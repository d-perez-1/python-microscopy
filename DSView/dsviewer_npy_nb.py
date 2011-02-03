#!/usr/bin/python

##################
# dsviewer_npy_nb.py
#
# Copyright David Baddeley, 2009
# d.baddeley@auckland.ac.nz
#
# This file may NOT be distributed without express permision from David Baddeley
#
##################

import wx
import wx.lib.agw.aui as aui

import PYME.misc.autoFoldPanel as afp
from PYME.misc.auiFloatBook import AuiNotebookWithFloatingPages
from PYME.FileUtils import h5ExFrames

import os
import sys

import PYME.cSMI as example
import numpy

import tables
import wx.py.crust
import pylab

from arrayViewPanel import ArraySettingsAndViewPanel
from PYME.Analysis.LMVis import recArrayView
import eventLogViewer
import fitInfo

from PYME.Acquire import MetaDataHandler
from PYME.Analysis import MetaData
from PYME.Analysis import MetadataTree
from PYME.Analysis.DataSources import HDFDataSource
from PYME.Analysis.DataSources import TQDataSource
#from PYME.Analysis.DataSources import TiffDataSource
from PYME.FileUtils import readTiff
from PYME.Analysis.LMVis import inpFilt
from PYME.Acquire.mytimer import mytimer

from PYME.Analysis import piecewiseMapping


class DSViewFrame(wx.Frame):
    def __init__(self, parent=None, title='', dstack = None, log = None, mdh = None, filename = None, queueURI = None, mode='LM'):
        wx.Frame.__init__(self,parent, -1, title,size=wx.Size(800,800), pos=(1100, 300))

        self.ds = dstack
        self.mdh = mdh
        self.log = log

        self.saved = False

        self.mode = mode
        self.vObjPos = None
        self.vObjFit = None

        self.analDispMode = 'z'

        #a timer object to update for us
        self.timer = mytimer()
        self.timer.Start(10000)

        #timer for playback
        self.tPlay = mytimer()
        self.tPlay.WantNotification.append(self.OnFrame)

        self.numAnalysed = 0
        self.numEvents = 0
        self.fitResults = []

        if (dstack == None):
            self.Load(filename)

        self._mgr = aui.AuiManager(agwFlags = aui.AUI_MGR_DEFAULT | aui.AUI_MGR_AUTONB_NO_CAPTION)

        atabstyle = self._mgr.GetAutoNotebookStyle()
        self._mgr.SetAutoNotebookStyle((atabstyle ^ aui.AUI_NB_BOTTOM) | aui.AUI_NB_TOP)

        # tell AuiManager to manage this frame
        self._mgr.SetManagedWindow(self)

        self._leftWindow1 = wx.Panel(self, -1, size = wx.Size(180, 1000))
        self._pnl = 0
                
        self.notebook1 = AuiNotebookWithFloatingPages(id=-1, parent=self, pos=wx.Point(0, 0), size=wx.Size(618,
              450), style=wx.aui.AUI_NB_TAB_SPLIT)

        self.notebook1.update = self.update


        #self.vp = MyViewPanel(self.notebook1, self.ds)
        self.vp = ArraySettingsAndViewPanel(self.notebook1, self.ds)

        self.mainWind = self

        self.sh = wx.py.shell.Shell(id=-1,
              parent=self.notebook1, pos=wx.Point(0, 0), size=wx.Size(618, 451), style=0, locals=self.__dict__, 
              introText='Python SMI bindings - note that help, license etc below is for Python, not PySMI\n\n')

        self.notebook1.AddPage(page=self.vp, select=True, caption='Data')
        self.notebook1.AddPage(page=self.sh, select=False, caption='Console')

        self.mdv = MetadataTree.MetadataPanel(self.notebook1, self.mdh)
        self.notebook1.AddPage(page=self.mdv, select=False, caption='Metadata')

        

        # Menu Bar
        self.menubar = wx.MenuBar()
        self.SetMenuBar(self.menubar)
        tmp_menu = wx.Menu()
        
        F_SAVE_POSITIONS = wx.NewId()
        F_SAVE_FITS = wx.NewId()
        tmp_menu.Append(wx.ID_SAVEAS, "Export", "", wx.ITEM_NORMAL)
        if self.mode == 'blob':
            tmp_menu.Append(F_SAVE_POSITIONS, "Save &Positions", "", wx.ITEM_NORMAL)
            tmp_menu.Append(F_SAVE_FITS, "Save &Fit Results", "", wx.ITEM_NORMAL)
        tmp_menu.Append(wx.ID_CLOSE, "Close", "", wx.ITEM_NORMAL)
        self.menubar.Append(tmp_menu, "File")


        

        mDeconvolution = wx.Menu()
        DECONV_ICTM = wx.NewId()
        DECONV_SAVE = wx.NewId()
        mDeconvolution.Append(DECONV_ICTM, "ICTM", "", wx.ITEM_NORMAL)
        mDeconvolution.AppendSeparator()
        mDeconvolution.Append(DECONV_SAVE, "Save", "", wx.ITEM_NORMAL)
        self.menubar.Append(mDeconvolution, "Deconvolution")

        mExtras = wx.Menu()
        EXTRAS_TILE = wx.NewId()
        mExtras.Append(EXTRAS_TILE, "&Tiling", "", wx.ITEM_NORMAL)
        self.menubar.Append(mExtras, "&Extras")

        # Menu Bar end
        #wx.EVT_MENU(self, wx.ID_SAVEAS, self.extractFrames)
        wx.EVT_MENU(self, wx.ID_SAVEAS, self.OnExport)
        wx.EVT_MENU(self, F_SAVE_POSITIONS, self.savePositions)
        wx.EVT_MENU(self, F_SAVE_FITS, self.saveFits)
        #wx.EVT_MENU(self, wx.ID_CLOSE, self.menuClose)
        #wx.EVT_MENU(self, EDIT_CLEAR_SEL, self.clearSel)
        #wx.EVT_MENU(self, EDIT_CROP, self.crop)
        wx.EVT_CLOSE(self, self.OnCloseWindow)

       

        wx.EVT_MENU(self, DECONV_ICTM, self.OnDeconvICTM)
        wx.EVT_MENU(self, DECONV_SAVE, self.saveDeconvolution)

        wx.EVT_MENU(self, EXTRAS_TILE, self.OnTile)
		
        self.statusbar = self.CreateStatusBar(1, wx.ST_SIZEGRIP)

        if self.mode == 'LM':
            self.InitLMMode()

        self.CreateFoldPanel()
        self._mgr.AddPane(self._leftWindow1, aui.AuiPaneInfo().
                          Name("sidebar").Left().CloseButton(False).CaptionVisible(False))

        self._mgr.AddPane(self.notebook1, aui.AuiPaneInfo().
                          Name("shell").Centre().CaptionVisible(False).CloseButton(False))

        self._mgr.Update()

        self.Layout()
        self.update()

    def LoadQueue(self, filename):
        import Pyro.core
        if queueURI == None:
            if 'PYME_TASKQUEUENAME' in os.environ.keys():
                taskQueueName = os.environ['PYME_TASKQUEUENAME']
            else:
                taskQueueName = 'taskQueue'
            self.tq = Pyro.core.getProxyForURI('PYRONAME://' + taskQueueName)
        else:
            self.tq = Pyro.core.getProxyForURI(queueURI)

        self.seriesName = filename[len('QUEUE://'):]

        self.dataSource = TQDataSource.DataSource(self.seriesName, self.tq)

        self.mdh = MetaDataHandler.QueueMDHandler(self.tq, self.seriesName)
        self.timer.WantNotification.append(self.dsRefresh)

    def Loadh5(self, filename):
        self.dataSource = HDFDataSource.DataSource(filename, None)
        if 'MetaData' in self.dataSource.h5File.root: #should be true the whole time
            self.mdh = MetaData.TIRFDefault
            self.mdh.copyEntriesFrom(MetaDataHandler.HDFMDHandler(self.dataSource.h5File))
        else:
            self.mdh = MetaData.TIRFDefault
            wx.MessageBox("Carrying on with defaults - no gaurantees it'll work well", 'ERROR: No metadata found in file ...', wx.OK)
            print "ERROR: No metadata fond in file ... Carrying on with defaults - no gaurantees it'll work well"

        MetaData.fillInBlanks(self.mdh, self.dataSource)

        from PYME.ParallelTasks.relativeFiles import getRelFilename
        self.seriesName = getRelFilename(filename)

        #try and find a previously performed analysis
        fns = filename.split(os.path.sep)
        cand = os.path.sep.join(fns[:-2] + ['analysis',] + fns[-2:]) + 'r'
        print cand
        if os.path.exists(cand):
            h5Results = tables.openFile(cand)

            if 'FitResults' in dir(h5Results.root):
                self.fitResults = h5Results.root.FitResults[:]
                self.resultsSource = inpFilt.h5rSource(h5Results)

                self.resultsMdh = MetaData.TIRFDefault
                self.resultsMdh.copyEntriesFrom(MetaDataHandler.HDFMDHandler(h5Results))

    def LoadKdf(self, filename):
        import PYME.cSMI as cSMI
        self.dataSource = cSMI.CDataStack_AsArray(cSMI.CDataStack(filename), 0).squeeze()
        self.mdh = MetaData.TIRFDefault

        try: #try and get metadata from the .log file
            lf = open(os.path.splitext(filename)[0] + '.log')
            from PYME.DSView import logparser
            lp = logparser.logparser()
            log = lp.parse(lf.read())
            lf.close()

            self.mdh.setEntry('voxelsize.z', log['PIEZOS']['Stepsize'])
        except:
            pass

        from PYME.ParallelTasks.relativeFiles import getRelFilename
        self.seriesName = getRelFilename(filename)

        self.mode = 'psf'

    def LoadPSF(self, filename):
        self.dataSource, vox = numpy.load(filename)
        self.mdh = MetaData.ConfocDefault

        self.mdh.setEntry('voxelsize.x', vox.x)
        self.mdh.setEntry('voxelsize.y', vox.y)
        self.mdh.setEntry('voxelsize.z', vox.z)


        from PYME.ParallelTasks.relativeFiles import getRelFilename
        self.seriesName = getRelFilename(filename)

        self.mode = 'psf'

    def LoadTiff(self, filename):
        #self.dataSource = TiffDataSource.DataSource(filename, None)
        self.dataSource = readTiff.read3DTiff(filename)

        xmlfn = os.path.splitext(filename)[0] + '.xml'
        if os.path.exists(xmlfn):
            self.mdh = MetaData.TIRFDefault
            self.mdh.copyEntriesFrom(MetaDataHandler.XMLMDHandler(xmlfn))
        else:
            self.mdh = MetaData.ConfocDefault

            from PYME.DSView.voxSizeDialog import VoxSizeDialog

            dlg = VoxSizeDialog(self)
            dlg.ShowModal()

            self.mdh.setEntry('voxelsize.x', dlg.GetVoxX())
            self.mdh.setEntry('voxelsize.y', dlg.GetVoxY())
            self.mdh.setEntry('voxelsize.z', dlg.GetVoxZ())


        from PYME.ParallelTasks.relativeFiles import getRelFilename
        self.seriesName = getRelFilename(filename)

        self.mode = 'blob'

    def Load(self, filename=None):
        if (filename == None):
            fdialog = wx.FileDialog(None, 'Please select Data Stack to open ...',
                wildcard='PYME Data|*.h5|TIFF files|*.tif|KDF files|*.kdf', style=wx.OPEN)
            succ = fdialog.ShowModal()
            if (succ == wx.ID_OK):
                filename = fdialog.GetPath()

        if not filename == None:
            if filename.startswith('QUEUE://'):
                self.LoadQueue(filename)
            elif filename.endswith('.h5'):
                self.Loadh5(filename)
            elif filename.endswith('.kdf'):
                self.LoadKdf(filename)
            elif filename.endswith('.psf'): #psf
                self.LoadPSF(filename)
            else: #try tiff
                self.LoadTiff(filename)


            self.PSFLocs = []

            self.ds = self.dataSource
            self.SetTitle(filename)
            self.saved = True

    def InitLMMode(self):
        import LMAnalysis
        if 'Protocol.DataStartsAt' in self.mdh.getEntryNames():
            self.vp.zp = self.mdh.getEntry('Protocol.DataStartsAt')
        else:
            self.vp.zp = self.mdh.getEntry('EstimatedLaserOnFrameNo')

        self.vp.Refresh()

        self.LMAnalyser = LMAnalysis.LMAnalyser(self)

        #self.sh.runfile(os.path.join(os.path.dirname(__file__),'fth5.py'))
        #self.mdv.rebuild()
        #self.elv = eventLogViewer.eventLogPanel(self.notebook1, self.ds.getEvents(), self.mdh, [0, self.ds.getNumSlices()]);
        events = self.ds.getEvents()
        st = self.mdh.getEntry('StartTime')
        if 'EndTime' in self.mdh.getEntryNames():
            et = self.mdh.getEntry('EndTime')
        else:
            et = piecewiseMapping.framesToTime(self.ds.getNumSlices(), events, self.mdh)
        self.elv = eventLogViewer.eventLogTPanel(self.notebook1, events, self.mdh, [0, et-st]);
        self.notebook1.AddPage(self.elv, 'Events')

        charts = []

        if 'ProtocolFocus' in self.elv.evKeyNames:
            self.zm = piecewiseMapping.GeneratePMFromEventList(self.elv.eventSource, self.mdh, self.mdh.getEntry('StartTime'), self.mdh.getEntry('Protocol.PiezoStartPos'))
            charts.append(('Focus [um]', self.zm, 'ProtocolFocus'))

        if 'ScannerXPos' in self.elv.evKeyNames:
            x0 = 0
            if 'Positioning.Stage_X' in self.mdh.getEntryNames():
                x0 = self.mdh.getEntry('Positioning.Stage_X')
            self.xm = piecewiseMapping.GeneratePMFromEventList(self.elv.eventSource, self.mdh, self.mdh.getEntry('StartTime'), x0, 'ScannerXPos', 0)
            charts.append(('XPos [um]', self.xm, 'ScannerXPos'))

        if 'ScannerYPos' in self.elv.evKeyNames:
            y0 = 0
            if 'Positioning.Stage_Y' in self.mdh.getEntryNames():
                y0 = self.mdh.getEntry('Positioning.Stage_Y')
            self.ym = piecewiseMapping.GeneratePMFromEventList(self.elv.eventSource, self.mdh, self.mdh.getEntry('StartTime'), y0, 'ScannerYPos', 0)
            charts.append(('YPos [um]', self.ym, 'ScannerYPos'))

        if 'ScannerZPos' in self.elv.evKeyNames:
            z0 = 0
            if 'Positioning.PIFoc' in self.mdh.getEntryNames():
                z0 = self.mdh.getEntry('Positioning.PIFoc')
            self.zm = piecewiseMapping.GeneratePMFromEventList(self.elv.eventSource, self.mdh, self.mdh.getEntry('StartTime'), z0, 'ScannerZPos', 0)
            charts.append(('ZPos [um]', self.zm, 'ScannerZPos'))

        self.elv.SetCharts(charts)

        if len(self.fitResults) > 0:
            self.vp.view.pointMode = 'lm'

            voxx = 1e3*self.mdh.getEntry('voxelsize.x')
            voxy = 1e3*self.mdh.getEntry('voxelsize.y')
            self.vp.view.points = numpy.vstack((self.fitResults['fitResults']['x0']/voxx, self.fitResults['fitResults']['y0']/voxy, self.fitResults['tIndex'])).T

            if 'Splitter' in self.mdh.getEntry('Analysis.FitModule'):
                self.vp.view.pointMode = 'splitter'
                self.vp.view.pointColours = self.fitResults['fitResults']['Ag'] > self.fitResults['fitResults']['Ar']

            from PYME.Analysis.LMVis import gl_render
            self.glCanvas = gl_render.LMGLCanvas(self.notebook1, False, vp = self.vp.do, vpVoxSize = voxx)
            self.glCanvas.cmap = pylab.cm.gist_rainbow

            self.notebook1.AddPage(page=self.glCanvas, select=True, caption='VisLite')

            xsc = self.ds.shape[0]*1.0e3*self.mdh.getEntry('voxelsize.x')/self.glCanvas.Size[0]
            ysc = self.ds.shape[1]*1.0e3*self.mdh.getEntry('voxelsize.y')/ self.glCanvas.Size[1]

            if xsc > ysc:
                self.glCanvas.setView(0, xsc*self.glCanvas.Size[0], 0, xsc*self.glCanvas.Size[1])
            else:
                self.glCanvas.setView(0, ysc*self.glCanvas.Size[0], 0, ysc*self.glCanvas.Size[1])

            #we have to wait for the gui to be there before we start changing stuff in the GL view
            self.timer.WantNotification.append(self.AddPointsToVis)

            self.fitInf = fitInfo.FitInfoPanel(self, self.fitResults, self.resultsMdh, self.vp.do.ds)
            self.notebook1.AddPage(page=self.fitInf, select=False, caption='Fit Info')

    def AddPointsToVis(self):
        self.glCanvas.setPoints(self.fitResults['fitResults']['x0'],self.fitResults['fitResults']['y0'],self.fitResults['tIndex'].astype('f'))
        self.glCanvas.setCLim((0, self.fitResults['tIndex'].max()))

        self.timer.WantNotification.remove(self.AddPointsToVis)


    def OnSize(self, event):
        wx.LayoutAlgorithm().LayoutWindow(self, self.notebook1)
        self.Refresh()
        event.Skip()

    def OnTile(self, event):
        from PYME.Analysis import deTile
        from PYME.DSView.dsviewer_npy import View3D
        
        x0 = self.mdh.getEntry('Positioning.Stage_X')
        xm = piecewiseMapping.GenerateBacklashCorrPMFromEventList(self.elv.eventSource, self.mdh, self.mdh.getEntry('StartTime'), x0, 'ScannerXPos', 0, .0055)
        
        y0 = self.mdh.getEntry('Positioning.Stage_Y')
        ym = piecewiseMapping.GenerateBacklashCorrPMFromEventList(self.elv.eventSource, self.mdh, self.mdh.getEntry('StartTime'), y0, 'ScannerYPos', 0, .0035)
        
        #dark = deTile.genDark(self.vp.do.ds, self.mdh)
        dark = self.mdh.getEntry('Camera.ADOffset')
        flat = deTile.guessFlat(self.vp.do.ds, self.mdh, dark)
        #flat = numpy.load('d:/dbad004/23_7_flat.npy')
        #flat = flat.reshape(list(flat.shape[:2]) + [1,])

        #print dark.shape, flat.shape

        split = False

        dt = deTile.tile(self.vp.do.ds, xm, ym, self.mdh, split=split, skipMoveFrames=False, dark=dark, flat=flat)#, mixmatrix = [[.3, .7], [.7, .3]])
        if dt.ndim > 2:
            View3D([dt[:,:,0][:,:,None], dt[:,:,1][:,:,None]], 'Tiled Image')
        else:
            View3D(dt, 'Tiled Image')


    def OnFoldPanelBarDrag(self, event):

        if event.GetDragStatus() == wx.SASH_STATUS_OUT_OF_RANGE:
            return

        if event.GetId() == self.ID_WINDOW_LEFT1:
            self._leftWindow1.SetDefaultSize(wx.Size(event.GetDragRect().width, 1000))


        # Leaves bits of itself behind sometimes
        wx.LayoutAlgorithm().LayoutWindow(self, self.notebook1)
        self.notebook1.Refresh()

        event.Skip()

    def CreateFoldPanel(self):

        # delete earlier panel
        self._leftWindow1.DestroyChildren()

        # recreate the foldpanelbar

#        self._pnl = fpb.FoldPanelBar(self._leftWindow1, -1, wx.DefaultPosition,
#                                     wx.Size(-1,-1))#, fpb.FPB_DEFAULT_STYLE,0)
#
#        self.Images = wx.ImageList(16,16)
#        self.Images.Add(GetExpandedIconBitmap())
#        self.Images.Add(GetCollapsedIconBitmap())

        hsizer = wx.BoxSizer(wx.VERTICAL)

        s = self._leftWindow1.GetBestSize()

        self._pnl = afp.foldPanel(self._leftWindow1, -1, wx.DefaultPosition,s)

        self.GenPlayPanel()
        #self.GenProfilePanel()
        if self.mode == 'LM':
            self.LMAnalyser.GenPointFindingPanel(self._pnl)
            self.LMAnalyser.GenAnalysisPanel(self._pnl)
            self.LMAnalyser.GenFitStatusPanel(self._pnl)
        elif self.mode == 'blob':
            self.GenBlobFindingPanel()
            self.GenBlobFitPanel()
            self.GenPSFPanel()
        else:
            self.GenPSFPanel()


        #item = self._pnl.AddFoldPanel("Filters", False, foldIcons=self.Images)
        #item = self._pnl.AddFoldPanel("Visualisation", False, foldIcons=self.Images)
        #wx.LayoutAlgorithm().LayoutWindow(self, self.notebook1)
        hsizer.Add(self._pnl, 1, wx.EXPAND, 0)
        self._leftWindow1.SetSizerAndFit(hsizer)
        self.Refresh()
        self.notebook1.Refresh()

    def GenPlayPanel(self):
        #item = self._pnl.AddFoldPanel("Playback", collapsed=False,
        #                              foldIcons=self.Images)
        item = afp.foldingPane(self._pnl, -1, caption="Playback", pinned = True)

        pan = wx.Panel(item, -1)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        hsizer = wx.BoxSizer(wx.HORIZONTAL)

        hsizer.Add(wx.StaticText(pan, -1, 'Pos:'), 0,wx.ALIGN_CENTER_VERTICAL|wx.LEFT,0)

        self.slPlayPos = wx.Slider(pan, -1, 0, 0, 100, style=wx.SL_HORIZONTAL)
        self.slPlayPos.Bind(wx.EVT_SCROLL_CHANGED, self.OnPlayPosChanged)
        hsizer.Add(self.slPlayPos, 1,wx.ALIGN_CENTER_VERTICAL)

        vsizer.Add(hsizer, 0,wx.ALL|wx.EXPAND, 0)
        hsizer = wx.BoxSizer(wx.HORIZONTAL)

        import os

        dirname = os.path.dirname(__file__)

        self.bSeekStart = wx.BitmapButton(pan, -1, wx.Bitmap(os.path.join(dirname, 'icons/media-skip-backward.png')))
        hsizer.Add(self.bSeekStart, 0,wx.ALIGN_CENTER_VERTICAL,0)
        self.bSeekStart.Bind(wx.EVT_BUTTON, self.OnSeekStart)

        self.bmPlay = wx.Bitmap(os.path.join(dirname,'icons/media-playback-start.png'))
        self.bmPause = wx.Bitmap(os.path.join(dirname,'icons/media-playback-pause.png'))
        self.bPlay = wx.BitmapButton(pan, -1, self.bmPlay)
        self.bPlay.Bind(wx.EVT_BUTTON, self.OnPlay)
        hsizer.Add(self.bPlay, 0,wx.ALIGN_CENTER_VERTICAL,0)

#        self.bSeekEnd = wx.BitmapButton(pan, -1, wx.Bitmap('icons/media-skip-forward.png'))
#        hsizer.Add(self.bSeekEnd, 0,wx.ALIGN_CENTER_VERTICAL,0)

        hsizer.Add(wx.StaticText(pan, -1, 'FPS:'), 0,wx.ALIGN_CENTER_VERTICAL|wx.LEFT,4)

        self.slPlaySpeed = wx.Slider(pan, -1, 5, 1, 50, style=wx.SL_HORIZONTAL)
        self.slPlaySpeed.Bind(wx.EVT_SCROLL_CHANGED, self.OnPlaySpeedChanged)
        hsizer.Add(self.slPlaySpeed, 1,wx.ALIGN_CENTER_VERTICAL)

        vsizer.Add(hsizer, 0,wx.TOP|wx.BOTTOM|wx.EXPAND, 4)
        pan.SetSizer(vsizer)
        vsizer.Fit(pan)

        #self._pnl.AddFoldPanelWindow(item, pan, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 5)
        item.AddNewElement(pan)
        self._pnl.AddPane(item)

    def OnPlay(self, event):
        if not self.tPlay.IsRunning():
            self.tPlay.Start(1000./self.slPlaySpeed.GetValue())
            self.bPlay.SetBitmapLabel(self.bmPause)
        else:
            self.tPlay.Stop()
            self.bPlay.SetBitmapLabel(self.bmPlay)

    def OnFrame(self):
        self.vp.do.zp +=1
        if self.vp.do.zp >= self.ds.shape[2]:
            self.vp.do.zp = 0

        self.update()

    def OnSeekStart(self, event):
        self.vp.do.zp = 0
        self.update()

    def OnPlaySpeedChanged(self, event):
        if self.tPlay.IsRunning():
            self.tPlay.Stop()
            self.tPlay.Start(1000./self.slPlaySpeed.GetValue())

    def OnPlayPosChanged(self, event):
        self.vp.do.zp = int((self.ds.shape[2]-1)*self.slPlayPos.GetValue()/100.)
        self.update()


    

    def GenBlobFindingPanel(self):
        item = afp.foldingPane(self._pnl, -1, caption="Object Finding", pinned = True)
#        item = self._pnl.AddFoldPanel("Object Finding", collapsed=False,
#                                      foldIcons=self.Images)

        pan = wx.Panel(item, -1)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)

        hsizer.Add(wx.StaticText(pan, -1, 'Threshold:'), 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.tThreshold = wx.TextCtrl(pan, -1, value='50', size=(40, -1))

        hsizer.Add(self.tThreshold, 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        pan.SetSizer(hsizer)
        hsizer.Fit(pan)

        self._pnl.AddFoldPanelWindow(item, pan, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 5)

        self.cbSNThreshold = wx.CheckBox(item, -1, 'SNR Threshold')
        self.cbSNThreshold.SetValue(False)

        self._pnl.AddFoldPanelWindow(item, self.cbSNThreshold, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 5)

        bFindObjects = wx.Button(item, -1, 'Find')


        bFindObjects.Bind(wx.EVT_BUTTON, self.OnFindObjects)
        #self._pnl.AddFoldPanelWindow(item, bFindObjects, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 10)
        item.AddNewElement(pan)
        self._pnl.AddPane(item)

    def GenPSFPanel(self):
        item = afp.foldingPane(self._pnl, -1, caption="PSF Extraction", pinned = True)
        #item = self._pnl.AddFoldPanel("PSF Extraction", collapsed=False,
        #                              foldIcons=self.Images)

        pan = wx.Panel(item, -1)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        hsizer = wx.BoxSizer(wx.HORIZONTAL)
#
#        hsizer.Add(wx.StaticText(pan, -1, 'Threshold:'), 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
#        self.tThreshold = wx.TextCtrl(pan, -1, value='50', size=(40, -1))
#
        bTagPSF = wx.Button(pan, -1, 'Tag', style=wx.BU_EXACTFIT)
        bTagPSF.Bind(wx.EVT_BUTTON, self.OnTagPSF)
        hsizer.Add(bTagPSF, 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        bClearTagged = wx.Button(pan, -1, 'Clear', style=wx.BU_EXACTFIT)
        bClearTagged.Bind(wx.EVT_BUTTON, self.OnClearTags)
        hsizer.Add(bClearTagged, 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        vsizer.Add(hsizer, 0,wx.ALL|wx.ALIGN_CENTER_HORIZONTAL, 5)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.Add(wx.StaticText(pan, -1, 'ROI Size:'), 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        self.tPSFROI = wx.TextCtrl(pan, -1, value='30,30,30', size=(40, -1))
        hsizer.Add(self.tPSFROI, 1,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.tPSFROI.Bind(wx.EVT_TEXT, self.OnPSFROI)

        vsizer.Add(hsizer, 0,wx.EXPAND|wx.ALL|wx.ALIGN_CENTER_HORIZONTAL, 0)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.Add(wx.StaticText(pan, -1, 'Blur:'), 0,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        self.tPSFBlur = wx.TextCtrl(pan, -1, value='.5,.5,1', size=(40, -1))
        hsizer.Add(self.tPSFBlur, 1,wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        vsizer.Add(hsizer, 0,wx.EXPAND|wx.ALL|wx.ALIGN_CENTER_HORIZONTAL, 0)

        bExtract = wx.Button(pan, -1, 'Extract', style=wx.BU_EXACTFIT)
        bExtract.Bind(wx.EVT_BUTTON, self.OnExtractPSF)
        vsizer.Add(bExtract, 0,wx.ALL|wx.ALIGN_RIGHT, 5)

        pan.SetSizer(vsizer)
        vsizer.Fit(pan)

        #self._pnl.AddFoldPanelWindow(item, pan, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 5)
        item.AddNewElement(pan)
        self._pnl.AddPane(item)
#
#        self.cbSNThreshold = wx.CheckBox(item, -1, 'SNR Threshold')
#        self.cbSNThreshold.SetValue(False)
#
#        self._pnl.AddFoldPanelWindow(item, self.cbSNThreshold, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 5)

        
    def OnTagPSF(self, event):
        from PYME.PSFEst import extractImages
        rsx, rsy, rsz = [int(s) for s in self.tPSFROI.GetValue().split(',')]
        dx, dy, dz = extractImages.getIntCenter(self.dataSource[(self.vp.do.xp-rsx):(self.vp.do.xp+rsx + 1),(self.vp.do.yp-rsy):(self.vp.do.yp+rsy+1), :])
        self.PSFLocs.append((self.vp.do.xp + dx, self.vp.do.yp + dy, dz))
        self.vp.view.psfROIs = self.PSFLocs
        self.vp.view.Refresh()

    def OnClearTags(self, event):
        self.PSFLocs = []
        self.vp.view.psfROIs = self.PSFLocs
        self.vp.view.Refresh()

    def OnPSFROI(self, event):
        try:
            psfROISize = [int(s) for s in self.tPSFROI.GetValue().split(',')]
            self.vp.view.psfROISize = psfROISize
            self.vp.Refresh()
        except:
            pass

    def OnExtractPSF(self, event):
        if (len(self.PSFLocs) > 0):
            from PYME.PSFEst import extractImages

            psfROISize = [int(s) for s in self.tPSFROI.GetValue().split(',')]
            psfBlur = [float(s) for s in self.tPSFBlur.GetValue().split(',')]
            #print psfROISize
            psf = extractImages.getPSF3D(self.dataSource, self.PSFLocs, psfROISize, psfBlur)

            from pylab import *
            import cPickle
            imshow(psf.max(2))

            fdialog = wx.FileDialog(None, 'Save PSF as ...',
                wildcard='PSF file (*.psf)|*.psf|H5P file (*.h5p)|*.h5p', style=wx.SAVE|wx.HIDE_READONLY)
            succ = fdialog.ShowModal()
            if (succ == wx.ID_OK):
                fpath = fdialog.GetPath()
                #save as a pickle containing the data and voxelsize

                if fpath.endswith('.psf'):
                    fid = open(fpath, 'wb')
                    cPickle.dump((psf, self.mdh.voxelsize), fid, 2)
                    fid.close()
                else:
                    import tables
                    h5out = tables.openFile(fpath,'w')
                    filters=tables.Filters(5,'zlib',shuffle=True)

                    xSize, ySize, nFrames = psf.shape

                    ims = h5out.createEArray(h5out.root,'PSFData',tables.Float32Atom(),(0,xSize,ySize), filters=filters, expectedrows=nFrames)
                    for frameN in range(nFrames):
                        ims.append(psf[:,:,frameN][None, :,:])
                        ims.flush()

                    outMDH = MetaDataHandler.HDFMDHandler(h5out)

                    outMDH.copyEntriesFrom(self.mdh)
                    outMDH.setEntry('psf.originalFile', self.seriesName)

                    h5out.flush()
                    h5out.close()

    def OnDeconvICTM(self, event):
        from PYME.Deconv.deconvDialogs import DeconvSettingsDialog,DeconvProgressDialog

        dlg = DeconvSettingsDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            from PYME.Deconv import dec, decThread
            nIter = dlg.GetNumIterationss()
            regLambda = dlg.GetRegularisationLambda()

            self.dlgDeconProg = DeconvProgressDialog(self, nIter)
            self.dlgDeconProg.Show()

            psf, vs = numpy.load(dlg.GetPSFFilename())

            self.dec = dec.dec_conv()
            self.dec.psf_calc(psf, self.ds.shape)

            self.decT = decThread.decThread(self.dec, self.ds.ravel(), regLambda, nIter)
            self.decT.start()

            self.deconTimer = mytimer()
            self.deconTimer.WantNotification.append(self.OnDeconTimer)

            self.deconTimer.Start(100)


    def OnDeconEnd(self, sucess):
        self.dlgDeconProg.Destroy()
        if sucess:
            if 'decvp' in dir(self):
                for pNum in range(self.notebook1.GetPageCount()):
                    if self.notebook1.GetPage(pNum) == self.decvp:
                        self.notebook1.DeletePage(pNum)
            self.decvp = MyViewPanel(self.notebook1, self.decT.res)
            self.notebook1.AddPage(page=self.decvp, select=True, caption='Deconvolved')




    def OnDeconTimer(self, caller=None):
        if self.decT.isAlive():
            if not self.dlgDeconProg.Tick(self.dec):
                self.decT.kill()
                self.OnDeconEnd(False)
        else:
            self.deconTimer.Stop()
            self.OnDeconEnd(True)

            


            
                    


    def OnFindObjects(self, event):
        threshold = float(self.tThreshold.GetValue())

        from PYME.Analysis.ofind3d import ObjectIdentifier

        if not 'ofd' in dir(self):
            #create an object identifier
            self.ofd = ObjectIdentifier(self.dataSource)

        #and identify objects ...
        if self.cbSNThreshold.GetValue(): #don't detect objects in poisson noise
            fudgeFactor = 1 #to account for the fact that the blurring etc... in ofind doesn't preserve intensities - at the moment completely arbitrary so a threshold setting of 1 results in reasonable detection.
            threshold =  (numpy.sqrt(self.mdh.Camera.ReadNoise**2 + numpy.maximum(self.mdh.Camera.ElectronsPerCount*(self.mdh.Camera.NoiseFactor**2)*(self.dataSource.astype('f') - self.mdh.Camera.ADOffset)*self.mdh.Camera.TrueEMGain, 1))/self.mdh.Camera.ElectronsPerCount)*fudgeFactor*threshold
            self.ofd.FindObjects(threshold, 0)
        else:
            self.ofd.FindObjects(threshold)
        
        self.vp.points = numpy.array([[p.x, p.y, p.z] for p in self.ofd])

        self.objPosRA = numpy.rec.fromrecords(self.vp.points, names='x,y,z')

        if self.vObjPos == None:
            self.vObjPos = recArrayView.recArrayPanel(self.notebook1, self.objPosRA)
            self.notebook1.AddPage(self.vObjPos, 'Object Positions')
        else:
            self.vObjPos.grid.SetData(self.objPosRA)

        self.update()

    def GenBlobFitPanel(self):
        item = afp.foldingPane(self._pnl, -1, caption="Object Fitting", pinned = True)
#        item = self._pnl.AddFoldPanel("Object Fitting", collapsed=False,
#                                      foldIcons=self.Images)

        bFitObjects = wx.Button(item, -1, 'Fit')


        bFitObjects.Bind(wx.EVT_BUTTON, self.OnFitObjects)
        #self._pnl.AddFoldPanelWindow(item, bFitObjects, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 10)
        item.AddNewElement(bFitObjects)
        self._pnl.AddPane(item)

    def OnFitObjects(self, event):
        import PYME.Analysis.FitFactories.Gauss3DFitR as fitMod

        fitFac = fitMod.FitFactory(self.dataSource, self.mdh)

        self.objFitRes = numpy.empty(len(self.ofd), fitMod.FitResultsDType)
        for i in range(len(self.ofd)):
            p = self.ofd[i]
            try:
                self.objFitRes[i] = fitFac.FromPoint(round(p.x), round(p.y), round(p.z))
            except:
                pass


        if self.vObjFit == None:
            self.vObjFit = recArrayView.recArrayPanel(self.notebook1, self.objFitRes['fitResults'])
            self.notebook1.AddPage(self.vObjFit, 'Fitted Positions')
        else:
            self.vObjFit.grid.SetData(self.objFitRes)

        self.update()

    

    def GenProfilePanel(self):
        item = afp.foldingPane(self._pnl, -1, caption="Intensity Profile", pinned = True)
#        item = self._pnl.AddFoldPanel("Intensity Profile", collapsed=False,
#                                      foldIcons=self.Images)

        bPlotProfile = wx.Button(item, -1, 'Plot')

        bPlotProfile.Bind(wx.EVT_BUTTON, self.OnPlotProfile)
        #self._pnl.AddFoldPanelWindow(item, bPlotProfile, fpb.FPB_ALIGN_WIDTH, fpb.FPB_DEFAULT_SPACING, 10)
        item.AddNewElement(bPlotProfile)
        self._pnl.AddPane(item)

        
    def OnPlotProfile(self, event):
        x,p,d, pi = self.vp.GetProfile(50, background=[7,7])

        pylab.figure(1)
        pylab.clf()
        pylab.step(x,p)
        pylab.step(x, 10*d - 30)
        pylab.ylim(-35,pylab.ylim()[1])

        pylab.xlim(x.min(), x.max())

        pylab.xlabel('Time [%3.2f ms frames]' % (1e3*self.mdh.getEntry('Camera.CycleTime')))
        pylab.ylabel('Intensity [counts]')

        fr = self.fitResults[pi]

        if not len(fr) == 0:
            pylab.figure(2)
            pylab.clf()
            
            pylab.subplot(211)
            pylab.errorbar(fr['tIndex'], fr['fitResults']['x0'] - self.vp.do.xp*1e3*self.mdh.getEntry('voxelsize.x'), fr['fitError']['x0'], fmt='xb')
            pylab.xlim(x.min(), x.max())
            pylab.xlabel('Time [%3.2f ms frames]' % (1e3*self.mdh.getEntry('Camera.CycleTime')))
            pylab.ylabel('x offset [nm]')

            pylab.subplot(212)
            pylab.errorbar(fr['tIndex'], fr['fitResults']['y0'] - self.vp.do.yp*1e3*self.mdh.getEntry('voxelsize.y'), fr['fitError']['y0'], fmt='xg')
            pylab.xlim(x.min(), x.max())
            pylab.xlabel('Time [%3.2f ms frames]' % (1e3*self.mdh.getEntry('Camera.CycleTime')))
            pylab.ylabel('y offset [nm]')

            pylab.figure(3)
            pylab.clf()

            pylab.errorbar(fr['fitResults']['x0'] - self.vp.do.xp*1e3*self.mdh.getEntry('voxelsize.x'),fr['fitResults']['y0'] - self.vp.do.yp*1e3*self.mdh.getEntry('voxelsize.y'), fr['fitError']['x0'], fr['fitError']['y0'], fmt='xb')
            #pylab.xlim(x.min(), x.max())
            pylab.xlabel('x offset [nm]')
            pylab.ylabel('y offset [nm]')



    


    def update(self):
        #self.vp.imagepanel.Refresh()
        self.vp.update()
        self.statusbar.SetStatusText('Slice No: (%d/%d)    x: %d    y: %d    Frames Analysed: %d    Events detected: %d' % (self.vp.do.zp, self.vp.do.ds.shape[2], self.vp.do.xp, self.vp.do.yp, self.numAnalysed, self.numEvents))
        self.slPlayPos.SetValue((100*self.vp.do.zp)/max(1,self.vp.do.ds.shape[2]-1))

        if 'fitInf' in dir(self) and not self.tPlay.IsRunning():
            self.fitInf.UpdateDisp(self.vp.view.PointsHitTest())

        if not self.tPlay.IsRunning():
            self.vp.optionspanel.RefreshHists()

        if 'decvp' in dir(self):
            self.decvp.imagepanel.Refresh()

    def saveStack(self, event=None):
        fdialog = wx.FileDialog(None, 'Save Data Stack as ...',
            wildcard='*.kdf', style=wx.SAVE|wx.HIDE_READONLY)
        succ = fdialog.ShowModal()
        if (succ == wx.ID_OK):
            self.ds.SaveToFile(fdialog.GetPath().encode())
            if not (self.log == None):
                lw = logparser.logwriter()
                s = lw.write(self.log)
                log_f = file('%s.log' % fdialog.GetPath().split('.')[0], 'w')
                log_f.write(s)
                log_f.close()
                
            self.SetTitle(fdialog.GetFilename())
            self.saved = True

    def extractFrames(self, event=None):
        dlg = wx.TextEntryDialog(self, 'Enter the range of frames to extract ...',
                'Extract Frames', '0:%d' % self.ds.getNumSlices())

        if dlg.ShowModal() == wx.ID_OK:
            ret = dlg.GetValue().split(':')

            start = int(ret[0])
            finish = int(ret[1])

            if len(ret) == 3:
                subsamp = int(ret[2])
            else:
                subsamp = 1
            
            fdialog = wx.FileDialog(None, 'Save Extracted Frames as ...',
                wildcard='*.h5', style=wx.SAVE|wx.HIDE_READONLY)
            succ = fdialog.ShowModal()
            if (succ == wx.ID_OK):
                h5ExFrames.extractFrames(self.ds, self.mdh, self.seriesName, fdialog.GetPath(), start, finish, subsamp)

            fdialog.Destroy()
        dlg.Destroy()

    def OnExport(self, event=None):
        import dataExporter

        if 'getEvents' in dir(self.ds):
            evts = self.ds.getEvents()
        else:
            evts = []

        dataExporter.CropExportData(self.vp.view, self.mdh, evts, self.seriesName)

    def savePositions(self, event=None):
        fdialog = wx.FileDialog(None, 'Save Positions ...',
            wildcard='Tab formatted text|*.txt', defaultFile=os.path.splitext(self.seriesName)[0] + '_pos.txt', style=wx.SAVE|wx.HIDE_READONLY)
        succ = fdialog.ShowModal()
        if (succ == wx.ID_OK):
            outFilename = fdialog.GetPath().encode()

            of = open(outFilename, 'w')
            of.write('\t'.join(self.objPosRA.dtype.names) + '\n')

            for obj in self.objPosRA:
                of.write('\t'.join([repr(v) for v in obj]) + '\n')
            of.close()

            npFN = os.path.splitext(outFilename)[0] + '.npy'

            numpy.save(npFN, self.objPosRA)

    def saveDeconvolution(self, event=None):
        fdialog = wx.FileDialog(None, 'Save Positions ...',
            wildcard='TIFF Files|*.tif', defaultFile=os.path.splitext(self.seriesName)[0] + '_dec.tif', style=wx.SAVE|wx.HIDE_READONLY)
        succ = fdialog.ShowModal()
        if (succ == wx.ID_OK):
            outFilename = fdialog.GetPath()

            from PYME.FileUtils import saveTiffStack

            saveTiffStack.saveTiffMultipage(self.dec.res, outFilename)

            

            
            
    def saveFits(self, event=None):
        fdialog = wx.FileDialog(None, 'Save Fit Results ...',
            wildcard='Tab formatted text|*.txt', defaultFile=os.path.splitext(self.seriesName)[0] + '_fits.txt', style=wx.SAVE|wx.HIDE_READONLY)
        succ = fdialog.ShowModal()
        if (succ == wx.ID_OK):
            outFilename = fdialog.GetPath().encode()

            of = open(outFilename, 'w')
            of.write('\t'.join(self.objFitRes['fitResults'].dtype.names) + '\n')

            for obj in self.objFitRes['fitResults']:
                of.write('\t'.join([repr(v) for v in obj]) + '\n')
            of.close()

            npFN = os.path.splitext(outFilename)[0] + '.npy'

            numpy.save(npFN, self.objFitRes)

    def menuClose(self, event):
        self.Close()

    def OnCloseWindow(self, event):
        pylab.close('all')
        if (not self.saved):
            dialog = wx.MessageDialog(self, "Save data stack?", "pySMI", wx.YES_NO|wx.CANCEL)
            ans = dialog.ShowModal()
            if(ans == wx.ID_YES):
                self.saveStack()
                self.Destroy()
            elif (ans == wx.ID_NO):
                self.Destroy()
            else: #wxID_CANCEL:   
                if (not event.CanVeto()): 
                    self.Destroy()
                else:
                    event.Veto()
        else:
            self.Destroy()
			
    def clearSel(self, event):
        self.vp.ResetSelection()
        self.vp.Refresh()
        
    def crop(self, event):
        cd = dCrop.dCrop(self, self.vp)
        if cd.ShowModal():
            ds2 = example.CDataStack(self.ds, cd.x1, cd.y1, cd.z1, cd.x2, cd.y2, cd.z2, cd.chs)
            dvf = DSViewFrame(self.GetParent(), '--cropped--', ds2)
            dvf.Show()

    def dsRefresh(self):
        #zp = self.vp.do.zp #save z -position
        self.vp.do.SetDataStack(self.ds)
        #self.vp.do.zp = zp #restore z position
        self.elv.SetEventSource(self.ds.getEvents())
        self.elv.SetRange([0, self.ds.getNumSlices()])
        
        if 'ProtocolFocus' in self.elv.evKeyNames:
            self.zm = piecewiseMapping.GeneratePMFromEventList(self.elv.eventSource, self.mdh.getEntry('Camera.CycleTime'), self.mdh.getEntry('StartTime'), self.mdh.getEntry('Protocol.PiezoStartPos'))
            self.elv.SetCharts([('Focus [um]', self.zm, 'ProtocolFocus'),])

        self.update()

    def analRefresh(self):
        newNumAnalysed = self.tq.getNumberTasksCompleted(self.seriesName)
        if newNumAnalysed > self.numAnalysed:
            self.numAnalysed = newNumAnalysed
            newResults = self.tq.getQueueData(self.seriesName, 'FitResults', len(self.fitResults))
            if len(newResults) > 0:
                if len(self.fitResults) == 0:
                    self.fitResults = newResults
                else:
                    self.fitResults = numpy.concatenate((self.fitResults, newResults))
                self.progPan.fitResults = self.fitResults

                self.vp.points = numpy.vstack((self.fitResults['fitResults']['x0'], self.fitResults['fitResults']['y0'], self.fitResults['tIndex'])).T

                self.numEvents = len(self.fitResults)

                if self.analDispMode == 'z' and (('zm' in dir(self)) or ('z0' in self.fitResults['fitResults'].dtype.fields)):
                    #display z as colour
                    if 'zm' in dir(self): #we have z info
                        if 'z0' in self.fitResults['fitResults'].dtype.fields:
                            z = 1e3*self.zm(self.fitResults['tIndex'].astype('f')).astype('f')
                            z_min = z.min() - 500
                            z_max = z.max() + 500
                            z = z + self.fitResults['fitResults']['z0']
                            self.glCanvas.setPoints(self.fitResults['fitResults']['x0'],self.fitResults['fitResults']['y0'],z)
                            self.glCanvas.setCLim((z_min, z_max))
                        else:
                            z = self.zm(self.fitResults['tIndex'].astype('f')).astype('f')
                            self.glCanvas.setPoints(self.fitResults['fitResults']['x0'],self.fitResults['fitResults']['y0'],z)
                            self.glCanvas.setCLim((z.min(), z.max()))
                    elif 'z0' in self.fitResults['fitResults'].dtype.fields:
                        z = self.fitResults['fitResults']['z0']
                        self.glCanvas.setPoints(self.fitResults['fitResults']['x0'],self.fitResults['fitResults']['y0'],z)
                        self.glCanvas.setCLim((-1e3, 1e3))

                elif self.analDispMode == 'gFrac' and 'Ag' in self.fitResults['fitResults'].dtype.fields:
                    #display ratio of colour channels as point colour
                    c = self.fitResults['fitResults']['Ag']/(self.fitResults['fitResults']['Ag'] + self.fitResults['fitResults']['Ar'])
                    self.glCanvas.setPoints(self.fitResults['fitResults']['x0'],self.fitResults['fitResults']['y0'],c)
                    self.glCanvas.setCLim((0, 1))

                else:
                    #default to time
                    self.glCanvas.setPoints(self.fitResults['fitResults']['x0'],self.fitResults['fitResults']['y0'],self.fitResults['tIndex'].astype('f'))
                    self.glCanvas.setCLim((0, self.numAnalysed))

        if (self.tq.getNumberOpenTasks(self.seriesName) + self.tq.getNumberTasksInProgress(self.seriesName)) == 0 and 'SpoolingFinished' in self.mdh.getEntryNames():
            self.statusbar.SetBackgroundColour(wx.GREEN)
            self.statusbar.Refresh()

        self.progPan.draw()
        self.progPan.Refresh()
        self.Refresh()
        self.update()



class MyApp(wx.App):
    def OnInit(self):
        #wx.InitAllImageHandlers()
        if (len(sys.argv) == 2):
            vframe = DSViewFrame(None, sys.argv[1], filename=sys.argv[1])
        elif (len(sys.argv) == 3):
            vframe = DSViewFrame(None, sys.argv[1], filename=sys.argv[1], queueURI=sys.argv[2])
        else:
            vframe = DSViewFrame(None, '')           

        self.SetTopWindow(vframe)
        vframe.Show(1)

        return 1

# end of class MyApp

def main():
    app = MyApp(0)
    app.MainLoop()


if __name__ == "__main__":
    main()
