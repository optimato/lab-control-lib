"""
Dummy driver definitions

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

# lclib decorators
from lclib import register_driver, proxycall, proxydevice

# lclib drivers
from lclib.drivers import dummydetector, dummymotor

# lab-specific parameters
from . import data_path, host_ips


#### Dummy detector
@register_driver
@proxydevice(address=(host_ips['control'], 5060))
class Dummydetector(dummydetector.Dummydetector):
    DEFAULT_BROADCAST_ADDRESS = (host_ips['control'], 9500)  # address to broadcast images for viewers
    BASE_PATH = data_path  # All data is saved in subfolders of this one

#### Dummy motor
@register_driver
@proxydevice(address=(host_ips['control'], 5050))
class Dummymotor(dummymotor.Dummymotor):
    pass

