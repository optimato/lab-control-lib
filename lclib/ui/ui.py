"""
User interface (CLI)

To be imported only by the interactive controlling process.

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import inspect
import os
import logging

from .. import drivers, motors, DATA_PATH, client_or_None, THIS_HOST
from . import uitools
from . import ask, ask_yes_no, user_prompt
from ..logs import logger as rootlogger
from .. import manager

logger = rootlogger.getChild(__name__)

_current_detector = []
INVESTIGATIONS = None

__all__ = ['init', 'Scan', 'choose_experiment', 'choose_investigation', 'set_current_detector']

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

    # Excillum
    if ask_yes_no("Connect to Excillum?"):
        driver = client_or_None('excillum', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['excillum'] = driver

    # Smaract
    if ask_yes_no('Connect to smaracts?',
                  help="SmarAct are the 3-axis piezo translation stages for high-resolution sample movement"):
        driver = client_or_None('smaract', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['smaract'] = driver
            from . import smaract
            motors['sx'] = smaract.Motor('sx', driver, axis=0)
            motors['sy'] = smaract.Motor('sy', driver, axis=2)
            motors['sz'] = smaract.Motor('sz', driver, axis=1)

    # Coarse stages
    if ask_yes_no('Connect to short branch coarse stages?'):
        # McLennan 1 (sample coarse x translation)
        driver = client_or_None('mclennan1', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['mclennan1'] = driver
            from . import mclennan
            motors['ssx'] = mclennan.Motor('ssx', driver)

        # McLennan 2 (short branch detector coarse x translation)
        driver = client_or_None('mclennan2', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['mclennan2'] = driver
            from . import mclennan
            motors['dsx'] = mclennan.Motor('dsx', driver)

    if ask_yes_no('Connect to long branch coarse stages?'):
        # McLennan 3 (long branch detector coarse x translation)
        driver = client_or_None('mclennan3', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['mclennan3'] = driver
            from . import mclennan
            motors['dsx'] = mclennan.Motor('dsx', driver)

    if ask_yes_no('Connect to Varex detector?'):
        driver =  client_or_None('varex', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['varex'] = driver

    if ask_yes_no('Connect to Lambda detector?'):
        driver = client_or_None('xlam', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['xlam'] = driver

    if ask_yes_no('Connect to PCO detector?'):
        driver = client_or_None('pco', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['pco'] = driver

    if ask_yes_no('Connect to Aerotech rotation stage?'):
        driver =  client_or_None('aerotech', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['aerotech'] = driver
            from . import aerotech
            motors['rot'] = aerotech.Motor('rot', driver)

    if ask_yes_no('Connect to Newport XPS motors?'):
        driver =  client_or_None('xps1', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['xps1'] = driver
            from . import xps
            motors['xps1'] = xps.Motor('xps1', driver)

        driver =  client_or_None('xps2', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['xps2'] = driver
            from . import xps
            motors['xps2'] = xps.Motor('xps2', driver)

        driver =  client_or_None('xps3', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['xps3'] = driver
            from . import xps
            motors['xps3'] = xps.Motor('xps3', driver)

    if ask_yes_no('Connect to mecademic robot?'):
        driver =  client_or_None('mecademic', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['mecademic'] = driver
            from . import mecademic
            motors.update(mecademic.create_motors(driver))

    #if ask_yes_no('Initialise stage pseudomotors?'):
    #    print('TODO')
        # motors['sxl'] = labframe.Motor(
        #    'sxl', motors['sx'], motors['sz'], motors['rot'], axis=0)
        # motors['szl'] = labframe.Motor(
        #    'szl', motors['sx'], motors['sz'], motors['rot'], axis=1)

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

def set_current_detector(name):
    """
    Useful to automate arm/disarm
    """
    if name.lower() not in ['varex', 'xlam', 'pco']:
        print(f'"{name}" is not a known detector name.')
    _current_detector[0] = name

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


def init_dummy(yes=None):
    """
    Initialize the dummy component for testing
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        uitools.user_interactive = False

    if ask_yes_no("Start dummy driver?"):
        driver =  client_or_None('dummy', client_name=f'main-client-{THIS_HOST}')
        if driver:
            drivers['dummy'] = driver


# Get data directly from file directory structure
def load_past_investigations(path=None):
    """
    Scan data_path directory structure and extract past investigations/experiments.

    """
    path = path or DATA_PATH

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
        load_past_investigations(DATA_PATH)

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
        load_past_investigations(DATA_PATH)

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
    exp_path = os.path.join(os.path.join(DATA_PATH, inv), exp)
    print(f'Experiment: {exp} at {exp_path}')
    os.makedirs(exp_path, exist_ok=True)
    manager.getManager().experiment = exp
    return exp
