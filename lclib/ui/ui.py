"""
User interface (CLI)

To be imported only by the interactive controlling process.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import inspect
import os
import logging

from .. import _driver_classes, get_config, drivers, motors, client_or_None, local_hostname, FileDict
from . import uitools
from ..util import FileDict
from . import ask, ask_yes_no, user_prompt
from ..logs import logger as rootlogger
from .. import manager

# Set up logger
logger = rootlogger.getChild(__name__)

# Set up config
config_filename = os.path.join(get_config()['conf_path'], 'ui.json')
config = FileDict(config_filename)

# Dictionary populated by init() at runtime, and possibly other future functions that set some defaults
_runtime = {'manager': None}

INVESTIGATIONS = None

__all__ = ['init', 'Scan', 'choose_experiment', 'choose_investigation']

def init(yes=None, manager_name='manager'):
    """
    Initialize components of the setup.
    Syntax:
        init()
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        uitools.user_interactive = False

    client_name = f'main-client-{get_config()["this_host"]}'

    # List of registered drivers - minus the Manager(s)
    registered_drivers = [name for name, cls in _driver_classes.items() if not (issubclass(cls, manager.ManagerBase) or name == 'monitor')]

    # First check that monitor is running
    monitor_client = client_or_None('monitor', client_name=client_name)
    if monitor_client is None:
        raise RuntimeError('Could not connect to monitor! Is it running?')
    drivers['monitor'] = monitor_client

    # Experiment management
    man = client_or_None(manager_name, keep_trying=False, admin=True)
    if man is None:
        raise RuntimeError(f'Could not connect to manager {manager_name}.')
    drivers[manager_name] = man

    # Keep track of current manager
    _runtime['manager_name'] = manager_name
    _runtime['manager'] = man

    # Print out some information
    print(" * Investigation: {investigation}\n * Experiment: {experiment}\n * Last Scan: {last_scan}".format(**man.status()))

    # Loop through registered driver classes
    for name in registered_drivers:
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
        new_motors = _driver_classes[name].create_motors(driver=driver_client)

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
        man = _runtime['manager']
        if man is None:
            raise RuntimeError('The experiment manager is not present. Did you run "init"?')

        # Collect as much information as possible on the calling context
        import __main__
        try:
            script_name = __main__.__file__
            calling_path = os.getcwd()
            script_name = os.path.join(calling_path, script_name)
            script_content = open(script_name).read()
        except AttributeError:
            if uitools.is_interactive():
                script_name = '<interactive>'
            else:
                import sys
                script_name = sys.argv[0]
            script_content = ''
        localmeta = {'script_name': script_name,
                      'calling_host': local_hostname,
                      'script_content': script_content}
        # New scan
        self.scan_data = man.start_scan(label=self.label, localmeta=localmeta)

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
        _runtime['manager'].end_scan()
        self.logger.info(f'Scan {self.name} complete.')

def choose_investigation(name=None):
    """
    Interactive selection of investigation name.
    If non-interactive and `name` is not None: select/create
    investigation with name `name`.
    """
    # Get experiment manager
    man = _runtime['manager']
    if man is None:
        raise RuntimeError('The experiment manager is not present. Did you run "init"?')

    invkeys = man.list_inv()

    if name is None:
        if not invkeys:
            name = user_prompt('Enter new investigation name:')
        else:
            values = list(range(len(invkeys)+1))
            labels = ['0) [new investigation]'] + [f'{i+1}) {v}' for i, v in enumerate(invkeys)]
            ichoice = ask('Select investigation', clab=labels, cval=values, multiline=True)
            if ichoice == 0:
                name = user_prompt('Enter new investigation name:')
            else:
                name = invkeys[ichoice-1]
    _runtime['manager'].investigation = name
    return name

def choose_experiment(name=None, inv=None):
    """
    Interactive selection of experiment name.
    If non-interactive and `name` is not None: select/create
    experiment with name `name`.
    """
    # Get experiment manager
    man = _runtime['manager']
    if man is None:
        raise RuntimeError('The experiment manager is not present. Did you run "init"?')

    expkeys = man.list_exp(inv=inv)

    # Now select or create new experiment
    if name is None:
        if not expkeys:
            name = user_prompt('Enter new experiment name:')
        else:
            values = list(range(len(expkeys) + 1))
            labels = ['0) [new experiment]'] + [f'{i+1}) {v}' for i, v in enumerate(expkeys)]
            ichoice = ask('Select experiment:', clab=labels, cval=values, multiline=True)
            if ichoice == 0:
                name = user_prompt('Enter new experiment name:')
            else:
                name = expkeys[ichoice - 1]
    man.experiment = name
    return name
