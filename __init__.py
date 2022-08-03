"""
OptImaTo control package

Terminology
-----------
"Device": an instrument with which it is necessary to communicate for motion, detection, etc.
"Driver": a python object that can be instantiated to manage a device. In practice, a client to the corresponding device server.
"Device Server": a process that manages and interacts with a given device, through commands sent by one or more clients
"Socket Device Server": a device server that connects to a device through a TCP socket.

General principle
-----------------
The design of this software is made to address these limitations:
- Most devices allow only one connection at a time. It is often useful to access a device through multiple clients,
  for instance to probe for metadata or specific signals.
- Keeping logs of a device status requires a process that runs constantly and that keep alive a connection with that device.
- A crash in a control software might interrupt connections to all devices, requiring a complete reinitialization.
- Running all drivers in a single software might overload the computer resources
- Some devices must run on their own machine (Windows), so at the very least these devices need to be "remote controlled".

The solution is to decentralize the device management. Each device has a unique process running a corresponding Device
Server. Control and data access is done through one or more clients to these servers. Since all communication is through
TCP sockets, Device Servers can run on different computers, as long as they are on the same network. An "admin" status
is conferred only to one client at a time to ensure that no two processes attempt at controlling a device
simultaneously (all "read-only" methods are however allowed by non-admin clients).

In practice, this means that to each device requires two classes, the server (DeviceServer) and the client (Driver). The
idea is to keep the Device Server as thin as possible, with the "knowledge" related to the Device API implemented
mostly in the Driver class. This is easily done for all Socket Driver Servers, because then the Device Server simply
acts as a middleman, or a message broker. Things are more complicated for Driver Servers that interact with the device
through custom libraries, because the library calls have to be forwarded from the client to the server.


Additional classes
------------------
The DeviceServer subclasses are meant to be instantiated each on their own process, possibly on their own computer,
should be running constantly. Users should never need to touch these.
The Driver subclasses can be instantiated in any python program within the network. To the user, this should be the
low-level access for specific configuration, experimentation, and debugging.
Currently, apart from the X-ray source, devices fall in just two main categories: motion devices, and detectors. There
are therefore two higher level classes (Motor and Camera) that is meant to provide access to the underlying device
through a common interface. For instance, it might be that capturing a frame on one detector is done through a call of
the "detect" method, while on the other it is called "record_frame" - but with the Camera wrapper both are called
"snap". The hope is to make "Motors" and "Camera" instances sufficient for everyday use.

"""
import logging
import logging.handlers
import os
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

# dictionary of camera instances
cameras = {}

# Import all driver submodules
from . import aerotech
from . import mclennan
from . import mecademic
from . import microscope
from . import smaract
#from . import varex
#from . import pco
#from . import xspectrum
#from . import xps

#from . import mtffun_hans
#from . import pcofun_hans
#from . import xpsfun_ronan

from . import excillum

#from .ui import *
