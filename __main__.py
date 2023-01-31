import time
import sys
import click
import logging

from . import THIS_HOST, LOCAL_HOSTNAME, client_or_None, Classes
from .network_conf import NETWORK_CONF, HOST_IPS
from .util.future import Future
from .util.logs import logging_muted, DisplayLogger, logger as rootlogger


AVAILABLE = [k for k, v in NETWORK_CONF.items() if v['control'][0] in HOST_IPS.get(THIS_HOST, [])]


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
        for name in NETWORK_CONF.keys():
            click.echo(f' * {name+":":<20}', nl=False)
            d = client_or_None(name)
            if d is not None:
                click.secho('YES', fg='green')
            else:
                click.secho('NO', fg='red')


@cli.command(help='Start the server proxy of driver [name]. Does not return.')
@click.argument('name', nargs=-1)
@click.option('--log', '-l', 'loglevel', default='INFO', show_default=True, help='Log level.')
def start(name, loglevel):
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
        net_info = NETWORK_CONF[name]
    except KeyError:
        raise click.BadParameter(f'No driver named {name}')

    click.echo(f'{name+":":<15}', nl=False)

    # Check if already running
    with logging_muted():
        d = client_or_None(name)
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

    rootlogger.setLevel(ll)

    # Start the server
    with logging_muted():
        s = Classes[name].Server(address=net_info['control'], instantiate=True)

    click.secho('RUNNING', fg='green')

    # Wait for completion, then exit.
    s.wait()
    sys.exit(0)


@cli.command(help='Kill the server proxy of driver [name] if running.')
@click.argument('name', nargs=-1)
def kill(name):
    d = client_or_None(name[0])
    if d:
        time.sleep(.2)
        d.ask_admin(True, True)
        time.sleep(.2)
        d._proxy.kill()


@cli.command(help='Kill all running server proxy.')
def killall():
    futures = []
    for name in NETWORK_CONF.keys():
        futures.append(Future(kill, ((name,),)))
    for f in futures:
        f.join()


@cli.command(help='Start Display real-time logs of all running drivers')
def logall():
    dl = DisplayLogger()
    for name, data in NETWORK_CONF.items():
        if addr:= data['net_info'].get('logging', None):
            dl.sub(name, addr)
    dl.show()

@cli.command(help='Start frame viewer')
@click.argument('name', nargs=1)
@click.option('--type', '-t', 'vtype', default='napari', show_default=True, help='Viewer type: "napari" or "cv".')
@click.option('--maxfps', '-m', default=10, show_default=True, help='Maximum refresh rate (FPS).')
def viewer(name, vtype, maxfps):
    from .util import viewers
    viewer_addr = {'varex': (NETWORK_CONF['varex']['control'][0],
                             NETWORK_CONF['varex']['broadcast_port']),
                   'xspectrum': (NETWORK_CONF['xspectrum']['control'][0],
                             NETWORK_CONF['xspectrum']['broadcast_port'])
                   }
    addr = viewer_addr.get(name.lower(), None)
    if not addr:
        click.echo(f'Unknown detector: {name}')
        sys.exit(0)
    if vtype.lower() == 'napari':
        Vclass = viewers.NapariViewer
    elif vtype.lower() == 'cv':
        Vclass = viewers.CvViewer
    else:
        click.echo(f'Unknown viewer type: {vtype}')
        sys.exit(0)

    if maxfps > 25:
        click.echo(f'Frame rate cannot be higher than 25.')
        sys.exit(0)
    if maxfps < 0:
        click.echo(f'Invalid FPS')
        sys.exit(0)

    v = Vclass(address=addr, max_fps=maxfps)
    v.start()
    sys.exit(0)

#@cli.command(help='Start all proxy drivers on separate processes.')
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
