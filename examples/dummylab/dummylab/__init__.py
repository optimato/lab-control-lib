"""
Dummy example lab

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os
import lclib
from lclib import ui
from lclib import util

# IPs of computer hosting some devices
host_ips = {
            'control': 'localhost',
            'other': '192.168.1.2'
            }

# This can be the location of a mounted file server
data_path = os.path.expanduser('~/dummylab-data/')
os.makedirs(data_path, exist_ok=True)

# Hack: add 'localhost' as valid ip
lclib.local_ip_list.append('localhost')

config = {}

# For testing purposes, we define two instruments
def load_instrument_1():
    c = lclib.init(instrument_ID='DummyLab1',
               host_ips=host_ips,
               data_path=data_path,
               manager_address=('localhost', lclib.DEFAULT_MANAGER_PORT))
    config.update(c)

def load_instrument_2():
    c = lclib.init(instrument_ID='DummyLab2',
               host_ips=host_ips,
               data_path=data_path,
               manager_address = ('localhost', lclib.DEFAULT_MANAGER_PORT+1))
    config.update(c)

# Import all driver submodules - this registers the drivers and motors
from . import dummymotor
from . import dummydetector

from lclib import manager, drivers, motors