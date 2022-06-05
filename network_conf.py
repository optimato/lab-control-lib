"""
Hard coded network values
"""

# Controller IPs/hostnames
CONTROL_HOST = '?.?.?.?'
CAMSERVER_HOST = '?.?.?.?'

################################
# Device IPs/hostnames + ports #
################################

# Aerotech rotation stage
AEROTECH = {'DAEMON': (CONTROL_HOST, 15000),
            'DEVICE': ("?.?.?.?", 8000)
            }

# McLennan controller for bottom stages
MCLENNAN1 = {'DAEMON': (CONTROL_HOST, 15100),
             'DEVICE': ("?.?.?.?", 7776)
             }

MCLENNAN2 = {'DAEMON': (CONTROL_HOST, 15101),
             'DEVICE': ("?.?.?.?", 7777)
             }

MECADEMIC = {'DAEMON': (CONTROL_HOST, 15200),
             'DEVICE': ("?.?.?.?", 10000)
             }
