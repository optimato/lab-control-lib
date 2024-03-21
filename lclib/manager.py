"""
Management of experiment data, labeling, metadata, etc.

The structure is inspired from Elettra's storage structure
 - Investigation : highest category (e.g. speckle_long_branch)
 - Experiment : Typically an experiment run (over days, possibly in multiple parts)
 - Scan : (instead of Elettra's "dataset") a numbered (and possibly labeled) dataset

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os
from datetime import datetime
import time
import threading

from . import (get_config,
               MANAGER_ADDRESS,
               _driver_classes,
               client_or_None,
               register_driver,
               proxycall,
               proxydevice)
from .util import Future
from .base import DriverBase
from .logs import logging_muted

logtags = {'type': 'manager',
           'branch': 'both'
           }

_client = []


def getManager():
    """
    A convenience function to return the current client (or a new one) for the Manager daemon.
    """
    if _client and _client[0]:
        return _client[0]
    d = client_or_None('manager', admin=False, client_name=f'client-{get_config()["this_host"]}')
    _client.clear()
    _client.append(d)
    return d


@register_driver
@proxydevice(address=MANAGER_ADDRESS)
class Manager(DriverBase):
    """
    Management of experiment structures and metadata.
    """

    # Allowed characters for experiment and investigation names
    _VALID_CHAR = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:'
    # Interval at which attempts are made at connecting clients
    CLIENT_LOOP_INTERVAL = 20.

    DEFAULT_CONFIG = DriverBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(
                      {'experiment':None,
                       'investigation':None,
                       'meta_to_save':{}})

    def __init__(self):
        """
        Metadata manager for investigations, experiments and scans.

        An important task of the Manager driver is to request and collect metadata
        *concurrently* from all other drivers. This is accomplished by creating
        clients to each driver. These clients are instantiated (and re-instantiated)
        on a separate thread running `self.client_loop`. For each client, the
        method `fetch_meta` is started on a separate thread as soon as metadata collection
        is requested. All this is done to ensure that metadata is obtained
        as quickly as possible after it has been requested.
        """
        super().__init__()

        # Set initial parameters
        self._running = False
        self._scan_name = None
        self._label = None
        self._base_file_name = None
        self._next_scan = None

        try:
            self._scan_number = self.next_scan()
        except Exception as e:
            self.logger.warning('Could not find first available scan number (have experiment and investigation been set?)')
        self.counter = 0

        self.metacalls = {'investigation': lambda: self.investigation,
                          'experiment': lambda: self.experiment,
                          'last_scan': lambda: self._scan_number or None}

        self.requests = {}      # Dictionary to accumulate requests in case many are made before returning
        self.stop_flag = threading.Event()
        self.clients = {}

        # HACK (kind of): On the process where this class is instantiated, getManager must return this instance, not a client.
        global _client
        _client.clear()
        _client.append(self)

        # self also instead of "client to self"
        self.clients['manager'] = self

        # Start client monitoring loop
        self.clients_loop_future = Future(self.clients_loop)

    def clients_loop(self):
        """
        A loop running on a thread monitoring the health of the driver connections
        """
        while True:
            # Stop if asked
            if self.stop_flag.is_set():
                break

            # Loop through all registered driver classes
            for name in _driver_classes.keys():
                if name.lower() == self.name.lower():
                    continue
                # If client does not exist
                if name not in self.clients:
                    # Attempt client instantiation
                    with logging_muted():
                        client = client_or_None(name, admin=False, client_name='manager_loop')
                    if client:
                        # Successful client connection
                        self.logger.info(f'Client "{name}" is connected')

                        # Store client
                        self.clients[name] = client
                else:
                    try:
                        cl = self.clients[name]
                        cl.conn.ping()                        
                    except (EOFError, TimeoutError) as error:
                        # Client is dead for some reason. We clean this up and restart it
                        self.logger.warning(f'Closing client to {name} because of failed ping: {repr(error)}')
                        cl = self.clients.pop(name)
                        try:
                            cl.disconnect()
                        except:
                            pass
            # Wait a bit before retrying
            if self.stop_flag.wait(self.CLIENT_LOOP_INTERVAL):
                break
        self.logger.info('Exiting client connection loop.')

    def fetch_meta(self, name):
        """
        Method run on a short-lived thread just the time to fetch metadata.
        """
        client = self.clients.get(name)
        if client is None:
            self.logger.warning(f'Client {name} not present.')
            return None
        t0 = time.time()
        meta = client.get_meta()
        dt = time.time() - t0
        self.logger.debug(f'{name} : metadata collection completed in {dt * 1000:.3g} ms')
        return {'meta':meta, 'time': dt}

    @proxycall()
    def request_meta(self, request_ID=None, exclude_list=[]):
        """
        Request metadata from all connected clients.

        This method returns immediately. The metadata itself will be obtained when calling return_meta.

        Args:
            request_ID: a (hopefully unique) ID to tag and store the request until self.return_meta is called. It can be None.
            exclude_list: a list of clients to exclude for the metadata requests.
        Returns:
            None
        """
        # Check for duplicate
        duplicate = self.requests.get(request_ID, None)
        if duplicate is not None:
            self.logger.warning(f'Requests ID {request_ID} has not been claimed and will be overwritten.')

        # Fetch metadata on separate threads
        self.requests[request_ID] = {name:Future(self.fetch_meta, (name,)) for name in self.clients.keys() if name not in exclude_list}
        return

    @proxycall()
    def return_meta(self, request_ID=None):
        """
        Return the metadata that has been accumulated since the last call to request_meta.

        Args:
            request_ID: The ID of the request made.

        Returns:
            A dictionary with all metadata.
        """
        if request_ID not in self.requests:
            self.logger.error(f'Unknown request ID {request_ID}!')

        # Pop the request
        request = self.requests.pop(request_ID, {})
        if not request:
            self.logger.warning(f'Empty request: {request_ID}!')

        meta = {}
        times = {}
        for name, future in request.items():
            if not future.done():
                self.logger.warning(f'{name}: metadata collection not completed in time.')
            else:
                result = future.result()
                if result is not None:
                    meta[name] = result['meta']
                    times[name] = result['time']

        return meta

    @proxycall(admin=True)
    def killall(self):
        """
        Kill all servers.
        """
        self.stop_flag.set()
        while self.clients:
            name, c = self.clients.popitem()
            if name == 'manager':
                # We don't kill ourselves
                continue
            c.ask_admin(True, True)
            c.kill_server()
            time.sleep(.5)
            del c
            self.logger.info(f'{name} killed.')

    def shutdown(self):
        """
        Clean up
        """
        self.stop_flag.set()
        m =  getManager()
        if m:
            del m
        self.clients_loop_future.join()

    @proxycall()
    def start_scan(self, label=None):
        """
                Start a new scan.
        Args:
            label: an optional label to be used for directory and file naming.

        Returns:
            `scan_info` dict with scan information.
        """
        if self._running:
            raise RuntimeError(f'Scan {self.scan_name} already running')

        # Get new scan number
        self._scan_number = self.next_scan()

        # Create scan name
        today = datetime.now().strftime('%y-%m-%d')

        scan_name = f'{self._scan_number:06d}_{today}'
        if label is not None:
            scan_name += f'_{label}'

        self._scan_name = scan_name
        self._base_file_name = scan_name + '_{0:06d}'

        self._running = True
        self._label = label
        self.counter = 0

        # Create path (ok even if on control host)
        os.makedirs(os.path.join(get_config()['data_path'], self.path, scan_name), exist_ok=True)

        scan_info = {'scan_number': self._scan_number,
                'scan_name': scan_name,
                'investigation': self.investigation,
                'experiment': self.experiment,
                'path': self.path}

        return scan_info

    @proxycall()
    def end_scan(self):
        """
        Finalize the scan
        """
        if not self._running:
            raise RuntimeError(f'No scan currently running')
        self._running = False
        return {'scan_number': self._scan_number,
                'scan_name': self._scan_name,
                'investigation': self.investigation,
                'experiment': self.experiment,
                'path': self.path,
                'count': self.counter
                 }

    @proxycall()
    def status(self):
        """
        Summary of current configuration as a string
        """
        s = f' * Investigation: {self.investigation}\n'
        s += f' * Experiment: {self.experiment}\n'
        ns = self.next_scan()
        s += f' * Last scan number: {"[none]" if (ns is None or ns==0) else ns-1}'
        return s

    @proxycall()
    def next_prefix(self):
        """
        Return full prefix identifier and increment counter.
        """
        if not self._running:
            raise RuntimeError(f'No scan currently running')
        prefix = self._base_file_name.format(self.counter)
        self.counter += 1
        return prefix

    @proxycall()
    def get_counter(self):
        """
        Return current counter value (unlike next_prefix, does not increment the counter)
        """
        return self.counter

    @proxycall()
    def next_scan(self):
        """
        Return the next available scan number based on the analysis of the
        experiment path.
        """
        try:
            exp_path = os.path.join(get_config()['data_path'], self.path)
        except RuntimeError as e:
            return None
        scan_numbers = [int(f.name[:6]) for f in os.scandir(exp_path) if f.is_dir()]
        return max(scan_numbers, default=-1) + 1

    def _check_path(self):
        """
        If the current investigation / experiment values are set, check if path exists.
        """
        try:
            full_path = os.path.join(get_config()['data_path'], self.path)
            if os.path.exists(full_path):
                self.logger.info(f'Path {full_path} selected (exists).')
            else:
                os.makedirs(full_path, exist_ok=True)
                self.logger.info(f'Created path {full_path}.')
        except RuntimeError as e:
            self.logger.warning(str(e))

    def _valid_name(self, s):
        """
        Confirm that the given string can be used as part of a path
        """
        return all(c in self._VALID_CHAR for c in s)

    @proxycall()
    @property
    def scan_name(self):
        """
        Return the full scan name - none if no scan is running.
        """
        if not self._running:
            return None
        return self._scan_name

    @proxycall()
    @property
    def investigation(self):
        """
        The current investigation name.

        *** Setting the investigation makes experiment None.
        """
        return self.config.get('investigation')

    @investigation.setter
    def investigation(self, v):
        if v is None:
            raise RuntimeError(f'Investigation should not be set to "None"')
        if self._running:
            raise RuntimeError(f'Investigation cannot be modified while a scan is running.')
        if not self._valid_name(v):
            raise RuntimeError(f'Invalid investigation name: {v}')
        self.config['investigation'] = v
        self.config['experiment'] = None

    @proxycall()
    @property
    def experiment(self):
        """
        The current experiment name.
        """
        return self.config['experiment']

    @experiment.setter
    def experiment(self, v):
        if v is None:
            raise RuntimeError(f'Experiment should not be set to "None"')
        if self._running:
            raise RuntimeError(f'Experiment cannot be modified while a scan is running.')
        if self.investigation is None:
            raise RuntimeError(f'Investigation is not set.')
        if not self._valid_name(v):
            raise RuntimeError(f'Invalid experiment name: {v}')
        self.config['experiment'] = v
        self._check_path()

    @proxycall()
    @property
    def scanning(self):
        """
        True if a scan is currently running
        """
        return self._running

    @property
    def path(self):
        """
        Return experiment path
        """
        if (self.experiment is None) or (self.investigation is None):
            raise RuntimeError('Experiment or Investigation not set.')
        return os.path.join(self.investigation, self.experiment)

    @proxycall()
    @property
    def scan_path(self):
        """
        Return scan path - None if no scan is running.
        """
        if not self._running:
            return None
        return os.path.join(self.path, self.scan_name)

    @proxycall()
    @property
    def scan_number(self):
        """
        Return scan name - None if no scan is running.
        """
        if not self._running:
            return None
        return self._scan_number
