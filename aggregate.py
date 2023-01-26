"""
Aggregator for metadata.
"""
import time

from . import motors
from .util import now
from .util.logs import logger as rootlogger
from .util.logs import logging_muted
from .util.future import Future
from .base import DaemonException

logger = rootlogger.getChild(__name__)

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
        with logging_muted():
            driver = instantiate_driver(name=name, admin=False)
    except DaemonException:
        logger.error(f'Driver {name} could not start.')
        driver = None
    if driver is not None:
        DRIVERS[name] = driver

    return


def meta_fetch_task(fct, dct):
    t0 = time.time()
    try:
        result = fct()
    except:
        result = {'failed': 'failed'}
    dct.update(result)
    dct['fetch_time'] = time.time()-t0
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

    workers = {}
    for k in DRIVERS.keys():
        f = Future(target=meta_fetch_task, args=(DRIVERS[k].get_meta, meta[k]))
        workers[k + ' [driver]'] = f

    for motor_name, motor in motors.items():
        f = Future(target=meta_fetch_task, args=(motor.get_meta, meta['motors'][motor_name]))
        workers[motor_name + ' [motor]'] = f

    logger.debug('Done creating workers.')

    # Thread watcher will add key "collection_end" once done. This is a way
    # to evaluate overall collection time, and whether collection is finished.
    def watch_futures(workers, d, t0):
        max_dt = 0.
        slowest = ''
        for k, w in workers.items():
            tt0 = time.time()
            w.join()
            dtt = time.time()-tt0
            if dtt > max_dt:
                max_dt = dtt
                slowest = k
        logger.info(f'Slowest fetch was "{slowest}" ({max_dt:0.3f} seconds)')
        d['meta']['collection_end'] = now()
        dt = time.time() - t0
        logger.info(f'Metadata collection completed in {dt*1000:3.2f} ms')

    logger.debug('Starting watcher.')

    watcher = Future(target=watch_futures, args=(workers, meta, t0))
    if block:
        logger.debug('Waiting for watcher.')
        watcher.result()
        logger.debug('Watcher done.')

    logger.debug('Aggregation complete.')

    return meta
