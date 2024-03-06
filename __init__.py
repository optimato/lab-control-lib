"""
Optimato Lab control package

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import lclib

# IPs of computer hosting some devices
host_ips = {
            'control': '172.19.248.40',
            'varex': '172.19.248.35',
            'pco': '172.19.248.18',
            'lambda': '172.19.248.39',
            'xps': '10.19.48.4'
            }

# network configuration - just because it is convenient to keep it in one place.
network_conf = {
                'excillum':  {'control': ('control', 5000),         'device': ('10.19.48.3', 4944)},
                'mecademic': {'control': ('control', 5010),         'device': ('192.168.1.2', 10000)},
                'mecademic_monitor': {'control': ('control', 5015), 'device': ('192.168.1.2', 10001)},
                'xps1':      {'control': ('control', 5020),         'device': ('xps', 5001)},
                'xps2':      {'control': ('control', 5021),         'device': ('xps', 5001)},
                'xps3':      {'control': ('control', 5022),         'device': ('xps', 5001)},
                'smaract':   {'control': ('control', 5030),         'device': ('10.19.48.8', 5000)},
                'aerotech':  {'control': ('control', 5040),         'device': ('10.19.48.7', 8000)},
                'mclennan1': {'control': ('control', 5050),         'device': ('10.19.48.11', 7776)},
                'mclennan2': {'control': ('control', 5051),         'device': ('10.19.48.12', 7776)},
                'mclennan3': {'control': ('control', 5052),         'device': ('10.19.48.13', 7776)},
                'dummy':     {'control': ('127.0.0.1', 5060),       'device': ('127.0.0.1', 6789)},
                'varex':     {'control': ('varex', 5070),           'broadcast_port': 8070},
                'pco':       {'control': ('pco', 5080),             'broadcast_port': 8080},
                'microscope':{'control': ('pco', 5085),             'device': None},
                'xlam':      {'control': ('lambda', 5090),          'broadcast_port': 8090},
                'datalogger': {'control': ('control', 8086),        'device': None},
                'manager':   {'control': ('control', 5100),         'device': None}
                }

data_path = '/data3/lab/'

lclib.init(lab_name='OptImaTo',
           host_ips=host_ips,
           data_path=data_path)

# Import all driver submodules - this registers the drivers and motors
from . import excillum
from . import aerotech
from . import dummy
from . import mclennan
from . import mecademic
#from . import microscope
#from . import smaract
from . import varex
from . import pco
from . import xlam
from . import xps
