"""
Manage driver and daemon creation.
"""

import subprocess
import time

import logging
import sys
import inspect
import click

from . import THIS_HOST, LOCAL_HOSTNAME
from .network_conf import NETWORK_CONF, HOST_IPS
from .util.future import Future
from .util.logs import logging_muted
from .util.uitools import ask_yes_no
from .util.proxydevice import ProxyClientError
from . import drivers, motors
from . import aerotech
from . import mclennan
from . import mecademic
from . import dummy
from . import workflow
#from . import microscope
from . import smaract
from . import excillum
from . import varex

DRIVER_DATA = {'mecademic': {'driver': mecademic.Mecademic, 'net_info': NETWORK_CONF['mecademic']},
               'smaract': {'driver': smaract.Smaract, 'net_info': NETWORK_CONF['smaract']},
               'aerotech': {'driver': aerotech.Aerotech, 'net_info': NETWORK_CONF['aerotech']},
               'mclennan1': {'driver': mclennan.McLennan1, 'net_info': NETWORK_CONF['mclennan1']},
               'mclennan2': {'driver': mclennan.McLennan2, 'net_info': NETWORK_CONF['mclennan2']},
               'mclennan3': {'driver': mclennan.McLennan3, 'net_info': NETWORK_CONF['mclennan3']},
               'excillum': {'driver': excillum.Excillum, 'net_info': NETWORK_CONF['excillum']},
               'dummy': {'driver': dummy.Dummy, 'net_info': NETWORK_CONF['dummy']},
               'varex': {'driver': varex.Varex, 'net_info': NETWORK_CONF['varex']},
               'experiment': {'driver': workflow.Experiment, 'net_info': NETWORK_CONF['experiment']}
              # 'xps': {},
              # 'pco': {},
              #'xspectrum': {'driver': xspectrum.XSpectrum},
               }

# List of drivers that should run on the current host
AVAILABLE = [k for k, v in NETWORK_CONF.items() if v['control'][0] in HOST_IPS.get(THIS_HOST, [])]

logger = logging.getLogger("manager")


def instantiate_driver(name, admin=True):
    """
    Helper function to instantiate a driver (client).

    name: driver name - a key of DRIVER_DATA.
    admin: If True, request admin rights
    """
    driver_data = DRIVER_DATA[name]
    driver = driver_data['driver']
    net_info = driver_data['net_info']

    try:
        d = driver.Client(address=net_info['control'],
                          admin=admin,
                          name=name)
        # temporize slightly
        time.sleep(.5)
        
        return d
    except ProxyClientError:
        logger.warning(f'The proxy server for driver {name} is unreachable')
        return None




# Command Line Interface

@click.group(help='Labcontrol proxy driver management')
def cli():
    pass


@cli.command(help='List proxy drivers that can be spawned on the current host')
def list():
    available_drivers = [k for k, v in NETWORK_CONF.items() if v['control'][0] in HOST_IPS[THIS_HOST]]
    click.echo('Available drivers:\n\n * ' + '\n * '.join(available_drivers))


@cli.command(help='List running proxy drivers')
def running():
    click.echo('Running drivers:\n\n')
    with logging_muted():
        for name in DRIVER_DATA.keys():
            click.echo(f' * {name+":":<20}', nl=False)
            d = instantiate_driver(name)
            if d is not None:
                click.secho('YES', fg='green')
            else:
                click.secho('NO', fg='red')


@cli.command(help='Start the server proxy of driver [name]. Does not return.')
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

    click.echo(f'{name+":":<15}', nl=False)

    # Check if already running
    with logging_muted():
        d = instantiate_driver(name)
    if d is not None:
        click.secho('ALREADY RUNNING', fg='yellow')
        return

    # Get driver class and instantiation arguments
    driver_cls = driver_data['driver']
    instance_args = driver_data.get('instance_args', ())
    instance_kwargs = driver_data.get('instance_kwargs', {})

    # Start the server
    with logging_muted():
        s = driver_cls.Server(address=net_info['control'],
                          instantiate=True,
                          instance_args=instance_args,
                          instance_kwargs=instance_kwargs)

    # Wait for completion, then exit.
    click.secho('RUNNING', fg='green')
    s.wait()
    sys.exit(0)


@cli.command(help='Kill the server proxy of driver [name] if running.')
@click.argument('name', nargs=-1)
def kill(name):
    d = instantiate_driver(name[0])
    if d:
        time.sleep(.2)
        d.ask_admin(True, True)
        time.sleep(.2)
        d._proxy.kill()


@cli.command(help='Kill all running server proxy.')
def killall():
    futures = []
    for name in DRIVER_DATA.keys():
        futures.append(Future(kill, ((name,),)))
    for f in futures:
        f.join()


@cli.command(help='Start all proxy drivers on separate processes.')
def startall():

    monitor_time = 10

    available_drivers = [k for k, v in NETWORK_CONF.items() if v['control'][0] in HOST_IPS[THIS_HOST]]

    processes = {}
    for name in available_drivers:
        processes[name] = subprocess.Popen([sys.executable, '-m', 'labcontrol', 'start', f'{name}'],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)

    # Monitor for failure
    time.sleep(.5)
    t0 = time.time()
    failed = []
    while time.time() < (t0 + monitor_time):
        for name, p in processes.items():
            err = p.stderr.read().decode()
            if ('Traceback ' in err) or (p.poll() is not None):
                # Process exited
                logger.warning(f'Driver proxy spawning for {name} failed!')
                print(err)
                failed.append(name)
        for f in failed:
            processes.pop(f, None)
        if not processes:
            break
        time.sleep(.1)


def boot(monitor_time=10):
    """
    Initialize all proxy servers that should run on this host.
    Wait for monitor_time to check and report errors.
    """
    # Start a new process for all proxy servers
    processes = {}
    for name in AVAILABLE:
        processes[name] = subprocess.Popen([sys.executable, '-m', 'labcontrol', 'start', f'{name}'],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
        logger.info(f'Spawning proxy server process for driver {name}...')

    # Monitor for failure
    time.sleep(.5)
    t0 = time.time()
    failed = []
    while time.time() < (t0 + monitor_time):
        for name, p in processes.items():
            err = p.stderr.read().decode()
            if ('Traceback ' in err) or (p.poll() is not None):
                # Process exited
                logger.warning(f'Driver proxy spawning for {name} failed!')
                print(err)
                failed.append(name)
        for f in failed:
            processes.pop(f, None)
        if not processes:
            break
        time.sleep(.1)
    return len(failed)
