"""
Dummy example lab

To test fully:

* Install lab-control-lib:
  ``cd [path to lab-control-lib]``
  ``pip install .``

* If not already done, install the daemon service scripts:
  ``cd scripts``
  ``chmod +x *.sh``
  ``sudo ./linux_install_daemon.sh``
  (similar for Windows)

* Install dummylab:
  ``cd [path to lab-control-lib]/examples/dummylab``
  ``pip install .``

* On a separate terminal, open a python process and instantiate the fake motor controller:

::
    import dummylab
    d = dummylab.dummymotor.DummyControllerInterface()
    # Will start listening for a connection

* Start all the drivers:

  ``python -m lclib dummylab start monitor``
  ``python -m lclib dummylab start manager``
  ``python -m lclib dummylab start dummymotor``
  ``python -m lclib dummylab start dummydetector``

* Finally, start an interactive python session (or jupyter notebook), and initialize everything:

::
    import dummylab
    dummylab.ui.init()

From this point on, the clients are connected to the drivers, and motion and acquisitions commands can be sent.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os
import lclib
from lclib import register_driver, proxydevice
from lclib.monitor import MonitorBase
from lclib.manager import ManagerBase

# IPs of computer hosting some devices
host_ips = {
            'control': 'localhost',
            'other': '192.168.1.2'
            }

# Hack: add 'localhost' as valid ip
lclib.local_ip_list.append('localhost')

lclib.init(lab_name='DummyLab',
           host_ips=host_ips,
           monitor_address=(host_ips['control'], 5001))

# Create and register Monitor
@register_driver
@proxydevice(address=(host_ips['control'], 5001))
class Monitor(MonitorBase):
    pass

# Create and register Manager
data_path = os.path.expanduser('~/dummylab-data/')
os.makedirs(data_path, exist_ok=True)
@register_driver
@proxydevice(address=(host_ips['control'], 5002))
class Manager(ManagerBase):
    DEFAULT_DATA_PATH = data_path

# Import all driver submodules - this registers the drivers and motors
from . import dummymotor
from . import dummydetector

# Declutter namespace
del MonitorBase, ManagerBase

# Populate namespace with useful objects and sub-packages
from lclib import ui, util, drivers, motors