"""
Lab control package

Terminology
-----------
"Device": an instrument with which it is necessary to communicate for motion, detection, etc.
"Driver": a python object that can be instantiated to manage a device.
"Socket Driver": a driver that communicates with a device through a socket connection.
"Proxy Server": an object that manages one driver and accepts connection from proxy clients to control this driver.
"Proxy Client": a client that connects to a Proxy Server and reproduces the driver interface through method calls.

General principle
-----------------
The design of this software is made to address these limitations:
- Most devices allow only one connection at a time. It is often useful to access a device through multiple clients,
  for instance to probe for metadata or specific signals.
- Keeping logs of a device status requires a process that runs constantly and that keep alive a connection with that device.
- A crash in a control software might interrupt connections to all devices, requiring a complete reinitialization.
- Running all drivers in a single software might overload the computer resources
- Some devices must run on their own machine (Windows), so at the very least these devices need to be "remote controlled".

The solution is a distributed device management. Each device is managed by a driver that runs on a unique process, and is
wrapped by a proxy server. Control and data access is done through one or more proxy clients to the proxy server. Since
all communication is through TCP sockets, drivers can run on different computers, as long as they are on the same network.
An "admin" status is conferred only to one client at a time to ensure that no two processes attempt at controlling a device
simultaneously (all "read-only" methods are however allowed by non-admin clients).

In practice, each driver is implemented as if it is meant to be the single instance connected to the device. The base class
`DriverBase` takes care of few things (logging, configuration, metadata collection, periodic calls), while `SocketDriverBase`
has all what is needed to connect to devices that have socket connections.
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

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

# The name of this lab
LABORATORY = "OptImaTo"

# The base path for data saving
data_path = '/data3/lab/'

import os
import platform
import json
import subprocess
import multiprocessing

# This is currently needed because filewriter and filestreamer use multiprocessing
# and must run on both linux and windows.
try:
    multiprocessing.set_start_method('spawn')
except RuntimeError:
    pass

from .network_conf import HOST_IPS
from . import util
from .util import FileDict
from ._version import version

# Basic configuration
conf_path = os.path.expanduser(f"~/.{LABORATORY.lower()}-labcontrol/")
os.makedirs(conf_path, exist_ok=True)
conf_file = os.path.join(conf_path, 'config.json')

# Persistent configuration and parameters
config = util.FileDict(conf_file)

#
# SETUP LOGGING
#
# This import takes care of setting up everything
# File logging
LOG_DIR = os.path.join(conf_path, 'logs/')
os.makedirs(LOG_DIR, exist_ok=True)
from .util import logs

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

print('\n'.join(['*{:^64s}*'.format(f"{LABORATORY} Lab Control"),
                 '*{:^64s}*'.format(f"Running on host '{LOCAL_HOSTNAME}'"),
                 '*{:^64s}*'.format(f"a.k.a. '{THIS_HOST}' with IP {LOCAL_IP_LIST}")
                 ])
      )

# Log to file interactive sessions
if util.uitools.is_interactive():
    log_file_name = os.path.join(LOG_DIR, f'{LABORATORY.lower()}-labcontrol.log')
    logs.log_to_file(log_file_name)
    print('*{0:^64}*'.format('[Logging to file on this host]'))
else:
    print('*{0:^64}*'.format('[Not logging to file on this host]'))

print()

# Dictionary for driver classes (populated when drivers module load)
Classes = {}


def register_proxy_client(cls):
    """
    A simple decorator to store all proxydriver clients in the `Clients` dictionary. Then
    Starting a clients can be done based on names, e.g. Clients['varex'].Client()
    """
    Classes[cls.__name__.lower()] = cls
    return cls


def client_or_None(name, admin=True, client_name=None, inexistent_ok=True):
    """
    Helper function to create a client to a named driver

    Args:
        name (str): driver name
        admin (bool): try to connect as admin [default True]
        client_name: an identifier for the client
        inexistent_ok: if True, ignore unknown names.

    Returns:
        An instance of the proxy client connected to named driver, or None if connection failed.
    """

    from .util.proxydevice import ProxyDeviceError
    d = None
    if name not in Classes:
        if inexistent_ok:
            logs.logger.info(f'{name}: not imported so ignored')
            return d
        else:
            raise RuntimeError(f'Could not find class {name}. Has the corresponding module been imported?')
    try:
        d = Classes[name].Client(admin=admin, name=client_name)
    except ProxyDeviceError as e:
        logs.logger.info(str(e))
    return d


# dictionary for driver instances
drivers = {}

# dictionary of motor instances
motors = {}

from . import manager

# Import ui
from .ui import (init,
                 choose_investigation,
                 choose_experiment,
                 Scan)

# Import all driver submodules
from . import excillum
from . import aerotech
from . import dummy
from . import mclennan
from . import mecademic
#from . import microscope
#from . import smaract
from . import varex
#from . import pco
from . import xlam
from . import xps
