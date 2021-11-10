import logging
import os
from ..util import logs, FileDict

# Basic configuration
conf_path = os.path.expanduser("~/.optimato-labcontrol/")
conf_file = os.path.join(conf_path, 'config.json')

# Persistent configuration and parameters
config = FileDict(conf_file)

# Default state: not a daemon
__DAEMON__ = False

# Setup logging
LOG_DIR = os.path.join(os.path.expanduser('~'), '.logs/')
LOG_FILE = os.path.join(LOG_DIR, 'optimato-labcontrol.log')


# Errors
class ControllerRunningError(RuntimeError):
    pass


if not os.path.exists(LOG_DIR):
    os.mkdir(LOG_DIR)
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
from . import microscope
from . import smaract

from . import mtffun_hans
from . import pcofun_hans
from . import xpsfun_ronan

from . import excillum

from .ui import *

