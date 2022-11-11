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
from . import xspectrum

DRIVER_DATA  = {'mecademic': {'driver': mecademic.Mecademic, 'net_info': NETWORK_CONF['mecademic']},
                'smaract': {'driver': smaract.Smaract, 'net_info': NETWORK_CONF['smaract']},
                'aerotech': {'driver': aerotech.Aerotech, 'net_info': NETWORK_CONF['aerotech']},
                'mclennan1': {'driver': mclennan.McLennan1, 'net_info': NETWORK_CONF['mclennan1']},
                'mclennan2': {'driver': mclennan.McLennan2, 'net_info': NETWORK_CONF['mclennan2']},
                'mclennan3': {'driver': mclennan.McLennan3, 'net_info': NETWORK_CONF['mclennan3']},
                'excillum': {'driver': excillum.Excillum, 'net_info': NETWORK_CONF['excillum']},
                'dummy': {'driver': dummy.Dummy, 'net_info': NETWORK_CONF['dummy']},
                'varex': {'driver': varex.Varex, 'net_info': NETWORK_CONF['varex']},
              # 'xps': {},
              # 'pco': {},
              #'xspectrum': {'driver': xspectrum.XSpectrum},
                }


logger = logging.getLogger("manager")


def instantiate_driver(name, admin=True, spawn=True):
    """
    Helper function to instantiate a driver (client) and spawn the corresponding server proxy
    if necessary and requested.

    name: driver name - a key of DRIVER_DATA.
    admin: If True, request admin rights
    spawn: If True, start the remote server if it is not found.
    """
    driver_data = DRIVER_DATA[name]
    driver = driver_data['driver']
    net_info = driver_data['net_info']

    # Try to instantiate a driver client
    d = None
    while True:
        try:
            d = driver.Client(address=net_info['control'],
                              admin=admin,
                              name=name)
            return d
        except ProxyClientError:
            if not spawn:
                logger.warning(f'The proxy server for driver {name} is unreachable')
                return None

            # Didn't connect. Let's try to spawn the server.
            if ask_yes_no(f'Server proxy for {name} unreachable. Spawn it?'):

                # TODO: use paramiko.SSHClient for drivers that need to start on another host
                # On windows, the command will be something like:
                # Invoke-CimMethod -ClassName 'Win32_Process' -MethodName Create -Arguments @{ CommandLine = 'python -m labcontrol start varex'}
                p = subprocess.Popen([sys.executable, '-m', 'labcontrol', 'start', f'{name}'],
                                     start_new_session=True,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
                logger.info(f'Trying to spawn proxy server process for driver {name}.')

                time.sleep(.5)
                t0 = time.time()
                failed = False
                while time.time() < t0 + 10:
                    err = p.stderr.read()
                    if (b'Error' in err) or (p.poll() is not None):
                        # Process exited
                        logger.warning('Driver proxy spawning failed')
                        failed = True
                        break
                    time.sleep(.1)

                if failed:
                    break

                spawn = False
                continue
            else:
                logger.error(f'Driver {driver.__name__} is not running.')
                return None
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

def init(yes=None, spawn=False):
    """
    Initialize components of the setup.
    Syntax:
        init()
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        ui_utils.user_interactive = False

    # Excillum
    if ask_yes_no("Connect to Excillum?"):
        driver = instantiate_driver(name='excillum', spawn=spawn)
        drivers['excillum'] = driver

    # Smaract
    if ask_yes_no('Initialise smaracts?',
                  help="SmarAct are the 3-axis piezo translation stages for high-resolution sample movement"):
        driver = instantiate_driver(name='smaract', spawn=spawn)
        drivers['smaract'] = driver
        if driver is not None:
            motors['sx'] = smaract.Motor('sx', driver, axis=0)
            motors['sy'] = smaract.Motor('sy', driver, axis=2)
            motors['sz'] = smaract.Motor('sz', driver, axis=1)

    # Coarse stages
    if ask_yes_no('Initialise short branch coarse stages?'):
        # McLennan 1 (sample coarse x translation)
        driver = instantiate_driver(name='mclennan1', spawn=spawn)
        drivers['mclennan_sample'] = driver
        if driver is not None:
            motors['ssx'] = mclennan.Motor('ssx', driver)

        # McLennan 2 (detector coarse x translation)
        driver = instantiate_driver(name='mclennan2', spawn=spawn)
        drivers['mclennan_detector'] = driver
        if driver is not None:
            motors['dsx'] = mclennan.Motor('dsx', driver)

    if ask_yes_no('Initialise Varex detector?'):
        driver = instantiate_driver(name='varex', spawn=spawn)
        drivers['varex'] = driver

    if ask_yes_no('Initialise PCO camera?'):
        print('TODO')

    if ask_yes_no('Initialise Andor camera?'):
        print('TODO')

    if ask_yes_no('Initialise microscope?'):
        print('TODO')

    if ask_yes_no('Initialise rotation stage?'):
        driver = instantiate_driver(name='aerotech', spawn=spawn)
        drivers['aerotech'] = driver
        if driver is not None:
            motors['rot'] = aerotech.Motor('rot', driver)

    if ask_yes_no('Initialise Newport XPS motors?'):
        print('TODO')

    if ask_yes_no('Initialize mecademic robot?'):
        driver = instantiate_driver(name='mecademic', spawn=spawn)
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
        driver = instantiate_driver(name='dummy')
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


@cli.command(help='Start a server proxy for a given name')
@click.argument('name', nargs=-1)
def start(name):
    available_drivers = [k for k, v in NETWORK_CONF.items() if v['control'][0] in HOST_IPS[THIS_HOST]]

    # Without driver name: list available drivers on current host
    if not name:
        click.echo('Available drivers on this host:\n * ' + '\n * '.join(available_drivers))
        return

    if len(name) > 1:
        click.echo('Warning, only supporting one driver at a time for the moment.')

    name = name[0]

    if name not in available_drivers:
        raise click.BadParameter(f'Driver {name} cannot be launched from host {THIS_HOST} ({LOCAL_HOSTNAME}).')

    # Get driver info
    try:
        driver_data = DRIVER_DATA[name]
        net_info = NETWORK_CONF[name]
    except KeyError:
        raise click.BadParameter(f'No driver named {name}')

    click.echo(f'Starting server proxy for driver {name}')

    # Get driver class and instantiation arguments
    driver_cls = driver_data['driver']
    instance_args = driver_data.get('instance_args', ())
    instance_kwargs = driver_data.get('instance_kwargs', {})

    # Start the server
    s = driver_cls.Server(address=net_info['control'],
                          instantiate=True,
                          instance_args=instance_args,
                          instance_kwargs=instance_kwargs)

    # Wait for completion, then exit.
    s.wait()
    sys.exit(0)