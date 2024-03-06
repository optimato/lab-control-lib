"""
Lab control library

Terminology
-----------
"Device": an instrument with which it is necessary to communicate for motion, detection, etc.
"Driver": a python object that can be instantiated to manage a device.
"Socket Driver": a driver that communicates with a device through a socket connection.
"Proxy Server": an object that manages one driver and accepts connections from proxy clients to control this driver.
"Proxy Client": a client that connects to a Proxy Server. It is a "proxy" because it reproduces the driver interface
                through method calls.

General principles
------------------
The design of this software is made to address these limitations:
- Most devices allow only one connection at a time. It is often useful to access a device through multiple clients,
  for instance to probe for metadata or specific signals.
- Keeping logs of a device status requires a process that runs constantly and that keep alive a connection with that device.
- A crash in a control software should not interrupt connections to all devices or require a complete reinitialization.
- Running all drivers in a single process might overload the computer resources
- Some devices must run on their own machine (Windows), so at the very least these devices need to be "remote controlled".

The solution is a distributed device management. Each device is managed by a driver that runs on a unique process, and is
wrapped by a proxy server. Control and data access is done through one or more proxy clients to the proxy server. Since
all communication is through TCP sockets, drivers can run on different computers, as long as they are on the same network.
An "admin" status is conferred only to one client at a time to ensure that no two processes attempt at controlling a device
simultaneously (all "read-only" methods are however allowed by non-admin clients).

In practice, each driver is implemented as if it is meant to be the single instance connected to the device. The base class
`DriverBase` takes care of few things (logging, configuration, metadata collection, periodic calls), while `SocketDriverBase`
has all what is needed to connect to devices that have socket connections.
The module `proxydevice` provides server/client classes as well as decorators that transform drivers into a
server/client pair. Any method of the driver can be "exposed" as remotely accessible with the method decorator
`@proxycall`. See the module doc for more info.

Additional classes
------------------
Currently, apart from the X-ray source, devices fall in just two main categories: motion devices, and detectors. There
is therefore a high-level class `Motor` meant to provide access to the underlying device through a common interface
(with methods inspired from the `spec` language). For detectors, the common interface is `CameraBase`, which is a
subclass of DriverBase. The hope is to make instances of `Motor` and `CameraBase` subclasses sufficient for everyday
use.

Library structure
-----------------
This library was split off of

The init() method has to called early to inform the library of the most important parameters for its functioning, namely
 * the name of the lab (for identification and access to configuration files)
 * the name and IP address of the relevant computers on the LAN, to identify the platform where the package is being runned
 * the network addresses and ports of all proxy servers and devices. In principle this information could be managed
   outside the library, but command line operations (see __main__.py) 
This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import os
import platform
import json
import subprocess

# Base attribute definitions have to be done before relative imports

Classes = {}   # Dictionary for driver classes (populated when drivers module load)
drivers = {}   # dictionary for driver instances
motors = {}  # dictionary of motor instances

DEFAULT_MANAGER_PORT = 5001

# Global variables set by init()
LABORATORY = None
LOCAL_HOSTNAME = None
LOCAL_IP_LIST = []
THIS_HOST = None
HOST_IPS = None
DATA_PATH = None
MANAGER_ADDRESS = None
CONF_PATH = None
config = None
LOG_DIR = None

from . import ui
from .proxydevice import ProxyDeviceError, proxydevice, proxycall
from .util import FileDict
from . import logs
from ._version import version

def init(lab_name,
         host_ips=None,
         data_path=None,
         manager_address=None):
    """
    Set up lab parameters.

    Args:
        lab_name: (str) The name of the laboratory
        host_ips: (dict) Dict of host names and IPs in  the laboratory LAN {hostname1: ip1, hostname2: ip2, ...}
        data_path: Main path to save data (from control node)
        manager_address: the address for the manager.
    """
    global LABORATORY, LOCAL_HOSTNAME, LOCAL_IP_LIST, THIS_HOST, HOST_IPS, DATA_PATH, CONF_PATH, config, LOG_DIR, MANAGER_ADDRESS

    #
    # Lab name
    #

    assert type(lab_name) is str, f'"lab_name" is not a string!'
    LABORATORY = lab_name

    #
    # Persistent configuration file
    #
    CONF_PATH = os.path.expanduser(f"~/.{LABORATORY.lower()}-labcontrol/")
    os.makedirs(CONF_PATH, exist_ok=True)
    conf_file = os.path.join(CONF_PATH, 'config.json')
    config = FileDict(conf_file)

    #
    # Host IP dictionary
    #
    if host_ips is None:
        HOST_IPS = config['host_ips']
    else:
        HOST_IPS = host_ips
        config['host_ips'] = host_ips

    assert 'control' in HOST_IPS, 'Mandatory "control" entry missing in "host_ips"!'

    #
    # Data path
    #
    if data_path is None:
        DATA_PATH = config['data_path']
    else:
        DATA_PATH = 'data_path'
        config['data_path'] = data_path

    #
    # Manager address
    #
    if manager_address is None:
        # Get manager address from config file, or revert to default
        MANAGER_ADDRESS = config.get('manager_address', (HOST_IPS['control'], DEFAULT_MANAGER_PORT))
    else:
        MANAGER_ADDRESS = manager_address
    config['manager_address'] = MANAGER_ADDRESS

    #
    # Identify this computer by matching IP with HOST_IPS
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

    #
    # SETUP LOGGING
    #
    LOG_DIR = os.path.join(CONF_PATH, 'logs/')
    os.makedirs(LOG_DIR, exist_ok=True)

    # Log to file interactive sessions
    if ui.is_interactive():
        log_file_name = os.path.join(LOG_DIR, f'{LABORATORY.lower()}-labcontrol.log')
        logs.log_to_file(log_file_name)
        print('*{0:^64}*'.format('[Logging to file on this host]'))
    else:
        print('*{0:^64}*'.format('[Not logging to file on this host]'))

    print()

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

from . import base
from . import camera
