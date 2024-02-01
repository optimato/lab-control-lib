"""
Hard coded network values

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

# IPs of computer hosting some devices
HOST_IPS = {
            'control': '172.19.248.40',
            'varex': '172.19.248.35',
            'pco': '172.19.248.18',
            'lambda': '172.19.248.39',
            'xps': '10.19.48.4'
            }
cIP = HOST_IPS['control']
vIP = HOST_IPS['varex']
pIP = HOST_IPS['pco']
lIP = HOST_IPS['lambda']
xIP = HOST_IPS['xps']

# note fabio: I temporarily changed the connection to the mecademic robot to a direct connection.
# In this connection, the control computer has the IP 192.168.1.1, and the robot has 192.168.1.2.
NETWORK_CONF = {
    'excillum':  {'control': (cIP, 5000),         'device': ('10.19.48.3', 4944),   'logging': (cIP, 7000),         'stream': (cIP, 5500)},
    'mecademic': {'control': (cIP, 5010),         'device': ('192.168.1.2', 10000), 'logging': (cIP, 7010),         'stream': (cIP, 5510)},  # 'device': ('10.19.48.5', 10000),
    'mecademic_monitor': {'control': (cIP, 5015), 'device': ('192.168.1.2', 10001), 'logging': (cIP, 7015)},                                 # 'device': ('10.19.48.5', 10001),
    'xps1':      {'control': (cIP, 5020),         'device': (xIP, 5001),           'logging': (cIP, 7020),         'stream': (cIP, 5520)},  # change the IP to a private one later
    'xps2':      {'control': (cIP, 5021),         'device': (xIP, 5001),           'logging': (cIP, 7021),         'stream': (cIP, 5521)},  # change the IP to a private one later
    'xps3':      {'control': (cIP, 5022),         'device': (xIP, 5001),           'logging': (cIP, 7022),         'stream': (cIP, 5522)},  # change the IP to a private one later
    'smaract':   {'control': (cIP, 5030),         'device': ('10.19.48.8', 5000),  'logging': (cIP, 7030),         'stream': (cIP, 5530)},
    'aerotech':  {'control': (cIP, 5040),         'device': ('10.19.48.7', 8000),  'logging': (cIP, 7040),         'stream': (cIP, 5540)},
    'mclennan1': {'control': (cIP, 5050),         'device': ('10.19.48.11', 7776), 'logging': (cIP, 7050),         'stream': (cIP, 5550)},
    'mclennan2': {'control': (cIP, 5051),         'device': ('10.19.48.12', 7776), 'logging': (cIP, 7051),         'stream': (cIP, 5551)},
    'mclennan3': {'control': (cIP, 5052),         'device': ('10.19.48.13', 7776), 'logging': (cIP, 7052),         'stream': (cIP, 5552)},
    'dummy':     {'control': ('127.0.0.1', 5060), 'device': ('127.0.0.1', 6789),   'logging': ('127.0.0.1', 7060), 'stream': (cIP, 5560)},
    'varex':     {'control': (vIP, 5070),         'device': None,                  'logging': (vIP, 7070),         'stream': (vIP, 5570), 'broadcast_port': 8070},
    'pco':       {'control': (pIP, 5080),         'device': None,                  'logging': (pIP, 7080),         'stream': (pIP, 5580), 'broadcast_port': 8080},
    'xlam':      {'control': (lIP, 5090),         'device': None,                  'logging': (lIP, 7090),         'stream': (lIP, 5590), 'broadcast_port': 8090},
    'datalogger': {'control': (cIP, 8086)},
    'manager':   {'control': (cIP, 5100),          'device': None,                  'logging': (cIP, 7100),         'stream': (cIP, 5600)}
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
XLAM = NETWORK_CONF['xlam']
DATALOGGER = NETWORK_CONF['datalogger']
MANAGER = NETWORK_CONF['manager']