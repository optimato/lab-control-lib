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

from . import data_path
from .network_conf import EXPERIMENT as NET_INFO
from .util.uitools import ask, user_prompt
from .util.proxydevice import proxydevice, proxycall
from .base import DriverBase
from .aggregate import get_all_meta
from .datalogger import datalogger

logtags = {'type': 'workflow',
           'branch': 'both'
           }

experiment = None


def connect():
    global experiment
    if experiment is not None:
        return
    from .manager import instantiate_driver
    d = instantiate_driver(name='experiment', admin=False)
    globals()['experiment'] = d


class Scan:
    """
    Scan context manager
    """

    def __init__(self, label=None):
        self.label = label
        self.logger = None
        connect()

    def __enter__(self):
        """
        Prepare for scan
        """
        # New scan
        self.scan_data = experiment.start_scan(label=self.label)

        self.name = self.scan_data['scan_name']
        self.scan_path = self.scan_data['scan_path']

        self.logger = logging.getLogger(self.name)
        self.logger.info(f'Starting scan {self.name}')
        self.logger.info(f'Files will be saved in {self.scan_path}')

        # This is a non-blocking call.
        self.meta = get_all_meta()

    def __exit__(self, exception_type, exception_value, traceback):
        """
        Exit scan context

        TODO: manage exceptions
        """
        experiment.end_scan()
        self.logger.info(f'Scan {self.name} complete.')


@proxydevice(address=NET_INFO['control'])
class Experiment(DriverBase):
    """
    Experiment management.
    """
    _VALID_CHAR = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:'

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

        return {'scan_number': self._scan_number,
                'scan_name': scan_name,
                'investigation': self.investigation,
                'experiment': self.experiment,
                'path': self.path}

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
        if self.experiment is None or self.investigation is None:
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
