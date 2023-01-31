"""
User interface (CLI)

To be imported only by the interactive controlling process.
"""

import inspect
import os

from . import drivers, motors, data_path, client_or_None
from .util import uitools
from .util.uitools import ask, ask_yes_no, user_prompt
from .util.logs import logger as rootlogger
from . import manager

logger = rootlogger.getChild(__name__)

INVESTIGATIONS = None


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
        if driver:=client_or_None('excillum'):
            drivers['excillum'] = driver

    # Smaract
    if ask_yes_no('Initialise smaracts?',
                  help="SmarAct are the 3-axis piezo translation stages for high-resolution sample movement"):
        if driver:=client_or_None('smaract'):
            drivers['smaract'] = driver
            from . import smaract
            motors['sx'] = smaract.Motor('sx', driver, axis=0)
            motors['sy'] = smaract.Motor('sy', driver, axis=2)
            motors['sz'] = smaract.Motor('sz', driver, axis=1)

    # Coarse stages
    if ask_yes_no('Initialise short branch coarse stages?'):
        # McLennan 1 (sample coarse x translation)
        if driver:=client_or_None('mclennan1'):
            drivers['mclennan1'] = driver
            from . import mclennan
            motors['ssx'] = mclennan.Motor('ssx', driver)

        # McLennan 2 (short branch detector coarse x translation)
        if driver:=client_or_None('mclennan2'):
            drivers['mclennan2'] = driver
            from . import mclennan
            motors['dsx'] = mclennan.Motor('dsx', driver)

        # McLennan 3 (long branch detector coarse x translation)
        if driver:=client_or_None('mclennan3'):
            drivers['mclennan3'] = driver
            from . import mclennan
            motors['dsx'] = mclennan.Motor('dsx', driver)

    if ask_yes_no('Initialise Varex detector?'):
        if driver := client_or_None('varex'):
            drivers['varex'] = driver

    #if ask_yes_no('Initialise PCO camera?'):
    #    pass

    #if ask_yes_no('Initialise Andor camera?'):
    #    pass

    #if ask_yes_no('Initialise microscope?'):
    #    pass

    if ask_yes_no('Initialise rotation stage?'):
        if driver := client_or_None('aerotech'):
            drivers['aerotech'] = driver
            from . import aerotech
            motors['rot'] = aerotech.Motor('rot', driver)

    if ask_yes_no('Initialise Newport XPS motors?'):
        if driver := client_or_None('xps1'):
            drivers['xps1'] = driver
            from . import xps
            motors['xps1'] = xps.Motor('xps1', driver)

        if driver := client_or_None('xps2'):
            drivers['xps2'] = driver
            from . import xps
            motors['xps2'] = xps.Motor('xps2', driver)

        if driver := client_or_None('xps3'):
            drivers['xps3'] = driver
            from . import xps
            motors['xps3'] = xps.Motor('xps3', driver)

    if ask_yes_no('Initialize mecademic robot?'):
        if driver := client_or_None('mecademic'):
            drivers['mecademic'] = driver
            from . import mecademic
            motors.update(mecademic.create_motors(driver))

    #if ask_yes_no('Initialise stage pseudomotors?'):
    #    print('TODO')
        # motors['sxl'] = labframe.Motor(
        #    'sxl', motors['sx'], motors['sz'], motors['rot'], axis=0)
        # motors['szl'] = labframe.Motor(
        #    'szl', motors['sx'], motors['sz'], motors['rot'], axis=1)

    if ask_yes_no('Initialise XPS motors?'):
        driver1 = instantiate_driver(name='xps1')
        driver2 = instantiate_driver(name='xps2')
        driver3 = instantiate_driver(name='xps3')
        drivers['xps1'] = driver1
        drivers['xps2'] = driver2
        drivers['xps3'] = driver3
        if driver1 or driver2 or driver3:
            from . import xps
        if driver1:
            motors['xps1'] = xps.Motor('xps1', driver1)  # remove "axis" parameter, get it from driver parameter
        if driver2:
            motors['xps2'] = xps.Motor('xps2', driver2)
        if driver3:
            motors['xps3'] = xps.Motor('xps3', driver3)


    if ask_yes_no('Dump motors and drivers in global namespace?'):
        # This is a bit of black magic
        for s in inspect.stack():
            if 'init' in s[4][0]:
                s[0].f_globals.update(motors)
                s[0].f_globals.update(drivers)
                break
    if yes:
        uitools.user_interactive = True

    return


def init_dummy(yes=None):
    """
    Initialize the dummy component for testing
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        uitools.user_interactive = False

    if ask_yes_no("Start dummy driver?"):
        if driver := client_or_None('dummy'):
            drivers['dummy'] = driver


# Get data directly from file directory structure
def load_past_investigations(path=None):
    """
    Scan data_path directory structure and extract past investigations/experiments.

    """
    path = path or data_path

    investigations = {}

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
        load_past_investigations(data_path)

    if name is not None:
        inv = name
    else:
        if not INVESTIGATIONS:
            inv = user_prompt('Enter new investigation name:')
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


def choose_experiment(inv=None, name=None):
    """
    Interactive selection of experiment name.
    If non-interactive and `name` is not None: select/create
    experiment with name `name`.
    """
    # Load past investigations if needed
    if not INVESTIGATIONS:
        load_past_investigations(data_path)

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
    exp_path = os.path.join(os.path.join(data_path, inv), exp)
    print(f'Experiment: {exp} at {exp_path}')
    os.makedirs(exp_path, exist_ok=True)
    manager.getManager().experiment = exp
    return exp
