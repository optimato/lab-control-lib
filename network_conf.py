"""
Hard coded network values
"""

# IPs of computer hosting some devices
HOST_IPS = {
            'control': '172.19.248.36',
            'varex': '172.19.248.35',
            'pco': '?.?.?.?',
            'lambda': '172.19.248.39',
            'xps': '172.19.248.37'
            }
cIP = HOST_IPS['control']
vIP = HOST_IPS['varex']
pIP = HOST_IPS['pco']
lIP = HOST_IPS['lambda']
xIP = HOST_IPS['xps']

NETWORK_CONF = {
    'excillum':  {'control': (cIP, 5000),         'device': ('10.19.48.3', 4944),  'logging': (cIP, 7000),         'stream': (cIP, 5500)},
    'mecademic': {'control': (cIP, 5010),         'device': ('10.19.48.5', 10000), 'logging': (cIP, 7010),         'stream': (cIP, 5510)},
    'mecademic_monitor': {'control': (cIP, 5015), 'device': ('10.19.48.5', 10001), 'logging': (cIP, 7015)},
    'xps1':      {'control': (cIP, 5020),         'device': (xIP, 5001),           'logging': (cIP, 7020),         'stream': (cIP, 5520)},  # change the IP to a private one later
    'xps2':      {'control': (cIP, 5021),         'device': (xIP, 5001),           'logging': (cIP, 7021),         'stream': (cIP, 5521)},  # change the IP to a private one later
    'xps3':      {'control': (cIP, 5022),         'device': (xIP, 5001),           'logging': (cIP, 7022),         'stream': (cIP, 5522)},  # change the IP to a private one later
    'smaract':   {'control': (cIP, 5030),         'device': ('10.19.48.?', 5000),  'logging': (cIP, 7030),         'stream': (cIP, 5530)},
    'aerotech':  {'control': (cIP, 5040),         'device': ('10.19.48.?', 8000),  'logging': (cIP, 7040),         'stream': (cIP, 5540)},
    'mclennan1': {'control': (cIP, 5050),         'device': ('10.19.48.?', 7776),  'logging': (cIP, 7050),         'stream': (cIP, 5550)},
    'mclennan2': {'control': (cIP, 5051),         'device': ('10.19.48.?', 7777),  'logging': (cIP, 7051),         'stream': (cIP, 5551)},
    'mclennan3': {'control': (cIP, 5052),         'device': ('10.19.48.?', 7778),  'logging': (cIP, 7052),         'stream': (cIP, 5552)},
    'dummy':     {'control': ('127.0.0.1', 5060), 'device': ('127.0.0.1', 6789),   'logging': ('127.0.0.1', 7060), 'stream': (cIP, 5560)},
    'varex':     {'control': (vIP, 5070),         'device': None,                  'logging': (vIP, 7070),         'stream': (vIP, 5570), 'broadcast_port': 8070},
    'pco':       {'control': (pIP, 5080),         'device': None,                  'logging': (pIP, 7080),         'stream': (pIP, 5580), 'broadcast_port': 8080},
    'xspectrum': {'control': (lIP, 5090),         'device': None,                  'logging': (lIP, 7090),         'stream': (lIP, 5590), 'broadcast_port': 8090},
    'datalogger': {'control': (cIP, 8086)},
    'manager':  {'control': (cIP, 5100),          'device': None,                  'logging': (cIP, 7100),         'stream': (cIP, 5600)}
}

# For convenience
EXCILLUM = NETWORK_CONF['excillum']
MECADEMIC = NETWORK_CONF['mecademic']
MECADEMIC_MONITOR = NETWORK_CONF['mecademic_monitor']
XPS1 = NETWORK_CONF['xps1']
XPS2 = NETWORK_CONF['xps2']
XPS3 = NETWORK_CONF['xps3']
SMARACT = NETWORK_CONF['smaract']
AEROTECH = NETWORK_CONF['aerotech']
MCLENNAN1 = NETWORK_CONF['mclennan1']
MCLENNAN2 = NETWORK_CONF['mclennan2']
MCLENNAN3 = NETWORK_CONF['mclennan3']
DUMMY = NETWORK_CONF['dummy']
VAREX = NETWORK_CONF['varex']
PCO = NETWORK_CONF['pco']
XSPECTRUM = NETWORK_CONF['xspectrum']
DATALOGGER = NETWORK_CONF['datalogger']
MANAGER = NETWORK_CONF['manager']

"""
################################
# Device IPs/hostnames + ports #
################################

# Aerotech rotation stage
AEROTECH = {'DAEMON': (HOST_IPS['control'], 15000),
            'DEVICE': (DEVICE_IPS['aerotech'], 8000)
            }

SMARACT = {'DAEMON': (HOST_IPS['control'], 15001),
           'DEVICE': (DEVICE_IPS['smaract'], 5000)
           }

# McLennan controller for bottom stages
MCLENNAN1 = {'DAEMON': (HOST_IPS['control'], 15003),
             'DEVICE': (DEVICE_IPS['mclennan1'], 7776)
             }

MCLENNAN2 = {'DAEMON': (HOST_IPS['control'], 15004),
             'DEVICE': (DEVICE_IPS['mclennan2'], 7777)
             }

MECA_ADDRESS = "172.19.234.28"
MECADEMIC = {'DAEMON': (HOST_IPS['control'], 15005),
             #'DEVICE': ("172.19.248.34", 10000)
             'DEVICE': (MECA_ADDRESS, 10000),
             'MONITOR': (MECA_ADDRESS, 10001)
             }

EXCILLUM = {'DAEMON': (HOST_IPS['control'], 15100),
            'DEVICE': ('10.19.48.3', 4944)
            }

XPS = {'DAEMON': (HOST_IPS['control'], 15006),
       'DEVICE': ("?.?.?.?", 5001)
       }

VAREX = {'DAEMON': (HOST_IPS['varex'], 15200),
         'BROADCAST': ('0.0.0.0', 5555)}

DUMMY = {'DAEMON': (HOST_IPS['control'], 16789),
         'DEVICE': (HOST_IPS['control'], 6789)
         }
"""