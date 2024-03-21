"""
User interface (CLI)

To be imported only by the interactive controlling process.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import inspect
import os
import logging

from .. import _driver_classes, get_config, drivers, motors, client_or_None
from . import uitools
from . import ask, ask_yes_no, user_prompt
from ..logs import logger as rootlogger
from .. import manager

logger = rootlogger.getChild(__name__)

_current_detector = []
INVESTIGATIONS = None

__all__ = ['init', 'Scan', 'choose_experiment', 'choose_investigation']

def init(yes=None):
    """
    Initialize components of the setup.
    Syntax:
        init()
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        uitools.user_interactive = False

    # Experiment management
    man = manager.getManager()
    print(man.status())
    load_past_investigations()

    client_name = f'main-client-{get_config()["this_host"]}'

    # Loop through registered driver classes
    for name, cls in _driver_classes.items():
        if not ask_yes_no(f'Connect to {name}?'):
            continue

        # Instantiate client
        driver_client = client_or_None(name, admin=True, client_name=client_name)
        if driver_client:
            drivers[name] = driver_client
        else:
            logger.warning(f"Could not connect to {name}")
            continue

        # Instantiate motors if they exist
        new_motors = cls.create_motors(driver=driver_client)

        for motorname in new_motors.keys():
            logger.info(f'Created motor "{motorname}" ({name})')

        motors.update(new_motors)

    if ask_yes_no('Dump motors and drivers in global namespace?'):
        # This is a bit of black magic
        for s in inspect.stack():
            if 'init' in s[4][0]:
                s[0].f_globals.update(motors)
                s[0].f_globals.update(drivers)
                break
    if yes:
        uitools.user_interactive = None

    return


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
        man = manager.getManager()

        # New scan
        self.scan_data = man.start_scan(label=self.label)

        self.name = self.scan_data['scan_name']
        self.scan_path = self.scan_data['path']

        self.logger = logging.getLogger(self.name)
        self.logger.info(f'Starting scan {self.name}')
        self.logger.info(f'Files will be saved in {self.scan_path}')

        return self

    def __exit__(self, exception_type, exception_value, traceback):
        """
        Exit scan context

        TODO: manage exceptions
        """
        manager.getManager().end_scan()
        self.logger.info(f'Scan {self.name} complete.')


# Get data directly from file directory structure
def load_past_investigations(path=None):
    """
    Scan data_path directory structure and extract past investigations/experiments.

    """
    path = path or get_config()['data_path']

    investigations = {}

    all_inv = {f.name: f.path for f in os.scandir(path) if f.is_dir()}
    for inv, inv_path in all_inv.items():
        all_exp = {f.name: f.path for f in os.scandir(inv_path) if f.is_dir()}
        exp_dict = {}
        for exp, exp_path in all_exp.items():
            # Scan directories are of the format %05d or %05d_some_label
            all_scans = {}
            for f in os.scandir(exp_path):
                if f.is_dir():
                    try:
                        all_scans[int(f.name[:6])] = f.name
                    except ValueError:
                        print(f'{f.name} is an alien directory. Ignored.')
            exp_dict[exp] = all_scans

        # This updates the module-level dictionary
        investigations[inv] = exp_dict

    globals()['INVESTIGATIONS'] = investigations
    return investigations


def choose_investigation(name=None):
    """
    Interactive selection of investigation name.
    If non-interactive and `name` is not None: select/create
    investigation with name `name`.
    """
    # Load past investigations if needed
    if not INVESTIGATIONS:
        load_past_investigations(get_config()['data_path'])

    if name is not None:
        inv = name
    else:
        if not INVESTIGATIONS:
            inv = user_prompt('Enter new investigation name:')
            INVESTIGATIONS[inv] = {}
        else:
            invkeys = list(INVESTIGATIONS.keys())
            values = list(range(len(invkeys)+1))
            labels = ['0) [new investigation]'] + [f'{i+1}) {v}' for i, v in enumerate(invkeys)]
            ichoice = ask('Select investigation', clab=labels, cval=values, multiline=True)
            if ichoice == 0:
                inv = user_prompt('Enter new investigation name:')
                INVESTIGATIONS[inv] = {}
            else:
                inv = invkeys[ichoice-1]
    manager.getManager().investigation = inv
    return inv


def choose_experiment(name=None, inv=None):
    """
    Interactive selection of experiment name.
    If non-interactive and `name` is not None: select/create
    experiment with name `name`.
    """
    # Load past investigations if needed
    if not INVESTIGATIONS:
        load_past_investigations(get_config()['data_path'])

    # Use global investigation name if none was provided
    if inv is None:
        inv = manager.getManager().investigation

    # This will break if inv is not a key of investigations
    # So be it. Create one first.
    experiments = INVESTIGATIONS[inv]

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
                exp = expkeys[ichoice - 1]
    exp_path = os.path.join(os.path.join(get_config()['data_path'], inv), exp)
    print(f'Experiment: {exp} at {exp_path}')
    os.makedirs(exp_path, exist_ok=True)
    manager.getManager().experiment = exp
    return exp
