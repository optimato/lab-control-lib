"""
Aggregator for metadata.
"""
import logging
import threading
import time

from . import motors
from .manager import instantiate_driver, DRIVER_DATA
from .base import DaemonException
logger = logging.getLogger()

# Dictionary of running drivers
DRIVERS = {}


def connect(name=None):
    """
    Instantiate one or multiple drivers.
    If name is None, instatiate all available.
    """

    if name is None:
        for name in DRIVER_DATA.keys():
            connect(name)
        return

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
        DRIVERS[name] = driver

    return


def get_all_meta(block=False):
    """
    Collect all available metadata.

    If block is True: wait for all thread to return.
    """
    if not DRIVERS:
        logger.warning('No metadata can be collected: No running driver.')
        return {}

    meta = {k: {} for k in DRIVERS.keys()}
    meta.update({motor_name: {} for motor_name in motors.keys()})

    meta['meta'] = {'collection_start': time.time()}

    # Use threads to optimize I/O
    workers = []
    for k in DRIVERS.keys():
        t = threading.Thread(target=DRIVERS[k].get_meta, args=(None, meta[k]))
        t.start()
        workers.append(t)

    for motor_name, motor in motors.items():
        t = threading.Thread(target=motor.get_meta, args=(meta[motor_name],))
        t.start()
        workers.append(t)

    # Thread watcher will add key "collection_end" once done. This is a way
    # evaluate overall colletion time, and whether collection is finished.
    def watch_threads(wlist, d):
        for w in wlist:
            w.join()
        d['meta']['collection_end'] = time.time()

    watcher = threading.Thread(target=watch_threads, args=(workers, meta))
    watcher.start()
    if block:
        watcher.join()

    return meta
