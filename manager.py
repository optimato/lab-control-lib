"""
Manage driver and daemon creation.
"""

import logging
import subprocess
import time
import sys

from .ui_utils import ask_yes_no
from .util.proxydevice import ProxyClientError
from . import network_conf
from . import mecademic
from . import smaract
from . import mclennan
from . import aerotech
from . import excillum
from . import dummy

DRIVER_DATA  = {'mecademic': {'driver': mecademic.Mecademic},
                'smaract': {'driver': smaract.Smaract},
                'aerotech': {'driver': aerotech.Aerotech},
                'mclennan1': {'driver': mclennan.McLennan,
                              'client_kwargs': {'kwargs': {'device_address': network_conf.MCLENNAN1['device']},
                                                'name': 'mclennan1'},
                              'name': 'mclennan1'},
                'mclennan2': {'driver': mclennan.McLennan,
                              'client_kwargs': {'kwargs': {'device_address': network_conf.MCLENNAN2['device']},
                                                'name': 'mclennan2'},
                              'name': 'mclennan2'},
                'excillum': {'driver': excillum.Excillum},
                'dummy': {'driver': dummy.Dummy}
              # 'xps': {},
              # 'pco': {},
              # 'varex': {},
              # 'xspectrum': {},
                }

logger = logging.getLogger("manager")


def instantiate_driver(driver, client_kwargs=None, name=None, admin=True, spawn=True):
    """
    Helper function to instantiate a driver and
    spawning the corresponding daemon if necessary and requested.
    """
    name = name or driver.__name__.lower()
    client_kwargs = client_kwargs or {}

    # Try to instantiate a driver client
    d = None
    try:
        d = driver.Client(admin=admin, **client_kwargs)
    except ProxyClientError:
        if not spawn:
            logger.warning(f'The proxy server for driver {name} is unreachable')
            return None

        # Didn't connect. Let's try to spawn the server.
        if ask_yes_no(f'Server proxy for {name} unreachable. Spawn it?'):
            p = subprocess.Popen([sys.executable, '-m', 'labcontrol.startup', 'start', f'{name}'],
                                 start_new_session=True,)
                               # stdout=subprocess.DEVNULL,
                               # stderr=subprocess.STDOUT)
            logger.info(f'Proxy server process for driver {name} has been spawned.')
            # Make sure the server is already listening before connecting
            time.sleep(20)
            d = driver.Client(admin=admin, **client_kwargs)
        else:
            logger.error(f'Driver {driver.name} is not running.')
    return d

