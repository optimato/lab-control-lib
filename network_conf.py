"""
Hard coded network values
"""

# IPs of computer hosting some devices
HOST_IPS = {
            'control': '172.19.248.36',
            'varex': '172.19.248.35',
            'pco': '?.?.?.?',
            'lambda': '172.19.248.39'
            }

NETWORK_CONF = {
    'excillum': {'control': (HOST_IPS['control'], 5000), 'device': ('10.19.48.3', 4944), 'logging': (HOST_IPS['control'], 7000)},
    'mecademic': {'control': (HOST_IPS['control'], 5010), 'device': ('172.19.248.34', 10000), 'logging': (HOST_IPS['control'], 7010)},
    'mecademic_monitor': {'control': (HOST_IPS['control'], 5015), 'device': ('172.19.248.34', 10001), 'logging': (HOST_IPS['control'], 7015)},
    'xps': {'control': (HOST_IPS['control'], 5020), 'device': ('10.19.48.?', 5001), 'logging': (HOST_IPS['control'], 7020)},
    'smaract': {'control': (HOST_IPS['control'], 5030), 'device': ('10.19.48.?', 5000), 'logging': (HOST_IPS['control'], 7030)},
    'aerotech': {'control': (HOST_IPS['control'], 5040), 'device': ('10.19.48.?', 8000), 'logging': (HOST_IPS['control'], 7040)},
    'mclennan1': {'control': (HOST_IPS['control'], 5050), 'device': ('10.19.48.?', 7776),  'logging': (HOST_IPS['control'], 7050)},
    'mclennan2': {'control': (HOST_IPS['control'], 5051), 'device': ('10.19.48.?', 7777), 'logging': (HOST_IPS['control'], 7051)},
    'mclennan3': {'control': (HOST_IPS['control'], 5052), 'device': ('10.19.48.?', 7778), 'logging': (HOST_IPS['control'], 7052)},
    'dummy':  {'control': ('127.0.0.1', 5060), 'device': ('127.0.0.1', 6789),  'logging': ('127.0.0.1', 7060)},
    'varex': {'control': (HOST_IPS['varex'], 5070), 'device': None,  'logging': (HOST_IPS['varex'], 7070), 'broadcast_port': 8070},
    'pco': {'control': (HOST_IPS['pco'], 5080), 'device': None, 'logging': (HOST_IPS['pco'], 7080), 'broadcast_port': 8080},
    'xspectrum': {'control': (HOST_IPS['lambda'], 5090), 'device': None, 'logging': (HOST_IPS['lambda'], 7090), 'broadcast_port': 8090},
    'datalogger': {'control': (HOST_IPS['control'], 8086)},
    'experiment': {'control': (HOST_IPS['control'], 9001)}
}

# For convenience
EXCILLUM = NETWORK_CONF['excillum']
MECADEMIC = NETWORK_CONF['mecademic']
MECADEMIC_MONITOR = NETWORK_CONF['mecademic_monitor']
XPS = NETWORK_CONF['xps']
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
EXPERIMENT = NETWORK_CONF['experiment']

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