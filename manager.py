"""
Management of experiment data, labeling, metadata, etc.

Suggested structure similar to Elettra's
 - Investigation : highest category (e.g. speckle_long_branch)
 - Experiment : Typically an experiment run (over days, possibly in multiple parts)
 - Scan : (instead of Elettra's "dataset") a numbered (and possibly labeled) dataset
"""
import logging
import os
from datetime import datetime
import time
import threading

from . import data_path, register_proxy_client, Classes, client_or_None, THIS_HOST
from .network_conf import NETWORK_CONF, MANAGER as NET_INFO
from .util.uitools import ask, user_prompt
from .util.proxydevice import proxydevice, proxycall
from .util.future import Future
from .base import DriverBase
from .datalogger import datalogger
from .util.logs import logging_muted

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
    d = client_or_None('manager', admin=False, client_name=f'client-{THIS_HOST}')
    _client.clear()
    _client.append(d)
    return d


@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class Manager(DriverBase):
    """
    Management of experiment structures and metadata.
    """

    # Allowed characters for experiment and investigation names
    _VALID_CHAR = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:'
    # Interval at which attempts are made at connecting clients
    CLIENT_LOOP_INTERVAL = 20.

    def __init__(self):
        """
        Metadata manager for investigations, experiments and scans.
        """
        super().__init__()

        if not self.config.get('experiment'):
            self.config['experiment'] = None
        if not self.config.get('investigation'):
            self.config['investigation'] = None

        # Set initial parameters
        self._running = False
        self._scan_name = None
        self._label = None
        self._base_file_name = None

        try:
            self._scan_number = self.next_scan()
        except Exception as e:
            self.logger.warning('Could not find first available scan number (have experiment and investigation been set?)')
        self.counter = 0

        self.metacalls = {'investigation': lambda: self.investigation,
                          'experiment': lambda: self.experiment,
                          'last_scan': lambda: self.next_scan() or None}

        self.metadata = {}
        self.meta_futures = {}
        self.meta_grab_done_dct = {}
        self.meta_grab_done = False
        self.stop_flag = threading.Event()
        self.clients = {}
        self.grab_meta_flag = threading.Event()
        self.continue_flag = threading.Event()

        # HACK (kind of): On the process where this class is instantiated, getManager must return this instance, not a client.
        _client.clear()
        _client.append(self)

        # self also instead of "client to self"
        self.clients['manager'] = self
        self.meta_futures['manager'] = Future(self.meta_loop, args=('manager',))


        self.clients_loop_future = Future(self.clients_loop)

    @proxycall()
    @property
    def meta_to_save(self):
        """
        A dictionary of all metadata that will be fetched and saved in files.
        """
        return self.config['meta_to_save']

    @meta_to_save.setter
    def meta_to_save(self, dct):
        self.config['meta_to_save'] = dct

    def clients_loop(self):
        """
        A loop running on a thread monitoring the health of the driver connections
        """
        while True:
            if self.stop_flag.is_set():
                break

            # Loop through all registered driver classes
            for name in Classes.keys():
                if name not in self.clients:
                    # Attempt client instantiation
                    with logging_muted():
                        client = client_or_None(name, admin=False, client_name='manager_loop')
                    if client:
                        # Store client
                        self.logger.info(f'Client "{name}" is connected')
                        self.clients[name] = client

                        # Start the meta collection loop
                        self.meta_futures[name] = Future(self.meta_loop, args=(name,))

            # Wait a bit before retrying
            if self.stop_flag.wait(self.CLIENT_LOOP_INTERVAL):
                break
        self.logger.info('Exiting client connection loop.')

    def meta_loop(self, name):
        """
        Running on a thread, one per client. Grab metadata when a signal is received,
        and put it right into self.metadata
        """
        self.logger.info(f'Starting metadata collection loop for {name}.')
        while True:
            if not self.grab_meta_flag.wait(timeout=1.):
                # The loop will stay here until the flag is set or the client is removed from the dict
                if self.stop_flag.is_set() or name not in self.clients:
                    return
                continue

            # This is a way to exclude some clients
            if name in self.meta_grab_done_dct:
                client =  self.clients.get(name, None)
                if client:
                    t0 = time.time()
                    meta = client.get_meta()
                    dt = time.time() - t0
                    self.logger.debug(f'{name} : metadata collection completed in {dt * 1000:3.2f} ms')
                    self.metadata[name] = meta
                    self.meta_grab_done_dct[name] = dt
                    if all(self.meta_grab_done_dct.values()):
                        self.meta_grab_done = True
                        self.logger.info(f'Metadata collection completed.')

            while not self.continue_flag.wait(timeout=.5):
                # Wait here until told to continue
                if self.stop_flag.is_set():
                    return
                continue
        self.logger.info(f'Metadata collection loop for {name} ended.')

    @proxycall()
    def request_meta(self, exclude_list=[]):
        """
        Start grabbing all the metadata corresponding to the keys in self.meta_to_save.

        This method returns immediately. The metadata itself will be obtained when calling return_meta.
        """

        # Nothing to do if already requested
        if self.grab_meta_flag.is_set():
            return

        # Clear metadata dict
        # self.metadata = {}
        # Keep metadata from previous call - better than nothing
        self.metadata = {k:self.metadata.get(k) for k in self.clients.keys() }

        # A dict that gathers information about who is done grabbing the metadata
        self.meta_grab_done_dct = {name:None for name in self.clients.keys() if name not in exclude_list}

        # Make sure everyone will stop after their meta collection
        self.continue_flag.clear()

        # Flag everyone to get going
        self.grab_meta_flag.set()
        return

    @proxycall()
    def return_meta(self):
        """
        Return the metadata that has been accumulated since the last call to request_meta.
        """
        if not self.meta_grab_done:
            not_done = [name for name, v in self.meta_grab_done_dct.items() if v is None]
            self.logger.warning(f'Metadata not completed at the time it is returned ({not_done})')

        # Reset everything for next time
        self.grab_meta_flag.clear()
        self.continue_flag.set()

        return self.metadata

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
            c._proxy.kill()
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
    @datalogger.meta(field_name='scan_start', tags=logtags)
    def start_scan(self, label=None):
        """
        Start a new scan.
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
        os.makedirs(os.path.join(data_path, self.path, scan_name), exist_ok=True)

        scan_info = {'scan_number': self._scan_number,
                'scan_name': scan_name,
                'investigation': self.investigation,
                'experiment': self.experiment,
                'path': self.path}

        return scan_info

    @proxycall()
    @datalogger.meta(field_name='scan_stop', tags=logtags)
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
        Summary of current configuration.
        """
        s = f' * Investigation: {self.investigation}\n'
        s += f' * Experiment: {self.experiment}\n'
        ns = self.next_scan()
        s += f' * Last scan number: {"[none]" if ns==0 else ns-1}'
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
            exp_path = os.path.join(data_path, self.path)
        except RuntimeError as e:
            return None
        scan_numbers = [int(f.name[:6]) for f in os.scandir(exp_path) if f.is_dir()]
        return max(scan_numbers, default=-1) + 1

    def _check_path(self):
        """
        If the current investigation / experiment values are set, check if path exists.
        """
        try:
            full_path = os.path.join(data_path, self.path)
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
            RuntimeError('Experiment or Investigation not set.')
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
