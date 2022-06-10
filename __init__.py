"""
OptImaTo control package
"""
import logging
import logging.handlers
import os
import optimatools as opt
from . import util
from .util import logs, FileDict
from . import network_conf
from ._version import version
#from . import experiment

# Package-wide default log level (this sets up console handler)
util.logs.set_level(logging.INFO)

# Basic configuration
conf_path = os.path.expanduser("~/.optimato-labcontrol/")
os.makedirs(conf_path, exist_ok=True)
conf_file = os.path.join(conf_path, 'config.json')

# Persistent configuration and parameters
config = FileDict(conf_file)

# Data paths
data_path = '/data/optimato/'

# Setup logging
LOG_DIR = os.path.join(conf_path, 'logs/')
LOG_FILE = os.path.join(LOG_DIR, 'optimato-labcontrol.log')


# Errors
class ControllerRunningError(RuntimeError):
    pass


os.makedirs(LOG_DIR, exist_ok=True)
file_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1024*1024*10, backupCount=300, encoding='utf-8')

current_level = logging.root.level
if current_level <= 5:
    file_handler.setFormatter(logs.second_extended_formatter)
elif current_level <= logging.DEBUG:
    file_handler.setFormatter(logs.extended_formatter)
else:
    file_handler.setFormatter(logs.default_formatter)
logging.root.addHandler(file_handler)

# dictionary for driver instances
drivers = {}

# dictionary of motor instances
motors = {}

# Import all driver submodules
from . import aerotech
from . import mclennan
from . import mecademic
from . import microscope
from . import smaract

from . import mtffun_hans
#from . import pcofun_hans
from . import xpsfun_ronan

#from . import excillum

#from .ui import *
