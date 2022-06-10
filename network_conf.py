"""
Hard coded network values
"""
import socket
import logging

THIS_HOST = None
try:
    THIS_HOST = socket.gethostbyname(socket.gethostname() + '.local')
except socket.gaierror:
    logging.getLogger().warning('Could not find local IP')

# Controller IPs/hostnames
CONTROL_HOST = '127.0.0.1'
CAMSERVER_HOST = '?.?.?.?'

################################
# Device IPs/hostnames + ports #
################################

# Aerotech rotation stage
AEROTECH = {'DAEMON': (CONTROL_HOST, 15000),
            'DEVICE': ("?.?.?.?", 8000)
            }

SMARACT = {'DAEMON': (CONTROL_HOST, 15001),
           'DEVICE': ("?.?.?.?", 5000)
           }

# McLennan controller for bottom stages
MCLENNAN1 = {'DAEMON': (CONTROL_HOST, 15100),
             'DEVICE': ("?.?.?.?", 7776)
             }

MCLENNAN2 = {'DAEMON': (CONTROL_HOST, 15101),
             'DEVICE': ("?.?.?.?", 7777)
             }

MECADEMIC = {'DAEMON': (CONTROL_HOST, 15200),
             #'DEVICE': ("172.19.248.34", 10000)
             'DEVICE': ("mecademic.elettra.eu", 10000)
             }