"""
Aggregator for metadata.
"""
import logging
import time

from . import motors
from .util import now
from .util.future import Future
from .base import DaemonException
logger = logging.getLogger(__name__)

# Dictionary of running drivers
DRIVERS = {}


def connect(name=None):
    """
    Instantiate one or multiple drivers.
    If name is None, instantiate all available.
    """
    from .manager import instantiate_driver, DRIVER_DATA

    if name is None:
        futures = []
        for name in DRIVER_DATA.keys():
            futures.append(Future(connect, args=(name,)))
        for f in futures:
            f.join()
        return

    # Check if a running driver exists already
    if name in DRIVERS:
        if DRIVERS[name]._proxy.running:
            logger.info(f'Driver {name} already running and healthy.')
            return
        else:
            logger.info(f'Stale driver {name} will be replaced.')

    # Instantiate the driver
    try:
        driver = instantiate_driver(name=name, admin=False)
    except DaemonException:
        logger.error(f'Driver {name} could not start.')
        driver = None
    if driver is not None:
        DRIVERS[name] = driver

    return


def meta_fetch_task(fct, dct):
    try:
        result = fct()
    except:
        result = 'failed'
    dct.update(result)
    return None


def get_all_meta(block=False):
    """
    Collect all available metadata.

    If block is True: wait for all thread to return.
    """

    logger.debug('Aggregation started.')

    if not DRIVERS:
        connect()

    if not DRIVERS:
        logger.warning('No metadata can be collected: No running driver.')
        return {}

    t0 = time.time()
    meta = {'meta': {'collection_start': now()}}

    meta['motors'] = {motor_name: {} for motor_name in motors.keys()}
    meta.update({k: {} for k in DRIVERS.keys()})
    meta.update({motor_name: {} for motor_name in motors.keys()})

    # Use threads to optimize I/O

    logger.debug('Creating workers.')

    workers = []
    for k in DRIVERS.keys():
        f = Future(target=meta_fetch_task, args=(DRIVERS[k].get_meta, meta[k]))
        workers.append(f)

    for motor_name, motor in motors.items():
        f = Future(target=meta_fetch_task, args=(motor.get_meta, meta['motors'][motor_name]))
        workers.append(f)

    logger.debug('Done creating workers.')

    # Thread watcher will add key "collection_end" once done. This is a way
    # to evaluate overall collection time, and whether collection is finished.
    def watch_futures(workers, d):
        for w in workers:
            w.join()
        d['meta']['collection_end'] = now()
        dt = time.time() - t0
        logger.info(f'Metadata collection completed in {dt*1000:3.2f} ms')

    logger.debug('Starting watcher.')

    watcher = Future(target=watch_futures, args=(workers, meta))
    if block:
        logger.debug('Waiting for watcher.')
        watcher.result()
        logger.debug('Watcher done.')

    logger.debug('Aggregation complete.')

    return meta
