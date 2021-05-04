"""
Common logic for loading a PSF
"""
import numpy as np
from collections import namedtuple
from PYME.IO.image import ImageStack

import logging
logger = logging.getLogger(__name__)

#VoxNM = namedtuple('VoxNM', 'x, y, z')

def load_psf(filename):
    """Load a PSF from an image file"""
    img = ImageStack(filename=filename)
    ps = img.data_xytc[:, :, :,0].squeeze()
    vox_nm = img.voxelsize_nm
    
    #sanity checks
    if not issubclass(ps.dtype.type, np.floating):
        raise RuntimeError('Expecting floating point PSF data. Was the PSF generated by PYME?')
    
    if (ps.shape[0] < 40) or (ps.shape[0] > 100):
        logging.warning('PSF shape (%s) seems odd. Expecting a shape around [61,61,61]' % str(ps.shape))
    
    return ps, vox_nm