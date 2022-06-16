"""
Full initialization procedure and command line access for the
startup of daemons.

For instance typing `python -m labcontrol.startup mecademic`
will start the mecademic daemon.
"""
import logging
import sys
import inspect
import click

from . import ui_utils
from .manager import instantiate_driver, DRIVER_DATA
from . import network_conf
from .ui_utils import ask_yes_no
from . import drivers, motors
from . import aerotech
from . import mclennan
from . import mecademic
from . import microscope
from . import smaract
from . import excillum

logger = logging.getLogger()


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
        drivers['ssx'] = driver
        if driver is not None:
            motors['ssx'] = mclennan.Motor('ssx', driver)

        # McLennan 2 (detector coarse x translation)
        driver = instantiate_driver(**DRIVER_DATA['mclennan2'])
        drivers['dsx'] = driver
        if driver is not None:
            motors['dsx'] = mclennan.Motor('dsx', driver)

    if ask_yes_no('Initialise PCO camera?'):
        print('TODO')

    if ask_yes_no('Initialise Andor camera?'):
        print('TODO')

    if ask_yes_no('Initialise microscope?'):
        print('TODO')

    if ask_yes_no('Initialise rotation stage?'):
        driver = instantiate_driver(**DRIVER_DATA['aerotech'])
        drivers['rot'] = driver
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
        #motors['sxl'] = labframe.Motor(
        #    'sxl', motors['sx'], motors['sz'], motors['rot'], axis=0)
        #motors['szl'] = labframe.Motor(
        #    'szl', motors['sx'], motors['sz'], motors['rot'], axis=1)

    if ask_yes_no('Dump all motor objects in global namespace?'):
        # This is a bit of black magic
        for s in inspect.stack():
            if 'init_all' in s[4][0]:
                s[0].f_globals.update(motors)
                break

    return

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
    if name == 'mecademic':
        click.echo(f'Starting daemon {name}')
        mecademic.MecademicDaemon.run()
        sys.exit(0)
    if name == 'smaract':
        click.echo(f'Starting daemon {name}')
        smaract.SmaractDaemon.run()
        sys.exit(0)
    if name == 'mclennan1':
        # Here we have more than one motors
        click.echo(f'Starting daemon {name}')
        mclennan.McLennanDaemon.run(serving_address=network_conf.MCLENNAN1['DAEMON'],
                                    device_address=network_conf.MCLENNAN1['DEVICE'])
        sys.exit(0)
    if name == 'mclennan2':
        # Here we have more than one motors
        click.echo(f'Starting daemon {name}')
        mclennan.McLennanDaemon.run(serving_address=network_conf.MCLENNAN2['DAEMON'],
                                    device_address=network_conf.MCLENNAN2['DEVICE'])
        sys.exit(0)
    if name == 'aerotech':
        click.echo(f'Starting daemon {name}')
        aerotech.AerotechDeamon.run()
        sys.exit(0)
    if name == 'excillum':
        click.echo(f'Excillum driver not implemented yet')
        # excillum.ExcillumDaemon.run()
        sys.exit(0)
    # pco, varex, xspectrum, xps

if __name__ == "__main__":
    cli()
    
