#!/usr/bin/python

##################
# TiffDataSource.py
#
# Copyright David Baddeley, 2009
# d.baddeley@auckland.ac.nz
#
# This file may NOT be distributed without express permision from David Baddeley
#
##################

from PYME.ParallelTasks.relativeFiles import getFullFilename
#from PYME.FileUtils import readTiff
#import Image
#from PYME.misc import TiffImagePlugin #monkey patch PIL with improved tiff support from Priithon

#import numpy as np

from PYME.gohlke import tifffile

class DataSource:
    moduleName = 'TiffDataSource'
    def __init__(self, filename, taskQueue, chanNum = 0):
        self.filename = getFullFilename(filename)#convert relative path to full path
        self.chanNum = chanNum
        
        #self.data = readTiff.read3DTiff(self.filename)

        #self.im = Image.open(filename)

        #self.im.seek(0)

        #PIL's endedness support is subtly broken - try to fix it
        #NB this is untested for floating point tiffs
        #self.endedness = 'LE'
        #if self.im.ifd.prefix =='MM':
        #    self.endedness = 'BE'

        #to find the number of images we have to loop over them all
        #this is obviously not ideal as PIL loads the image data into memory for each
        #slice and this is going to represent a huge performance penalty for large stacks
        #should still let them be opened without having all images in memory at once though
        #self.numSlices = self.im.tell()
        
        #try:
        #    while True:
        #        self.numSlices += 1
        #        self.im.seek(self.numSlices)
                
        #except EOFError:
        #    pass

        print self.filename

        self.im = tifffile.TIFFfile(self.filename).series[0].pages


    def getSlice(self, ind):
        #self.im.seek(ind)
        #ima = np.array(im.getdata()).newbyteorder(self.endedness)
        #return ima.reshape((self.im.size[1], self.im.size[0]))
        #return self.data[:,:,ind]
        res =  self.im[ind].asarray(False, False)
        #if res.ndim == 3:
        #print res.shape
        #print self.chanNum
        res = res[0,self.chanNum, :,:].squeeze()
        #print res.shape
        return res

    def getSliceShape(self):
        #return (self.im.size[1], self.im.size[0])
        if len(self.im[0].shape) == 2:
            return self.im[0].shape
        else:
            return self.im[0].shape[1:3]
        #return self.data.shape[:2]

    def getNumSlices(self):
        return len(self.im)

    def getEvents(self):
        return []

    def release(self):
        #self.im.close()
        pass

    def reloadData(self):
        pass
