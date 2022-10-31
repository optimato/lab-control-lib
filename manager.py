"""
Manage driver and daemon creation.
"""

import logging
import subprocess
import time
import sys

import logging
import sys
import inspect
import click

from . import ui_utils
from . import THIS_HOST, LOCAL_HOSTNAME
from .network_conf import NETWORK_CONF, HOST_IPS
from .ui_utils import ask_yes_no
from .util.proxydevice import ProxyClientError
from . import drivers, motors, cameras
from . import aerotech
from . import mclennan
from . import mecademic
from . import dummy
#from . import microscope
from . import smaract
from . import excillum
from . import varex

DRIVER_DATA  = {'mecademic': {'driver': mecademic.Mecademic},
                'smaract': {'driver': smaract.Smaract},
                'aerotech': {'driver': aerotech.Aerotech},
                'mclennan1': {'driver': mclennan.McLennan,
                              'client_kwargs': {'kwargs': {'device_address': NETWORK_CONF['mclennan1']['device']},
                                                'name': 'mclennan1',
                                                'address': NETWORK_CONF['mclennan1']['control']},
                              'name': 'mclennan1'},
                'mclennan2': {'driver': mclennan.McLennan,
                              'client_kwargs': {'kwargs': {'device_address': NETWORK_CONF['mclennan2']['device']},
                                                'name': 'mclennan2',
                                                'address': NETWORK_CONF['mclennan2']['control']},
                              'name': 'mclennan2'},
                'excillum': {'driver': excillum.Excillum},
                'dummy': {'driver': dummy.Dummy},
                'varex': {'driver': varex.Varex},
              # 'xps': {},
              # 'pco': {},
              # 'xspectrum': {},
                }

logger = logging.getLogger("manager")


def instantiate_driver(driver, client_kwargs=None, name=None, admin=True, spawn=True):
    """
    Helper function to instantiate a driver and
    spawning the corresponding daemon if necessary and requested.
    """
    name = name or driver.__name__.lower()
    client_kwargs = client_kwargs or {}

    # Try to instantiate a driver client
    d = None
    try:
        d = driver.Client(admin=admin, **client_kwargs)
    except ProxyClientError:
        if not spawn:
            logger.warning(f'The proxy server for driver {name} is unreachable')
            return None

        # Didn't connect. Let's try to spawn the server.
        if ask_yes_no(f'Server proxy for {name} unreachable. Spawn it?'):

            # TODO: use paramiko.SSHClient for drivers that need to start on another host
            # On windows, the command will be something like:
            # "Invoke-WmiMethod -Path 'Win32_Process' -Name Create -ArgumentList 'python -m labcontrol.startup startup varex'"

            p = subprocess.Popen([sys.executable, '-m', 'labcontrol.startup', 'start', f'{name}'],
                                 start_new_session=True)
            logger.info(f'Proxy server process for driver {name} has been spawned.')

            # TODO: wait a little but not too much
            time.sleep(5)
            d = driver.Client(admin=admin, **client_kwargs)
        else:
            logger.error(f'Driver {driver.name} is not running.')
    return d


def boot():
    """
    Initial, machine-dependent startup.
    """
    # Instantiate all servers
    for driver_name, net_info in NETWORK_CONF.items():
        if (HOST_IPS['control'] in net_info[THIS_HOST][0]):
            # Instantiate device control is on this computer. Instantiate.
            kwargs = {}
            kwargs.update(DRIVER_DATA[driver_name])
            kwargs['admin'] = False
            d = instantiate_driver(**kwargs)


def init_all(yes=None):
    """
    Initialize components of the setup.
    Syntax:
        init_all()
    is interactive

    TODO: Take care of starting deamons remotely if needed.
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        ui_utils.user_interactive = False

    # Excillum
    if ask_yes_no("Connect to Excillum?"):
        driver = instantiate_driver(**DRIVER_DATA['excillum'])
        drivers['excillum'] = driver

    # Smaract
    if ask_yes_no('Initialise smaracts?',
                  help="SmarAct are the 3-axis piezo translation stages for high-resolution sample movement"):
        driver = instantiate_driver(**DRIVER_DATA['smaract'])
        drivers['smaract'] = driver
        if driver is not None:
            motors['sx'] = smaract.Motor('sx', driver, axis=0)
            motors['sy'] = smaract.Motor('sy', driver, axis=2)
            motors['sz'] = smaract.Motor('sz', driver, axis=1)

    # Coarse stages
    if ask_yes_no('Initialise short branch coarse stages?'):
        # McLennan 1 (sample coarse x translation)
        driver = instantiate_driver(**DRIVER_DATA['mclennan1'])
        drivers['mclennan_sample'] = driver
        if driver is not None:
            motors['ssx'] = mclennan.Motor('ssx', driver)

        # McLennan 2 (detector coarse x translation)
        driver = instantiate_driver(**DRIVER_DATA['mclennan2'])
        drivers['mclennan_detector'] = driver
        if driver is not None:
            motors['dsx'] = mclennan.Motor('dsx', driver)

    if ask_yes_no('Initialise Varex detector?'):
        driver = instantiate_driver(**DRIVER_DATA['varex'])
        drivers['varex'] = driver
        if driver is not None:
            cameras['varex'] = driver.Camera('varex', driver)

    if ask_yes_no('Initialise PCO camera?'):
        print('TODO')

    if ask_yes_no('Initialise Andor camera?'):
        print('TODO')

    if ask_yes_no('Initialise microscope?'):
        print('TODO')

    if ask_yes_no('Initialise rotation stage?'):
        driver = instantiate_driver(**DRIVER_DATA['aerotech'])
        drivers['aerotech'] = driver
        if driver is not None:
            motors['rot'] = aerotech.Motor('rot', driver)

    if ask_yes_no('Initialise Newport XPS motors?'):
        print('TODO')

    if ask_yes_no('Initialize mecademic robot?'):
        driver = instantiate_driver(**DRIVER_DATA['mecademic'])
        drivers['mecademic'] = driver
        if driver is not None:
            motors.update(driver.create_motors())

    if ask_yes_no('Initialise stage pseudomotors?'):
        print('TODO')
        # motors['sxl'] = labframe.Motor(
        #    'sxl', motors['sx'], motors['sz'], motors['rot'], axis=0)
        # motors['szl'] = labframe.Motor(
        #    'szl', motors['sx'], motors['sz'], motors['rot'], axis=1)

    if ask_yes_no('Dump all motor objects in global namespace?'):
        # This is a bit of black magic
        for s in inspect.stack():
            if 'init_all' in s[4][0]:
                s[0].f_globals.update(motors)
                break

    return


def init_dummy(yes=None):
    """
    Initialize the dummy component for testing
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        ui_utils.user_interactive = False

    if ask_yes_no("Start dummy driver?"):
        driver = instantiate_driver(**DRIVER_DATA['dummy'])
        drivers['dummy'] = driver


# Command Line Interface

@click.group(help='Labcontrol daemon management')
def cli():
    pass


@cli.command(help='List available daemons')
def list():
    click.echo('Here I will list all available daemons')


@cli.command(help='List running daemons')
def running():
    click.echo('Here I will list all running daemons')


@cli.command(help='Start a daemon')
@click.argument('name')
def start(name):
    click.echo(f'Starting server proxy for driver {name}')
    if name == 'mecademic':
        s = mecademic.Mecademic.Server(instantiate=True)
        s.wait()
        sys.exit(0)
    if name == 'dummy':
        s = dummy.Dummy.Server(instantiate=True)
        s.wait()
        sys.exit(0)
    if name == 'smaract':
        s = smaract.Smaract.Server(instantiate=True)
        s.wait()
        sys.exit(0)
    if name == 'mclennan1' or name == 'mclennan2':
        # Here we have more than one motors
        s = mclennan.McLennan.Server(address=NETWORK_CONF[name]['DAEMON'],
                                     instantiate=True,
                                     instance_kwargs=dict(address=NETWORK_CONF[name]['DEVICE']))
        s.wait()
        sys.exit(0)
    if name == 'aerotech':
        s = aerotech.Aerotech.Server()
        s.wait()
        sys.exit(0)
    if name == 'excillum':
        s = excillum.Excillum.Server()
        s.wait()
        sys.exit(0)
    # pco, varex, xspectrum, xps

