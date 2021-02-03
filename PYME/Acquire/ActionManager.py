# -*- coding: utf-8 -*-
"""
Created on Sat May 28 23:12:24 2016

@author: david
"""
try:
    #python 2.x
    # noinspection PyCompatibility
    import Queue
except ImportError:
    #python 3.x
    import queue as Queue
    
import time
from PYME.contrib import dispatch
import weakref
import threading
from PYME.util import webframework
import numpy as np
import logging
logger = logging.getLogger(__name__)

class Action(object):
    '''
    Base Action method - over-ride the __call__ function in derived classes
    '''
    def __init__(self, **kwargs):
        self.params = kwargs
    
    def __call__(self, scope):
        pass
    
    def serialise(self):
        '''Convert to a .json serializable dictionary'''
        d = dict(self.params)
        
        then = getattr(self, '_then', None)
        if then:
            d['then'] = then.serialise()
            
        return {self.__class__.__name__ : d}
    
    
class FunctionAction(Action):
    '''Legacy action which evals a string.
    
    Used for handling old -style actions
    '''
    def __init__(self, functionName, args):
        self._fcn = functionName
        self._args = args
        
        Action.__init__(self, functionName=functionName, args=args)
        
    def __call__(self, scope):
        fcn = eval('.'.join(['scope', self._fcn]))
        #fcn = getattr(scope, self._fcn)
        return fcn(**self._args)
    
    def __repr__(self):
        return 'FunctionAction: %s(%s)' % (self._fcn, self._args)
    
    
class StateAction(Action):
    ''' Base class for actions which modify scope state, with chaining support
    
    NOTE: we currently do not support chaining off the end of actions (e.g. spooling) which are likely to take some time.
    This is because functions such as StartSpooling are non-blocking - they return a callback instead.
    '''
    def __init__(self, **kwargs):
        self._then=None
        Action.__init__(self, **kwargs)

    def then(self, task):
        self._then = task
            
    def _do_then(self, scope):
        if self._then is not None:
            return self._then(scope)


class UpdateState(StateAction):
    def __init__(self, **kwargs):
        self._state = kwargs
        StateAction.__init__(self, **kwargs)
        
    def __call__(self, scope):
        scope.state.update(self._state)
        return self._do_then(scope)
        
    def __repr__(self):
        return 'UpdateState: %s' % self._state
    

class CentreROIOn(StateAction):
    def __init__(self, x, y):
        StateAction.__init__(self, x=x, y=y)
        # TODO - write this however David wanted it
    def __call__(self, scope):
        scope.centre_roi_on(self.params['x'], self.params['y'])
        return self._do_then(scope)
    
    def __repr__(self):
        return 'CentreROIOn: %f, %f (x, y)' % (self.params['x'], self.params['y'])
        

class SpoolSeries(Action):
    def __init__(self, **kwargs):
        self._args = kwargs
        Action.__init__(self, **kwargs)
        
    def __call__(self, scope):
        return scope.spoolController.StartSpooling(**self._args)
        
    def __repr__(self):
        return 'SpoolSeries(%s)' % ( self._args)
        
def action_from_dict(serialised):
    assert(len(serialised) == 1)
    act, params = list(serialised.items())[0]
    
    then = params.pop('then', None)
    try:
        # TODO - use a slightly less broad dictionary for action lookup (or move actions to a separate module)
        a = globals()[act](**params)
    except KeyError:
        # Legacy string-based action queued in `Action` function method
        logger.warn('string-based function queuing is deprecated, see ActionManager.FunctionAction')
        return FunctionAction(act, params)
    if then:
        a.then(action_from_dict(then))
        
    return a


class ActionManager(object):
    """This implements a queue for actions which should be called sequentially.
    
    The main purpose of the ActionManager is to facilitate automated imaging by 
    allowing multiple operations to be queued. Rather than being strictly FIFO,
    different tasks can be asigned different priorities, with higher priority 
    tasks bubbling up and and being executed before lower priority tasks. This 
    allows high priority "imaging" tasks to be inserted into a stream of lower
    priority "monitoring" tasks if something interesting is detected during 
    monitoring.
    
    An individual action is a function which can be found within the scope of
    our microscope object (for more details see the QueueAction method).
    
    To function correctly the Tick() method should be called regularly - e.g.
    from a GUI timer.
    """
    def __init__(self, scope):
        """Initialise our action manager
        
        Parameters
        ----------
        
        scope : PYME.Acquire.microscope.microscope object
            The microscope. The function object to call for an action should be 
            accessible within the scope namespace, and will be resolved by
            calling eval('scope.functionName')
        
        """
        self.actionQueue = Queue.PriorityQueue()
        self.scope = weakref.ref(scope)
        
        #this will be assigned to a callback to indicate if the last task has completed        
        self.isLastTaskDone = None
        self.paused = False
        
        self.currentTask = None
        
        self.onQueueChange = dispatch.Signal()
        
        self._timestamp = 0

        self._monitoring = True
        self._monitor = threading.Thread(target=self._monitor_defunct)
        self._monitor.daemon = True
        self._monitor.start()
        
    def QueueAction(self, functionName, args, nice=10, timeout=1e6, 
                    max_duration=np.finfo(float).max):
        """Add an action to the queue. Legacy version for string based actions. Most applications should use queue_actions() below instead
        
        Parameters
        ----------
        
        functionName : string
            The name of a function relative to the microscope object.
            e.g. to `call scope.spoolController.StartSpooling()`, you would use
            a functionName of 'spoolController.StartSpooling'.
            
            The function should either return `None` if the operation has already
            completed, or function which evaluates to True once the operation
            has completed. See `scope.spoolController.StartSpooling()` for an
            example.
            
        args : dict
            a dictionary of arguments to pass the function    
        nice : int (or float)
            The priority with which to execute the function. Functions with a
            lower nice value execute first.
        timeout : float
            A timeout in seconds from the current time at which the action
            becomes irrelevant and should be ignored.
        max_duration : float
            A generous estimate, in seconds, of how long the task might take, 
            after which the lasers will be automatically turned off and the 
            action queue paused. This will not interrupt the current task, 
            though it has presumably already failed at that point. Intended as a
            safety feature for automated acquisitions, the check is every 3 s 
            rather than fine-grained.
            
        """
        curTime = time.time()    
        expiry = curTime + timeout
        
        #make sure our timestamps strictly increment
        self._timestamp = max(curTime, self._timestamp + 1e-3)
        
        #ensure FIFO behaviour for events with the same priority
        nice_ = nice + self._timestamp*1e-10
        
        self.actionQueue.put_nowait((nice_, FunctionAction(functionName, args), expiry, max_duration))
        self.onQueueChange.send(self)
        
    def queue_actions(self, actions, nice=10, timeout=1e6, max_duration=np.finfo(float).max):
        '''
        Queue a number of actions for subsequent execution
        
        Parameters
        ----------
        actions : list
            A list of Action instances
        nice : int (or float)
            The priority with which to execute the function. Functions with a
            lower nice value execute first.
        timeout : float
            A timeout in seconds from the current time at which the action
            becomes irrelevant and should be ignored.
        max_duration : float
            A generous estimate, in seconds, of how long the task might take,
            after which the lasers will be automatically turned off and the
            action queue paused. This will not interrupt the current task,
            though it has presumably already failed at that point. Intended as a
            safety feature for automated acquisitions, the check is every 3 s
            rather than fine-grained.

        Returns
        -------
        
        
        Examples
        --------
        
        >>> my_actions = [UpdateState({'Camera.ROI' : [50, 50, 200, 200]}),
        >>>      SpoolSeries(maxFrames=500, stack=False),
        >>>      UpdateState({'Camera.ROI' : [100, 100, 250, 250]}).then(SpoolSeries(maxFrames=500, stack=False)),
        >>>      ]
        >>>
        >>>ActionManager.queue_actions(my_actions)
        
        Note that the first two tasks are independant -

        '''
        for action in actions:
            curTime = time.time()
            expiry = curTime + timeout
        
            #make sure our timestamps strictly increment
            self._timestamp = max(curTime, self._timestamp + 1e-3)
        
            #ensure FIFO behaviour for events with the same priority
            nice_ = nice + self._timestamp * 1e-10
        
            self.actionQueue.put_nowait((nice_, action, expiry, max_duration))
            
        self.onQueueChange.send(self)
        
        
    def Tick(self, **kwargs):
        """Polling function to check if the current action is finished and, if so, start the next
        action if available.
        
        Should be called regularly for a timer or event loop.
        """
        if self.paused:
            return
            
        if (self.isLastTaskDone is None) or self.isLastTaskDone():
            try:
                self.currentTask = self.actionQueue.get_nowait()
                nice, action, expiry, max_duration = self.currentTask
                self._cur_task_kill_time = time.time() + max_duration
                self.onQueueChange.send(self)
            except Queue.Empty:
                self.currentTask = None
                return
            
            if expiry > time.time():
                print('%s, %s' % (self.currentTask, action))
                #fcn = eval('.'.join(['self.scope()', functionName]))
                self.isLastTaskDone = action(self.scope())
            else:
                past_expire = time.time() - expiry
                logger.debug('task expired %f s ago, ignoring %s' % (past_expire,
                                                                     self.currentTask))
    
    def _monitor_defunct(self):
        """
        polling thread method to check that if a task is being executed through
        the action manager it isn't taking longer than its `max_duration`.
        """
        while self._monitoring:
            if self.currentTask is not None:
                #logger.debug('here, %f s until kill' % (self._cur_task_kill_time - time.time()))
                if time.time() > self._cur_task_kill_time:
                    self.scope().turnAllLasersOff()
                    # pause and reset so we can start up again later
                    self.paused = True
                    self.isLastTaskDone = None
                    self.currentTask = None
                    self.onQueueChange.send(self)
                    logger.error('task exceeded specified max duration')
        
            time.sleep(3)
    
    def __del__(self):
        self._monitoring = False


class ActionManagerWebWrapper(object):
    def __init__(self, action_manager):
        """ Wraps an action manager instance with server endpoints

        Parameters
        ----------
        action_manager : ActionManager
            action manager instance to wrap
        """
        self.action_manager = action_manager

    @webframework.register_endpoint('/queue_actions', output_is_json=False)
    def queue_actions(self, body, nice=10, timeout=1e6, max_duration=np.finfo(float).max):
        """
        Add a list of actions to the queue
        
        Parameters
        ----------
        body - json formatted list of serialised actions (see example below)
        nice
        timeout
        max_duration

        Returns
        -------
        
        
        Example body
        ------------
        
        `[{'UpdateState':{'foo':'bar', 'then': {'SpoolSeries' : {...}}}]`

        """
        import json
        actions = [action_from_dict(a) for a in json.loads(body)]

        self.action_manager.queue_actions(actions, nice=int(nice), 
                                          timeout=float(timeout), 
                                          max_duration=float(max_duration))
        
    
    @webframework.register_endpoint('/queue_action', output_is_json=False)
    def queue_action(self, body):
        """
        adds an action to the queue

        Parameters
        ----------
        body: str
            json.dumps(dict) with the following keys:
                function_name : str
                    The name of a function relative to the microscope object.
                    e.g. to `call scope.spoolController.StartSpooling()`, you 
                    would use a functionName of 'spoolController.StartSpooling'.
                    
                    The function should either return `None` if the operation 
                    has already completed, or function which evaluates to True 
                    once the operation has completed. See 
                    `scope.spoolController.StartSpooling()` for an example.
                args : dict, optional
                    a dictionary of arguments to pass to `function_name`
                nice : int, optional
                    priority with which to execute the function, by default 10. 
                    Functions with a lower nice value execute first.
                timeout : float, optional
                    A timeout in seconds from the current time at which the 
                    action becomes irrelevant and should be ignored. By default
                    1e6.
                max_duration : float
                    A generous estimate, in seconds, of how long the task might
                    take, after which the lasers will be automatically turned 
                    off and the action queue paused.
        """
        import json
        params = json.loads(body)
        function_name = params['function_name']
        args = params.get('args', {})
        nice = params.get('nice', 10.)
        timeout = params.get('timeout', 1e6)
        max_duration = params.get('max_duration', np.finfo(float).max)

        self.action_manager.QueueAction(function_name, args, nice, timeout,
                                        max_duration)


class ActionManagerServer(webframework.APIHTTPServer, ActionManagerWebWrapper):
    def __init__(self, action_manager, port, bind_address=''):
        """
        Server process to expose queue_action functionality to everything on the
        cluster network.

        NOTE - this will likely not be around long, as it would be preferable to
        add the ActionManagerWebWrapper to
        `PYME.acquire_server.AcquireHTTPServer` and run a single server process
        on the microscope computer.

        Parameters
        ----------
        action_manager : ActionManager
            already initialized
        port : int
            port to listen on
        bind_address : str, optional
            specifies ip address to listen on, by default '' will bind to local 
            host.
        """
        webframework.APIHTTPServer.__init__(self, (bind_address, port))
        ActionManagerWebWrapper.__init__(self, action_manager)
        
        self.daemon_threads = True
        self._server_thread = threading.Thread(target=self._serve)
        self._server_thread.daemon_threads = True
        self._server_thread.start()

    def _serve(self):
        try:
            logger.info('Starting ActionManager server on %s:%s' % (self.server_address[0], self.server_address[1]))
            self.serve_forever()
        finally:
            logger.info('Shutting down ActionManager server ...')
            self.shutdown()
            self.server_close()

