from .array_utils import *
from .plot_utils import *
from .image_correction import *
from .mpl_image_stack import *

# Silently fail if astra is not installed
try:
    from . import pyCTwrapper as pyCT
except ImportError:
    class PlaceHolder(object):
        def __getattribute__(self, item):
            raise RuntimeError("Astra toolbox not installed.")
    pyCT = PlaceHolder()

# Clear namespace
try:
    del array_utils, plot_utils, image_correction
except:
    pass
