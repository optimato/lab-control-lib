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
from .ui_utils import ask, user_prompt
from .aggregate import get_all_meta

# INVESTIGATION and EXPERIMENT will be populated by user prompts or other ways
# SCAN will be None unless a scan is ongoing, in which case it will be
# equal to the current Scan context manager (see below).
# The current idea is to scan for next available scan always based on directory
# structure to reduce to risk of overwriting existing data. It could be done
# differently.

INVESTIGATION = None
EXPERIMENT = None
SCAN = None

# List of existing investigations (and experiments, ...)
investigations = {}


def startup():
    """
    Interactive startup script to prepare experiment variables.
    """
    pass


def choose_investigation(name=None):
    """
    Interactive selection of investigation name.
    If non-interactive and `name` is not None: select/create
    investigation with name `name`.
    """
    # Load past investigations if needed
    if not investigations:
        load_past_investigations(data_path)

    if name is not None:
        inv = name
    else:
        if not investigations:
            inv = user_prompt('Enter new investigation name:')
        else:
            invkeys = list(investigations.keys())
            values = list(range(len(invkeys)+1))
            labels = ['0) [new investigation]'] + [f'{i+1}) {v}' for i, v in enumerate(invkeys)]
            ichoice = ask('Select investigation', clab=labels, cval=values, multiline=True)
            if ichoice == 0:
                inv = user_prompt('Enter new investigation name:')
            else:
                inv = invkeys[ichoice-1]
    inv_path = os.path.join(data_path, inv)
    print(f'Investigation: {inv} at {inv_path}')
    os.makedirs(inv_path, exist_ok=True)
    globals()['INVESTIGATION'] = inv
    return inv


def choose_experiment(inv=None, name=None):
    """
    Interactive selection of experiment name.
    If non-interactive and `name` is not None: select/create
    experiment with name `name`.
    """
    # Load past investigations if needed
    if not investigations:
        load_past_investigations(data_path)

    # Use global investigation name if none was provided
    if inv is None:
        inv = INVESTIGATION

    # This will break if inv is not a key of investigations
    # So be it. Create one first.
    experiments = investigations[inv]

    # Now select or create new experiment
    if name is not None:
        exp = name
    else:
        if not experiments:
            exp = user_prompt('Enter new experiment name:')
        else:
            expkeys = list(experiments.keys())
            values = list(range(len(expkeys) + 1))
            labels = ['0) [new experiment]'] + [f'{i+1}) {v}' for i, v in enumerate(expkeys)]
            ichoice = ask('Select experiment:', clab=labels, cval=values, multiline=True)
            if ichoice == 0:
                exp = user_prompt('Enter new experiment name:')
            else:
                exp = expkeys[ichoice]
    exp_path = os.path.join(os.path.join(data_path, inv), exp)
    print(f'Experiment: {exp} at {exp_path}')
    os.makedirs(exp_path, exist_ok=True)
    globals()['EXPERIMENT'] = exp
    return exp


def investigation_path(base_path=None):
    """
    Current investigation path
    """
    if INVESTIGATION is None:
        RuntimeError('No investigation has been selected or created.')
    base_path = base_path or data_path
    return os.path.join(base_path, INVESTIGATION)


def experiment_path(base_path=None):
    """
    Current experiment path
    """
    if EXPERIMENT is None:
        RuntimeError('No experiment has been selected or created.')
    inv_path = investigation_path(base_path)
    return os.path.join(inv_path, EXPERIMENT)


def next_scan(exp_path=None):
    """
    Return the next available scan number based on the analysis of the
    experiment path.
    """
    if exp_path is None:
        exp_path = experiment_path()
    scan_numbers = [int(f.name[:6]) for f in os.scandir(exp_path) if f.is_dir()]
    return max(scan_numbers, default=-1) + 1


# Get data directly from file directory structure
def load_past_investigations(path):
    """
    Scan data_path directory structure and extract past investigations/experiments.

    This might get heavy, we'll adjust if it does.
    """
    all_inv = {f.name: f.path for f in os.scandir(path) if f.is_dir()}
    for inv, inv_path in all_inv.items():
        all_exp = {f.name: f.path for f in os.scandir(inv_path) if f.is_dir()}
        exp_dict = {}
        for exp, exp_path in all_exp.items():
            # Scan directories are of the format %05d or %05d_some_label
            all_scans = {int(f.name[:6]): f.name for f in os.scandir(exp_path) if f.is_dir()}
            exp_dict[exp] = all_scans

        # This updates the module-level dictionary
        investigations[inv] = exp_dict

    return investigations


class Scan:
    """
    Scan context manager
    """

    def __init__(self, label=None):
        self.label = label
        self.logger = None

    def __enter__(self):
        """
        Prepare for scan
        """
        # Get current experiment path
        self.path = experiment_path()

        # Get new scan number
        self.scan_number = next_scan(self.path)

        # Create scan name
        today = datetime.now().strftime('%y-%m-%d')

        scan_name = f'{self.scan_number:06d}_{today}'
        if self.label is not None:
            scan_name += f'_{self.label}'

        self.scan_name = scan_name

        # Create scan directory
        self.scan_path = os.path.join(self.path, scan_name)
        os.makedirs(self.scan_path)

        # Reset counter
        self._base_file_name = '{0:06d}'
        self.counter = 0

        # Set SCAN module attribute
        globals()['SCAN'] = self

        self.logger = logging.getLogger(scan_name)
        self.logger.info(f'Starting scan {scan_name}')
        self.logger.info(f'Files will be saved in {self.scan_path}')

        # This is a non-blocking call.
        self.meta = get_all_meta()

    def __exit__(self, exception_type, exception_value, traceback):
        """
        Exit scan context

        TODO: manage exceptions
        """
        globals()['SCAN'] = None

        self.logger.info(f'Scan {self.scan_name} complete.')

    def next_prefix(self):
        prefix = self._base_file_name.format(self.counter)
        self.counter += 1
        return prefix