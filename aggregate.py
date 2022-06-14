"""
Aggregator for metadata.
"""
import logging
import threading

from .manager import instantiate_driver, DRIVER_DATA
from .base import DaemonException
logger = logging.getLogger()

# Dictionary of running drivers
DRIVERS = {}


def connect(name=None):
    """
    Instantiate one or multiple drivers.
    """
    if name is None:
        for name in DRIVER_DATA.keys():
            return connect(name)

    # Check if a running driver exists already
    if name in DRIVERS:
        if DRIVERS['name'].isalive:
            logger.info(f'Driver {name} already running and healthy.')
            return
        else:
            logger.info(f'Stale driver {name} will be replaced.')

    # Instantiate the driver
    try:
        driver = instantiate_driver(**DRIVER_DATA[name], admin=False, spawn=False)
    except DaemonException:
        logger.error(f'Driver {name} could not start.')
        driver = None
    if driver is not None:
        DRIVERS['name'] = driver

    return


def get_all_meta():
    """
    Collect all available metadata.

    TODO: also motors
    """
    if not DRIVERS:
        logger.warning('No metadata can be collected: No running driver.')
        return {}

    meta = {k: {} for k in DRIVERS.keys()}
    workers = []
    for k, d in meta.items():
        t = threading.Thread(target=DRIVERS[k].get_meta, args=(None, d))
        t.start()
        workers.append(t)

    for w in workers:
        w.join(10.)

    return meta