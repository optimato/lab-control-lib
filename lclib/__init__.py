"""
Lab control library

Terminology
-----------
"Device": an instrument with which it is necessary to communicate for motion, detection, etc.
"Driver": a python object that can be instantiated to manage a device.
"Socket Driver": a driver that communicates with a device through a socket connection.
"Proxy Server": an object that manages one driver and accepts connections from proxy clients to control this driver.
"Proxy Client": a client that connects to a Proxy Server. It is a "proxy" because it reproduces the driver interface through method calls.

General principles
------------------
The design of this software is made to address these limitations:
- Most devices allow only one connection at a time. It is often useful to access a device through multiple clients, for instance to probe for metadata or specific signals.
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

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)

"""

import os
import platform
import json
import subprocess
import inspect

from .proxydevice import ProxyDeviceError, proxydevice, proxycall
from .util import FileDict
from . import logs
from .logs import logger
from ._version import version

# Base attribute definitions have to be done before relative imports

_driver_classes = {}   # Dictionary for driver classes (populated through @register_driver when drivers module load)
_motor_classes = {}   # Dictionary for motor classes (populated when drivers module load)
drivers = {}   # Dictionary for driver instances
motors = {}    # Dictionary of motor instances

DEFAULT_MONITOR_PORT = 5001
DEFAULT_LOG_LEVEL = 20 # logging.INFO

# Global variables set by init()
config = {}

# Get computer name and IP addresses
uname = platform.uname()
local_hostname = uname.node
local_platform = uname.system
if local_platform == "Linux":
    iface_info = json.loads(subprocess.run(['ip', '-j', '-4', 'addr'], capture_output=True).stdout.decode())
    local_ip_list = [iface['addr_info'][0]['local'] for iface in iface_info]
elif local_platform == "Windows":
    s = subprocess.run(['ipconfig', '/allcompartments'], capture_output=True).stdout.decode()
    local_ip_list = [x.split(' ')[-1] for x in s.split('\r\n') if x.strip().startswith('IPv4')]
elif local_platform == "Darwin":
    ip = str(subprocess.check_output(["ifconfig | grep inet"], shell=True)[:-2], 'UTF-8')
    local_ip_list = [x.split(' ')[1] for x in ip.split('\t') if x.split(' ')[0] == 'inet']
else:
    raise RuntimeError(f'Unknown system platform {local_platform}')

# Remove localhost (not there under windows)
try:
    local_ip_list.remove('127.0.0.1')
except ValueError:
    pass

def get_config():
    return config

def client_or_None(name, admin=True, client_name=None, inexistent_ok=True, keep_trying=False):
    """
    Helper function to create a client to a named driver

    Args:
        name (str): driver name
        admin (bool): try to connect as admin [default True]
        client_name: an identifier for the client
        inexistent_ok: if True, ignore unknown names.
        keep_trying: if True, the client object is returned even if the connection was not successful

    Returns:
        An instance of the proxy client connected to named driver, or None if connection failed.
    """

    d = None
    if name not in _driver_classes:
        if inexistent_ok:
            logs.logger.info(f'{name}: not imported so ignored')
            return d
        else:
            raise RuntimeError(f'Could not find class {name}. Has the corresponding module been imported?')
    try:
        if keep_trying:
            d = _driver_classes[name].Client(admin=admin, name=client_name, reconnect='always')
        else:
            d = _driver_classes[name].Client(admin=admin, name=client_name)
    except ProxyDeviceError as e:
        logs.logger.info(str(e))
    return d

def register_driver(cls):
    """
    A simple decorator to store all drivers in a dictionary.
    """
    # Check that the registered address is unique
    registered_addresses = [d.Server.ADDRESS for d in _driver_classes.values()]
    if cls.Server.ADDRESS in registered_addresses:
        raise RuntimeError(f'{cls.Server.ADDRESS} is already registered')

    # Store class into dict
    driver_name = cls.__name__.lower()
    _driver_classes[driver_name] = cls
    logger.debug(f"Driver '{driver_name}' is now registered.")
    return cls

def caller_module():
    """
    Utility to find the name of the package importing this.
    """
    caller_frame = inspect.stack()
    parent_module = None
    for f in caller_frame:
        calling_module = inspect.getmodule(f[0])
        if calling_module is not None:
            parent_module = calling_module.__name__
            if parent_module == __name__:
                continue
            break
    return parent_module


def init(lab_name,
         host_ips=None,
         data_path=None,
         monitor_address=None):
    """
    Set up lab parameters.

    Args:
        lab_name: (str) The name of the laboratory
        host_ips: (dict) Dict of host names and IPs in  the laboratory LAN {hostname1: ip1, hostname2: ip2, ...}
        data_path: Main path to save data (from control node)
        manager_address: the address for the manager.
    """
    global config
    BANNER = '*{0:^120}*'

    #
    # Lab name
    #

    assert type(lab_name) is str, f'"lab_name" is not a string!'

    parent_module = caller_module()

    #
    # Persistent configuration file
    #
    conf_path = os.path.expanduser(f"~/.{lab_name.lower()}-lclib/")
    os.makedirs(conf_path, exist_ok=True)
    conf_file = os.path.join(conf_path, 'config.json')
    config = FileDict(conf_file)

    # Bootstrap lab name
    config.setdefault('lab_name', lab_name)

    # Bootstrap default log level
    config.setdefault('log_level', DEFAULT_LOG_LEVEL)
    logger.setLevel(config['log_level'])

    # Set other parameters
    config['conf_path'] = conf_path
    config['module'] = parent_module

    print(BANNER.format(f'This is {lab_name} (module "{parent_module}")'))

    # Store local info extracted already at import
    config['local_hostname'] = local_hostname
    config['local_ip_list'] = local_ip_list

    logger.debug('Basic config completed')

    #
    # Setup logging on file for interactive sessions
    #
    log_dir = os.path.join(conf_path, 'logs/')
    os.makedirs(log_dir, exist_ok=True)

    # Store for access e.g. by __main__
    logs.log_dir = log_dir

    # Log to file interactive sessions
    if ui.is_interactive():
        log_file_name = os.path.join(log_dir, f'{lab_name.lower()}-lclib.log')
        logs.log_to_file(log_file_name)
        print(BANNER.format('[Logging to file on this host]'))
    else:
        print(BANNER.format('[Not logging to file on this host]'))
    print(BANNER.format(""))

    logger.debug('Logging config completed')

    #
    # Host IP dictionary
    #
    if host_ips is None:
        host_ips = config['host_ips']
    else:
        config['host_ips'] = host_ips

    assert 'control' in host_ips, 'Mandatory "control" entry missing in "host_ips"!'

    #
    # Data path
    #
    if data_path is None:
        data_path = config['data_path']
    else:
        config['data_path'] = data_path

    #
    # Monitor address
    #
    if monitor_address is None:
        # Get manager address from config file, or revert to default
        monitor_address = config.get('monitor_address', (host_ips['control'], DEFAULT_MONITOR_PORT))

    # Register Hub
    @register_driver
    @proxydevice(address=monitor_address)
    class Monitor(monitor.MonitorBase):
        pass

    config['hub_address'] = monitor_address

    #
    # Identify this computer by matching IP with HOST_IPS
    #
    try:
        this_host = [name for name, ip in host_ips.items() if ip in local_ip_list][0]
    except IndexError:
        print(BANNER.format('[Host IP not part of the control network.]'))
        this_host = 'unknown'

    config['this_host'] = this_host

    print('\n'.join([BANNER.format(f"{lab_name} Lab Control"),
                     BANNER.format(f"Running on host '{local_hostname}'"),
                     BANNER.format(f"a.k.a. '{this_host}' with IP {local_ip_list}")
                     ])
          )

from . import monitor
from . import manager
from . import base
from . import camera
from . import ui