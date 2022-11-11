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

In practice, each driver is implemented as if it is meant to be the single instance connected to the device. The base class
`DriverBase` takes care of few things (logging, metadata collection), while `SocketDriverBase` has all what is needed to
connect to devices that have socket connections.
The module `proxydevice` provides server/client classes as well as decorators that transform all drivers into a
server/client pair. Any method of the driver can be "exposed" as remotely accessible with the method decorator
`@proxycall`. See the module doc for more info.

Additional classes
------------------
Currently, apart from the X-ray source, devices fall in just two main categories: motion devices, and detectors. There
is therefore a high-level class `Motor` meant to provide access to the underlying device through a common interface
(with methods inspired from the `spec` language). For detectors, the common interface is `CameraBase`, which is a
subclass of DriverBase. The hope is to make instances of `Motor` and `CameraBase` subclasses sufficient for everyday
use.

"""
import logging
import logging.handlers
import os
import platform
import json
import subprocess

from .network_conf import HOST_IPS
from . import util
from .util import logs, FileDict
from ._version import version

#
# SETUP LOGGING
#

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
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

LOG_DIR = os.path.join(conf_path, 'logs/')
LOG_FILE = os.path.join(LOG_DIR, 'optimato-labcontrol.log')


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

#
# IDENTIFY SYSTEM
#

uname = platform.uname()
LOCAL_HOSTNAME = uname.node
if uname.system == "Linux":
    iface_info = json.loads(subprocess.run(['ip', '-j', '-4',  'addr'], capture_output=True).stdout.decode())
    LOCAL_IP_LIST = [iface['addr_info'][0]['local'] for iface in iface_info]
elif uname.system == "Windows":
    s = subprocess.run(['ipconfig', '/allcompartments'], capture_output=True).stdout.decode()
    LOCAL_IP_LIST = [x.split(' ')[-1] for x in s.split('\r\n') if x.strip().startswith('IPv4')]
else:
    raise RuntimeError(f'Unknown system platform {uname.system}')

# Remove localhost (not there under windows)
try:
    LOCAL_IP_LIST.remove('127.0.0.1')
except ValueError:
    pass

# Check which machine this is
try:
    THIS_HOST = [name for name, ip in HOST_IPS.items() if ip in LOCAL_IP_LIST][0]
except IndexError:
    print('Host IP not part of the control network.')
    THIS_HOST = 'unknown'

print('\n'.join(['*{:^64s}*'.format(f"OptImaTo Lab Control"),
                 '*{:^64s}*'.format(f"Running on host '{LOCAL_HOSTNAME}'"),
                 '*{:^64s}*'.format(f"a.k.a. '{THIS_HOST}' with IP {LOCAL_IP_LIST}")
                 ])
      )


# Errors
class ControllerRunningError(RuntimeError):
    pass


# dictionary for driver instances
drivers = {}

# dictionary of motor instances
motors = {}

# dictionary of camera instances
cameras = {}

from .manager import init
# Import all driver submodules
#from . import aerotech
#from . import dummy
#from . import mclennan
#from . import mecademic
#from . import microscope
#from . import smaract
#from . import varex
#from . import pco
#from . import xspectrum
#from . import xps

#from . import mtffun_hans
#from . import pcofun_hans
#from . import xpsfun_ronan

#from .ui import *
