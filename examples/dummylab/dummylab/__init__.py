"""
Dummy example lab

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import lclib
from lclib.ui import ui
from lclib import util

# IPs of computer hosting some devices
host_ips = {
            'control': 'localhost',
            'other': '192.168.1.2'
            }

data_path = '/data/'

lclib.init(lab_name='DummyLab',
           host_ips=host_ips,
           data_path=data_path)

# Import all driver submodules - this registers the drivers and motors
from . import dummymotor
from . import dummydetector

from lclib import _driver_classes, drivers, motors