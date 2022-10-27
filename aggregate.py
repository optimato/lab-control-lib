"""
Aggregator for metadata.
"""
import logging
import time

from . import motors
from .util import now
from .util.future import Future
from .manager import instantiate_driver, DRIVER_DATA
from .base import DaemonException
logger = logging.getLogger(__name__)

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


def meta_fetch_task(fct, dct):
    result = fct()
    dct.update(result)
    return None


def get_all_meta(block=False):
    """
    Collect all available metadata.

    If block is True: wait for all thread to return.
    """
    if not DRIVERS:
        logger.warning('No metadata can be collected: No running driver.')
        return {}

    t0 = time.time()
    meta = {'meta': {'collection_start': now()}}

    meta['motors'] = {motor_name: {} for motor_name in motors.keys()}
    meta.update({k: {} for k in DRIVERS.keys()})
    meta.update({motor_name: {} for motor_name in motors.keys()})

    # Use threads to optimize I/O
    workers = []
    for k in DRIVERS.keys():
        f = Future(target=meta_fetch_task, args=(DRIVERS[k].get_meta, meta[k]))
        workers.append(f)

    for motor_name, motor in motors.items():
        f = Future(target=meta_fetch_task, args=(motor.get_meta, meta['motors'][motor_name]))
        workers.append(f)

    # Thread watcher will add key "collection_end" once done. This is a way
    # to evaluate overall collection time, and whether collection is finished.
    def watch_futures(workers, d):
        for w in workers:
            w.join()
        d['meta']['collection_end'] = now()
        dt = time.time() - t0
        logger.info(f'Metadata collection completed in {dt*1000:3.2f} ms')

    watcher = Future(target=watch_futures, args=(workers, meta))
    if block:
        watcher.result()

    return meta
