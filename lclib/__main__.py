"""
Lab control CLI entry point.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
# TODO: spawn and start should not override the log levels stored in the config files


import time
import sys
import os
import click
import logging
import subprocess

from . import logs, get_config, client_or_None, _driver_classes
from .camera import CameraBase
from .logs import logging_muted, log_to_file, logger as rootlogger
from . import ui

lab_info = {}

@click.group(help=f'Lab-control-lib driver management')
@click.argument('labname')
def cli(labname):
    """
    Get lab name, import if needed, and populate lab_info with information needed for other commands.
    """

    # Pull the lab config
    config = get_config()

    # lab module name
    lab_module = config.get('module')

    # If no proper config exists, that's probably because lclib.init() has not been called
    if lab_module is None:
        import importlib
        try:
            labpackage = importlib.import_module(labname)
        except ModuleNotFoundError:
            raise click.BadParameter(f'Package {labname} not found')

    # Get again properly populated config
    config = get_config()

    lab_name = config['lab_name']
    lab_module = config['module']
    if lab_module != labname:
        raise click.BadParameter(f'Lab name {labname} does not match already imported {lab_module}')

    lab_info['lab_name'] = lab_name
    lab_info['lab_module'] = lab_module
    lab_info['this_host'] = config['this_host']
    lab_info['local_hostname'] = config['local_hostname']
    lab_info['log_dir'] = logs.log_dir

    # Spawn information
    lab_info['spawn_info'] = config['spawn_info']

    # List of addresses to access registered devices
    lab_info['device_addresses'] = {name: cls.Server.ADDRESS for name, cls in _driver_classes.items()}

    local_ip_list = config['local_ip_list']
    lab_info['local_ip_list'] = local_ip_list

    # List of all devices
    lab_info['all_drivers'] = [name for name, address in lab_info['device_addresses'].items()]

    # List of devices that can run on this host
    lab_info['local_drivers'] = [name for name, address in lab_info['device_addresses'].items() if address[0] in local_ip_list]

    # List Camera devices
    lab_info['cameras'] = {name: cls for name, cls in _driver_classes.items() if issubclass(cls, CameraBase)}


@cli.command(help='List proxy drivers that can be spawned on the current host')
def list():
    s = 'Available drivers (*=on this host):\n\n - '
    s += '\n - '.join([f'{name}*' if name in lab_info['local_drivers'] else f'{name}' for name in lab_info['all_drivers']])
    click.echo(s + '\n')

@cli.command(help='List running proxy drivers')
def running():
    click.echo('Running drivers:\n\n')
    with logging_muted():
        for name in lab_info['all_drivers']:
            click.echo(f' * {name+":":<20}', nl=False)
            d = client_or_None(name, client_name=f'check-{lab_info["this_host"]}')
            if d is not None:
                click.secho('YES', fg='green')
            else:
                click.secho('NO', fg='red')


@cli.command(help='Spawn server proxy of driver [name].')
@click.argument('name', nargs=-1)
@click.option('--log', '-l', 'loglevel', default='INFO', show_default=True, help='Log level.')
@click.option('--log-global', '-L', 'loglevel_global', default='INFO', show_default=True, help='Log level for all components')
def spawn(name, loglevel, loglevel_global):

    try:
        llg = int(loglevel_global)
    except ValueError:
        try:
            llg = logging._nameToLevel[loglevel_global]
        except KeyError:
            raise click.BadParameter(f'Unknown log level: {loglevel_global}')

    try:
        ll = int(loglevel)
    except ValueError:
        try:
            ll = logging._nameToLevel[loglevel]
        except KeyError:
            raise click.BadParameter(f'Unknown log level: {loglevel}')

    # Without driver name: list all drivers
    if not name:
        list()
        return

    if len(name) > 1:
        click.echo('Warning, only supporting one driver at a time for the moment.')

    name = name[0]

    click.echo(f'{name+":":<15}', nl=False)

    # Check if already running
    with logging_muted():
        d = client_or_None(name, client_name=f'check-{lab_info["this_host"]}')
    if d is not None:
        click.secho('ALREADY RUNNING', fg='yellow')
        return

    call_list = ['python', '-m', __package__, lab_info['lab_module'], "start", name, "-l", str(ll), "-L", str(llg)]
    if name in lab_info['local_drivers']:
        # Local driver: easy, just run it.
        process = subprocess.Popen(call_list, start_new_session=True)
        click.secho(f'RUNNING (PID: {process.pid}', fg='green')
        return

    # Driver is not local
    driver_ip = lab_info['device_addresses'][name][0]
    # TODO: figure out how to do this is a multiplatform way
    # subprocess.run(["ssh", driver_ip] + call_list) # Doesn't work
    click.secho(f'SPAWNING REMOTE DRIVERS IS NOT YET IMPLEMENTED', fg='red')
    return

@cli.command(help='Start the server proxy of driver [name]. Does not return.')
@click.argument('name', nargs=-1)
@click.option('--log', '-l', 'loglevel', default='INFO', show_default=True, help='Log level.')
@click.option('--log-global', '-L', 'loglevel_global', default='INFO', show_default=True, help='Log level for all components')
def start(name, loglevel, loglevel_global):

    try:
        llg = int(loglevel_global)
    except ValueError:
        try:
            llg = logging._nameToLevel[loglevel_global]
        except KeyError:
            raise click.BadParameter(f'Unknown log level: {loglevel_global}')
    rootlogger.setLevel(llg)

    # Without driver name: list available drivers on current host
    if not name:
        list()
        return

    if len(name) > 1:
        click.echo('Warning, only supporting one driver at a time for the moment.')

    name = name[0]

    if name not in lab_info['local_drivers']:
        raise click.BadParameter(f'Driver {name} cannot be launched from host {lab_info["this_host"]} ({lab_info["local_hostname"]}).')

    click.echo(f'{name+":":<15}', nl=False)

    # Check if already running
    with logging_muted():
        d = client_or_None(name, client_name=f'check-{lab_info["this_host"]}')
    if d is not None:
        click.secho('ALREADY RUNNING', fg='yellow')
        return

    try:
        ll = int(loglevel)
    except ValueError:
        try:
            ll = logging._nameToLevel[loglevel]
        except KeyError:
            raise click.BadParameter(f'Unknown log level: {loglevel}')

    # Log to file
    log_file = os.path.join(lab_info['log_dir'], f'optimato-labcontrol-{name}.log')
    log_to_file(log_file)

    # Start the server
    # with logging_muted():
    # s = Classes[name].Server(address=net_info['control'], instantiate=True)
    s = _driver_classes[name].Server(instantiate=True)

    click.secho('RUNNING', fg='green')

    s.instance.set_log_level(ll)

    # Wait for completion, then exit.
    s.wait()
    sys.exit(0)



@cli.command(help='Kill the server proxy of driver [name] if running.')
@click.argument('name', nargs=-1)
def kill(name):
    d = client_or_None(name[0], client_name=f'killer-{lab_info["this_host"]}')
    if d:
        time.sleep(.2)
        d.ask_admin(True, True)
        time.sleep(.2)
        d.kill_server()


@cli.command(help='Kill all running server proxy.')
def killall():
    # First ask manager to kill all other servers
    d = client_or_None('manager', client_name=f'killer-{lab_info["this_host"]}')
    if not d:
        click.Abort('Could not connect to manager!')
    time.sleep(.5)
    try:
        d.ask_admin(True, True)
        d.killall()
        # Then kill manager
        d.ask_admin(True, True)
        d.kill_server()
    except AttributeError:
        # For some reason d can still be None at this point.
        click.Abort('Could not connect to manager!')


@cli.command(help='Start Display real-time logs of all running drivers')
def logall():
    click.echo('Not implemented.')

@cli.command(help='Start frame viewer')
@click.argument('name', nargs=1)
@click.option('--log', '-l', 'loglevel', default='INFO', show_default=True, help='Log level.')
@click.option('--type', '-t', 'vtype', default='napari', show_default=True, help='Viewer type: "napari" or "cv".')
@click.option('--maxfps', '-m', default=10, show_default=True, help='Maximum refresh rate (FPS).')
def viewer(name, loglevel, vtype, maxfps):
    name = name.lower()
    cam_cls = lab_info['cameras'].get(name, None)
    addr = cam_cls.DEFAULT_BROADCAST_ADDRESS
    if not addr:
        click.echo(f'Unknown detector: {name}')
        sys.exit(0)
    if vtype.lower() == 'napari':
        Vclass = ui.viewers.NapariViewer
    elif vtype.lower() == 'cv':
        Vclass = ui.viewers.CvViewer
    else:
        click.echo(f'Unknown viewer type: {vtype}')
        sys.exit(0)

    if maxfps > 25:
        click.echo(f'Frame rate cannot be higher than 25.')
        sys.exit(0)
    if maxfps < 0:
        click.echo(f'Invalid FPS')
        sys.exit(0)

    try:
        ll = int(loglevel)
    except ValueError:
        try:
            ll = logging._nameToLevel[loglevel]
        except KeyError:
            raise click.BadParameter(f'Unknown log level: {loglevel}')

    v = Vclass(address=addr, max_fps=maxfps, camera_name=name)
    v.logger.setLevel(ll)
    v.start()
    sys.exit(0)


if __name__ == "__main__":
    cli()