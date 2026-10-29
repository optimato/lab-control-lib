"""
Lab control CLI entry point.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import time
import sys
import os
import signal
import datetime
import concurrent.futures
import click
import logging

from . import logs, get_config, client_or_None, _driver_classes, ProxyDeviceError
from .proxydevice import ProxyServerBase
from .util import Future
from .camera import CameraBase
from .logs import logging_muted, log_to_file, log_to_mem, logger as rootlogger
from . import ui
from . import daemon as dd

lab_info = {}


def _parse_level(level):
    """
    Convert a log level given as a number or a name to an int.
    """
    try:
        return logs.level_number(level)
    except ValueError as e:
        raise click.BadParameter(str(e))

def _exit_on_sigterm(signum, frame):
    """
    Turn SIGTERM into a normal exit, so that atexit handlers (driver shutdown) are called.
    """
    sys.exit(128 + signum)

def _raised_by_driver(error):
    """
    True if error was raised while instantiating the driver. In this case the proxy
    server has already logged it, with its traceback.
    """
    tb = error.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code is ProxyServerBase.create_instance.__code__:
            return True
        tb = tb.tb_next
    return False

def _connect_daemon(ip):
    """
    Connect to the daemon of the host with the given ip, and check that it is recent enough.
    """
    # Only warnings and errors from the daemon client
    rootlogger.getChild(dd.ProcessPool.Client.LOGGER_NAME).setLevel(logging.WARNING)
    try:
        with logging_muted():
            client = dd.ProcessPool.Client(address=(ip, dd.DAEMON_PORT))
    except ProxyDeviceError as e:
        # The message gives the reason (refused, timed out, no route to host, ...)
        raise click.UsageError(f'Cannot reach the daemon on host {_host_name(ip)}. {e}')
    try:
        version = client.api_version()
    except AttributeError:
        # Daemon older than the version check
        version = 1
    if version < dd.API_VERSION:
        raise click.UsageError(f'The daemon on host {_host_name(ip)} is too old: update lclib on that host '
                               f'and restart the daemon (python -m lclib -r).')
    return client

def _host_name(ip):
    """
    Name of the host with the given ip (the ip itself if not in the lab hosts).
    """
    names = {host_ip: host for host, host_ip in lab_info['host_ips'].items()}
    return names.get(ip, ip)

def _format_duration(seconds):
    """
    Format a duration as [days d] h:mm:ss.
    """
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    text = f'{hours}:{minutes:02}:{seconds:02}'
    return f'{days}d {text}' if days else text

# Colors of the driver states shown by `status`
STATE_COLORS = {'RUNNING': 'green',
                'STARTING': 'yellow',
                'STOPPING': 'yellow',
                'FAILED': 'red',
                'UNKNOWN': 'red'}


@click.group(help=f'Lab-control-lib driver management', invoke_without_command=True)
@click.argument('labname', required=False)
@click.option('-d', '--daemon', is_flag=True, help='Start daemon.')
@click.option('-r', '--restart', is_flag=True, help='Kill daemon. Since it is running as a service, it will restart.')
@click.pass_context
def cli(ctx, labname, daemon, restart):
    """
    Get lab name, import if needed, and populate lab_info with information needed for other commands.
    """
    if daemon:
        # Start daemon - this will block forever
        dd.setup_daemon_logging()
        s = dd.daemon_server()
        click.echo(f'Starting daemon on {s.ADDRESS[0]}:{s.ADDRESS[1]}')
        s.wait()
        sys.exit(0)

    if restart:
        # Restart daemon
        c = dd.daemon_client(reconnect="always")
        # Wait a little for connection to establish
        t = time.time()
        while time.time() - t < 1:
            if c.connected:
                break
            time.sleep(.05)
        if not c.connected:
            raise click.UsageError('Local daemon is not running')
        # Kill the daemon
        c.kill_server()
        click.echo('Local daemon has been killed. It will restart automatically.')
        sys.exit(0)
    
    # labname is not optional but had to be set to required=False to allow for the possibility of
    # usint the -d (--daemon) option
    if not ctx.invoked_subcommand:
        if not labname:
            raise click.UsageError("Missing required argument 'labname'.")

    # Pull the lab config
    config = get_config()

    # lab module name
    lab_module = config.get('module')

    # If no proper config exists, that's probably because lclib.init() has not been called
    if lab_module is None:
        import importlib
        try:
            labpackage = importlib.import_module(labname)
        except ModuleNotFoundError as e:
            # A missing dependency of the lab package (e.g. a vendor SDK) is reported as such
            if e.name != labname:
                raise
            raise click.BadParameter(f'Package {labname} not found')

    # Get again properly populated config
    config = get_config()

    lab_name = config['lab_name']
    lab_module = config['module']
    if lab_module != labname:
        raise click.BadParameter(f'Lab name {labname} does not match already imported {lab_module}')

    lab_info['module'] = lab_module
    lab_info['lab_name'] = lab_name
    lab_info['this_host'] = config['this_host']
    lab_info['local_hostname'] = config['local_hostname']
    lab_info['log_dir'] = logs.log_dir
    lab_info['conf_path'] = config['conf_path']
    lab_info['host_ips'] = config['host_ips']

    # List of addresses to access registered devices
    lab_info['device_addresses'] = {name: cls.Server.ADDRESS for name, cls in _driver_classes.items()}

    # List of devices that can run on this host
    local_ip_list = config['local_ip_list']
    lab_info['local_ip_list'] = local_ip_list
    lab_info['available'] = [name for name, address in lab_info['device_addresses'].items() if address[0] in local_ip_list]

    # List Camera devices
    lab_info['cameras'] = {name: cls for name, cls in _driver_classes.items() if issubclass(cls, CameraBase)}

@cli.command(help='List all drivers that can be spawned')
def list():
    click.echo('Available drivers:\n\n * ' + '\n * '.join([name + '(local)' if name in lab_info['available'] else name for name, cls in _driver_classes.items()]))

@cli.command(help='List proxy drivers that can be started on the current host')
def llist():
    click.echo('Available drivers on this host:\n\n * ' + '\n * '.join(lab_info['available']))

@cli.command(help='List running proxy drivers')
def running():
    click.echo('Running drivers:\n\n')
    with logging_muted():
        for name in _driver_classes.keys():
            click.echo(f' * {name+":":<20}', nl=False)
            d = client_or_None(name, client_name=f'check-{lab_info["this_host"]}')
            if d is not None:
                click.secho('YES', fg='green')
            else:
                click.secho('NO', fg='red')


@cli.command(help='Spawn the server proxy of driver [name].')
@click.argument('name', nargs=-1)
@click.option('--log', '-l', 'loglevel', default=None, help='Log level of the driver. [default: its saved level]')
@click.option('--log-global', '-L', 'loglevel_global', default=None, help='Log level for all components. [default: the lab level]')
@click.option('--timeout', '-t', default=60., show_default=True, help='Time (in seconds) to wait for the driver to be ready.')
def start(name, loglevel, loglevel_global, timeout):

    # Without driver name: list available drivers on current host
    if not name:
        list()
        return

    if len(name) > 1:
        click.echo('Warning, only supporting one driver at a time for the moment.')

    # Find the host where the driver can be launched
    name = name[0]
    host = lab_info['device_addresses'][name]

    daemon_client = _connect_daemon(host[0])

    click.echo(f'{name+":":<15}', nl=False)

    # Check if already running
    with logging_muted():
        d = client_or_None(name, client_name=f'check-{lab_info["this_host"]}')
    if d is not None:
        click.secho('ALREADY RUNNING', fg='yellow')
        return

    # Spawn the driver, then wait until it is ready
    status = daemon_client.start(lab=lab_info['module'],
                                 driver=name,
                                 loglevel=loglevel,
                                 loglevel_global=loglevel_global)
    t0 = time.time()
    while status['state'] == 'starting' and time.time() - t0 < timeout:
        time.sleep(.25)
        status = daemon_client.status(lab=lab_info['module'], driver=name)

    if status['state'] == 'running':
        click.secho('RUNNING', fg='green')
    elif status['state'] == 'starting':
        click.secho('STILL STARTING', fg='yellow')
        click.echo(f'The driver is not ready after {timeout:g} s. Its output is in {status["out_file"]} on host {host[0]}.')
        sys.exit(1)
    else:
        click.secho('FAILED', fg='red')
        click.echo('\n'.join(status['error_tail']))
        sys.exit(1)
    sys.exit(0)

@cli.command(help='Start locally the server proxy of driver [name]. Does not return.')
@click.argument('name', nargs=-1)
@click.option('--log', '-l', 'loglevel', default=None, help='Log level of the driver. [default: its saved level]')
@click.option('--log-global', '-L', 'loglevel_global', default=None, help='Log level for all components. [default: the lab level]')
@click.option('--ready-file', default=None, hidden=True, help='File written once the server is ready (used by the daemon).')
@click.option('--console-level', default=None, hidden=True, help='Log level of the console output (used by the daemon).')
def lstart(name, loglevel, loglevel_global, ready_file, console_level):

    # Exit cleanly on SIGTERM, so that the driver can release its device
    signal.signal(signal.SIGTERM, _exit_on_sigterm)

    # Otherwise, the level of the lab configuration (set at import)
    if loglevel_global is not None:
        rootlogger.setLevel(_parse_level(loglevel_global))

    # Without driver name: list available drivers on current host
    if not name:
        llist()
        return

    if len(name) > 1:
        click.echo('Warning, only supporting one driver at a time for the moment.')

    name = name[0]

    if name not in lab_info['available']:
        raise click.BadParameter(f'Driver {name} cannot be launched from host {lab_info["this_host"]} ({lab_info["local_hostname"]}).')

    # By hand: "<name>:   RUNNING" on one line. Started by the daemon (output in a file): the
    # status on a line of its own, so that log lines are not mixed with it.
    status_prefix = f'{name}: '
    if ready_file is None:
        click.echo(f'{name+":":<15}', nl=False)
        status_prefix = ''

    # Check if already running
    with logging_muted():
        d = client_or_None(name, client_name=f'check-{lab_info["this_host"]}')
    if d is not None:
        click.secho(status_prefix + 'ALREADY RUNNING', fg='yellow')
        sys.exit(3)

    # Otherwise, the driver level saved in its configuration (applied at instantiation)
    ll = None if loglevel is None else _parse_level(loglevel)

    # Log to file and to memory
    log_file = os.path.join(lab_info['log_dir'], f'{lab_info["lab_name"]}-{lab_info["module"]}-{name}.log')
    log_to_file(log_file)
    log_to_mem()

    # Also what is logged outside lclib: warnings and errors of all modules, and the
    # messages of the lab package (from the global level)
    logs.log_other_loggers(lab_info['module'], rootlogger.getEffectiveLevel())

    # Everything is now logged to file: the console output can be restricted
    if console_level is not None:
        logs.console_handler.setLevel(_parse_level(console_level))

    # Start the server
    try:
        s = _driver_classes[name].Server(instantiate=True)
    except Exception as error:
        if _raised_by_driver(error):
            # Already logged, no need for a second traceback
            sys.exit(1)
        raise
    # Driver level only: the proxy server keeps the global level (see ProxyServerBase)
    if ll is not None:
        s.instance.set_log_level(ll)

    # Tell the daemon that the server is ready, once it accepts connections
    # (rpyc starts listening on the serving thread)
    if ready_file is not None:
        t0 = time.time()
        while not s.rpyc_server.active and time.time() - t0 < 2.:
            time.sleep(.01)
        dd.write_json_atomic(ready_file, {'pid': os.getpid(),
                                          'address': s.ADDRESS,
                                          'log_file': log_file,
                                          'time': time.time()})

    click.secho(status_prefix + 'RUNNING', fg='green')

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

@cli.command(help='Stop the process of driver [name] through the daemon of its host (terminate it if needed).')
@click.argument('name', nargs=-1)
def forcekill(name):
    # Find the host where the driver can be launched
    name = name[0]
    host = lab_info['device_addresses'][name]

    daemon_client = _connect_daemon(host[0])
    try:
        status = daemon_client.kill_process(lab=lab_info['module'], driver=name)
    except RuntimeError as e:
        # Only the first line: the rest is the remote traceback
        raise click.ClickException(str(e).splitlines()[0])

    # The daemon asks the driver to shut down, and terminates it after a grace period
    click.echo(f'{name+":":<15}', nl=False)
    t0 = time.time()
    while status['state'] == 'stopping' and time.time() - t0 < 2 * dd.ProcessPool.STOP_GRACE_TIME:
        time.sleep(.25)
        status = daemon_client.status(lab=lab_info['module'], driver=name)

    if status['state'] == 'exited':
        click.secho('STOPPED', fg='green')
    else:
        click.secho(status['state'].upper(), fg='yellow')
        sys.exit(1)

@cli.command(help='Abort all drivers (does not kill them).')
def abortall():
    d = client_or_None('monitor', client_name=f'killer-{lab_info["this_host"]}')
    if d:
        d.abortall()
    else:
        click.Abort('Could not connect to monitor!')

@cli.command(help='Kill all running server proxy.')
def killall():
    # First ask monitor to kill all other servers
    d = client_or_None('monitor', client_name=f'killer-{lab_info["this_host"]}')
    if not d:
        click.Abort('Could not connect to monitor!')
    time.sleep(.5)
    try:
        d.ask_admin(True, True)
        d.killall()
        # Then kill monitor
        d.kill_server()
    except AttributeError:
        # For some reason d can still be None at this point.
        click.Abort('Could not connect to monitor!')
    except:
        raise

@cli.command(help='Start the control panel display')
def cp():
    app = ui.driver_control_panel.DeviceManagerApp()
    app.run(reload=False)
    sys.exit(0)

def _status_lines(value, depth=0):
    """
    Lines showing a driver status: one 'key: value' line per item of a dictionary (nested
    dictionaries indented below their key), or the value itself.
    """
    indent = '  ' * depth
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if not isinstance(value, dict):
        return [f'{indent}{value}']

    width = max((len(str(key)) for key in value), default=0) + 1
    lines = []
    for key, item in value.items():
        if isinstance(item, dict) and item:
            lines.append(f'{indent}{key}:')
            lines += _status_lines(item, depth + 1)
        else:
            if isinstance(item, bytes):
                item = item.decode('utf-8', errors='replace')
            lines.append(f'{indent}{str(key) + ":":<{width}}  {item}')
    return lines

def _echo_driver_status(name):
    """
    Print the status reported by the driver itself (DriverBase.status, which drivers can
    extend).
    """
    with logging_muted():
        client = _driver_client(name)
    if client is None:
        raise click.ClickException(f'Cannot reach driver {name} (is it running?).')
    try:
        if not hasattr(client, 'status'):
            raise click.ClickException(f'Driver {name} does not expose a status method.')
        status = client.status()
    except AttributeError:
        raise click.ClickException(f'Driver {name} runs an older version of lclib: restart it.')
    except click.ClickException:
        raise
    except Exception as e:
        # Only the first line: the rest is the remote traceback
        raise click.ClickException(f'Status of driver {name} failed: {str(e).splitlines()[0]}')
    finally:
        client.disconnect()
    click.echo('\n'.join(_status_lines(status)))

# Status of several drivers: time (in seconds) between two refreshes with --follow, and time
# after which a driver that has not answered is shown as busy
STATUS_INTERVAL = 2.
STATUS_TIMEOUT = 5.

def _status_error(error):
    """
    Short explanation of an error raised by a status call.
    """
    if isinstance(error, AttributeError):
        return 'runs an older version of lclib: restart it'
    # Only the first line: the rest is the remote traceback
    return f'status failed: {str(error).splitlines()[0]}'

def _show_statuses(names, follow):
    """
    Show the status reported by each of the drivers and, with follow, refresh it every
    STATUS_INTERVAL seconds until Ctrl-C. The drivers are asked in parallel, over connections
    kept open. A driver that does not answer within STATUS_TIMEOUT (e.g. busy with a long
    operation) is shown as busy, with its last status, and is not asked again before it
    answers.
    """
    clients = {}       # {driver: client}
    connecting = {}    # {driver: connection attempt in progress}
    calls = {}         # {driver: status call in progress}
    last = {}          # {driver: last status received}

    def start(target, *args):
        # On a daemon thread: a call to a busy driver does not prevent exiting
        return Future(target, args=args, callback=lambda result, error: None)

    def wait(futures):
        deadline = time.time() + STATUS_TIMEOUT
        for future in futures:
            future.join(max(0., deadline - time.time()))

    def refresh(first):
        """
        Returns {driver: (kind, value)}: kind is 'ok' (value: the status), 'busy' (value: the
        last status, or None), 'error' (value: an explanation) or 'unreachable'.
        """
        # Connect to the drivers not connected yet. In parallel, since unreachable hosts take
        # seconds to time out: wait for the connections only the first time.
        for name in names:
            if name not in clients and name not in connecting:
                connecting[name] = start(_driver_client, name)
        if first:
            wait(connecting.values())
        for name, attempt in [*connecting.items()]:
            if attempt.done():
                del connecting[name]
                if attempt.exception() is None and attempt.result() is not None:
                    clients[name] = attempt.result()

        # Ask the connected drivers for their status (not again before the last call answered)
        shown, started = {}, []
        for name, client in clients.items():
            if not hasattr(client, 'status'):
                shown[name] = ('error', 'does not expose a status method')
            elif name not in calls and client.connected:
                calls[name] = start(client.status)
                started.append(calls[name])
        wait(started)

        for name in names:
            if name in shown:
                continue
            call = calls.get(name)
            if call is None:
                shown[name] = ('unreachable', None)
            elif not call.done():
                shown[name] = ('busy', last.get(name))
            else:
                del calls[name]
                if call.exception() is None:
                    last[name] = call.result()
                    shown[name] = ('ok', last[name])
                else:
                    shown[name] = ('error', _status_error(call.exception()))
        return shown

    def show(shown):
        for name in names:
            kind, value = shown[name]
            if kind == 'unreachable':
                continue
            host = _host_name(lab_info['device_addresses'][name][0])
            if kind == 'busy':
                click.secho(f'── {name} ({host}) ── busy, last status:', fg='yellow')
            else:
                click.secho(f'── {name} ({host}) ──', fg='blue')
            if kind == 'error':
                click.secho(f'  {value}', fg='red')
            elif value is None:
                click.echo('  (no status yet)')
            else:
                click.echo('\n'.join(_status_lines(value, depth=1)))
            click.echo()
        unreachable = [name for name in names if shown[name][0] == 'unreachable']
        if unreachable:
            click.echo('Not reachable: ' + ', '.join(unreachable))

    # Connection errors are expected (drivers not running)
    with logging_muted():
        try:
            first = True
            while True:
                shown = refresh(first)
                if follow:
                    click.clear()
                    click.secho(f'Status at {time.strftime("%H:%M:%S")}, refreshed every {STATUS_INTERVAL:g} s '
                                f'(Ctrl-C to stop)', bold=True)
                    click.echo()
                show(shown)
                if not follow:
                    break
                first = False
                time.sleep(STATUS_INTERVAL)
        except KeyboardInterrupt:
            pass
        finally:
            for client in clients.values():
                client.disconnect()

@cli.command(name='status', help='Show the status of all drivers according to the daemon of their host or, with '
                                 'driver [names] or --all, the status reported by the drivers themselves.')
@click.argument('names', nargs=-1)
@click.option('--all', 'all_drivers', is_flag=True, help='The status reported by all the drivers.')
@click.option('--follow', '-f', is_flag=True, help=f'Refresh every {STATUS_INTERVAL:g} s, until Ctrl-C.')
def status_cmd(names, all_drivers, follow):
    if all_drivers and names:
        raise click.UsageError('Give driver names, or --all.')
    if all_drivers:
        names = tuple(lab_info['device_addresses'])
    for name in names:
        if name not in lab_info['device_addresses']:
            raise click.BadParameter(f'Unknown driver {name}.')

    # The status reported by the drivers
    if len(names) == 1 and not follow:
        _echo_driver_status(names[0])
        return
    if names:
        _show_statuses(names, follow)
        return
    if follow:
        raise click.UsageError('-f needs driver names, or --all.')

    # The status according to the daemons
    lab = lab_info['module']

    # Status of the drivers managed by each daemon (one call per host)
    statuses = {}
    problems = {}
    for ip in {address[0] for address in lab_info['device_addresses'].values()}:
        try:
            client = _connect_daemon(ip)
        except click.UsageError as e:
            problems[ip] = e.message
            continue
        statuses[ip] = client.status_all()
        client.disconnect()

    click.echo(f'{"Driver":<20}{"Host":<12}{"State":<12}{"Uptime":<14}PID')
    unmanaged = False
    for name, address in lab_info['device_addresses'].items():
        ip = address[0]
        click.echo(f'{name:<20}{_host_name(ip):<12}', nl=False)
        if ip in problems:
            click.secho('UNKNOWN', fg=STATE_COLORS['UNKNOWN'])
            continue
        status = statuses[ip].get(f'{lab}_{name}')
        if status is None:
            click.echo('-')
            unmanaged = True
            continue
        state = status['state'].upper()
        if state == 'EXITED' and status['failed']:
            state = 'FAILED'
        click.secho(f'{state:<12}', fg=STATE_COLORS.get(state), nl=False)
        if status['state'] == 'exited':
            click.echo()
        else:
            click.echo(f'{_format_duration(status["uptime"]):<14}{status["pid"]}')

    for problem in problems.values():
        click.secho(problem, fg='red')
    if unmanaged:
        click.echo('\n-: not started by the daemon (use the "running" command to check if it runs anyway).')

# Colors telling drivers apart in merged logs, and colors of the levels
DRIVER_COLORS = ['cyan', 'magenta', 'blue', 'green', 'bright_cyan', 'bright_magenta', 'bright_blue', 'bright_green']
LEVEL_COLORS = {'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'red'}

def _tail_drivers(names, nlines, source, clients):
    """
    Get the end of the logs of the drivers, from the daemons of their hosts. The daemon
    clients are kept in `clients` ({ip: client}), to be used again.

    Returns ({driver: result of the daemon tail call}, {driver: problem}).
    """
    by_host = {}
    for name in names:
        by_host.setdefault(lab_info['device_addresses'][name][0], []).append(name)

    results, problems = {}, {}
    for ip, host_drivers in by_host.items():
        if ip not in clients:
            try:
                clients[ip] = _connect_daemon(ip)
            except click.UsageError as e:
                problems.update({name: e.message for name in host_drivers})
                continue
        for name in host_drivers:
            try:
                results[name] = clients[ip].tail(lab=lab_info['module'], driver=name, n=nlines, source=source)
            except (RuntimeError, ValueError) as e:
                # Only the first line: the rest is the remote traceback
                problems[name] = str(e).splitlines()[0]
            except (EOFError, OSError):
                # Connection lost (e.g. the daemon restarted): connect again next time
                clients.pop(ip).disconnect()
                problems.update({name: f'Connection to the daemon on host {_host_name(ip)} lost.'
                                 for name in host_drivers if name not in results})
                break
    return results, problems

def _filter_level(entries, min_level):
    """
    The log entries at min_level or above (all entries if min_level is None).
    """
    if min_level is None:
        return entries
    return [e for e in entries if e.level is not None and logs.level_number(e.level) >= min_level]

def _echo_entry(driver, entry, width, color, raw):
    """
    Print an entry of a merged log: in compact form (time, driver, level, logger if it is
    not the driver itself, message), or its original lines after the driver name (raw).
    """
    label = click.style(f'{driver:<{width}}', fg=color)
    if raw:
        click.echo(f'{label}  {entry.lines[0]}')
    else:
        if entry.time is None:
            time_text = ' ' * 12
        else:
            time_text = datetime.datetime.fromtimestamp(entry.time).strftime('%H:%M:%S.%f')[:-3]
        level_text = click.style(f'{entry.level or "":<8}', fg=LEVEL_COLORS.get(entry.level))
        logger_text = f'[{entry.name}] ' if entry.name not in (None, driver) else ''
        click.echo(f'{time_text}  {label}  {level_text} {logger_text}{entry.message}')

    # e.g. a traceback
    _echo_continuation(entry.lines[1:], width, raw)

def _echo_continuation(lines, width, raw):
    """
    Print the continuation lines of an entry of a merged log (e.g. a traceback), indented.
    """
    indent = ' ' * (width + 2 if raw else 12 + 2 + width + 2 + 9)
    for line in lines:
        click.echo(indent + line)

# Follow mode: interval (in seconds) between two reads of the logs, and lines read per driver
FOLLOW_INTERVAL = 2.
FOLLOW_LINES = 500

def _show_logs(names, nlines, min_level, source, raw, follow, expect_never_started):
    """
    Show the end of the logs of the drivers: the original lines for one driver, merged by
    time for several. With follow, keep showing the new entries, read every FOLLOW_INTERVAL
    seconds, until Ctrl-C. With expect_never_started, drivers never started by the daemon of
    their host are not reported.
    """
    single = len(names) == 1
    width = max(len(name) for name in names)
    colors = {name: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, name in enumerate(names)}
    clients = {}
    follower = logs.LogFollower()
    reported = {}

    def show(name, entry, added_lines=None):
        """
        Print an entry, or only the lines added to it since it was shown.
        """
        if single:
            click.echo('\n'.join(entry.lines if added_lines is None else added_lines))
        elif added_lines is None:
            _echo_entry(name, entry, width, colors[name], raw)
        else:
            _echo_continuation(added_lines, width, raw)

    def read_and_show(n, first):
        results, problems = _tail_drivers(names, n, source, clients)

        # One driver: its original lines, after a header
        if first and single:
            name = names[0]
            if name in problems:
                raise click.ClickException(problems[name])
            result = results[name]
            ip = lab_info['device_addresses'][name][0]
            kind = 'log file' if result['source'] == 'log' else 'process output'
            click.secho(f'--- {name} {kind}: {result["path"]} (on {_host_name(ip)}) ---', fg='blue')

        # Several drivers: the new entries, merged by time
        new = {}
        for name, result in results.items():
            added, entries, complete = follower.new_entries(name, logs.parse_log_lines(result['lines']))
            if not complete:
                click.secho(f'[{name}: lines may have been skipped]', fg='yellow')
            if added is not None and _filter_level([added[0]], min_level):
                show(name, *added)
            new[name] = _filter_level(entries, min_level)
        for name, entry in logs.merge_log_entries(new):
            show(name, entry)

        # Drivers whose log cannot be read, grouped by reason, reported once
        by_problem = {}
        for name, problem in problems.items():
            if reported.get(name) != problem and not (expect_never_started and 'never started' in problem):
                by_problem.setdefault(problem, []).append(name)
        reported.clear()
        reported.update(problems)
        for problem, drivers in by_problem.items():
            click.secho(f'{", ".join(drivers)}: {problem}', fg='yellow', err=True)

    try:
        read_and_show(nlines, first=True)
        while follow:
            time.sleep(FOLLOW_INTERVAL)
            read_and_show(FOLLOW_LINES, first=False)
    except KeyboardInterrupt:
        pass
    finally:
        for client in clients.values():
            client.disconnect()

@cli.command(name='statusall', help=f'Follow the status reported by all the drivers, refreshed every '
                                    f'{STATUS_INTERVAL:g} s until Ctrl-C (like "status --all -f").')
def statusall_cmd():
    _show_statuses(tuple(lab_info['device_addresses']), follow=True)

@cli.command(name='log', help='Show the end of the log of the drivers [names], from the daemons of their '
                              'host. The logs of several drivers are merged by time.')
@click.argument('names', nargs=-1)
@click.option('-n', 'nlines', default=50, show_default=True, help='Number of lines read per driver.')
@click.option('--all', 'all_drivers', is_flag=True, help='All the drivers of the lab.')
@click.option('--level', default=None, help='Only the entries at this level or above (e.g. WARNING).')
@click.option('--out', 'output', is_flag=True, help='Show the process output (stdout and stderr) instead of the log file.')
@click.option('--raw', is_flag=True, help='Merged logs: show the original lines instead of the compact form.')
@click.option('--follow', '-f', is_flag=True, help='Keep showing the new entries, until Ctrl-C.')
def log_cmd(names, nlines, all_drivers, level, output, raw, follow):
    if all_drivers == bool(names):
        raise click.UsageError('Give driver names, or --all.')
    if all_drivers:
        names = tuple(lab_info['device_addresses'])
    for name in names:
        if name not in lab_info['device_addresses']:
            raise click.BadParameter(f'Unknown driver {name}.')
    min_level = None if level is None else _parse_level(level)
    _show_logs(names, nlines, min_level, 'out' if output else None, raw, follow,
               expect_never_started=all_drivers)

@cli.command(name='logall', help='Follow the logs of all the drivers, merged by time, until Ctrl-C '
                                 '(like "log --all -f").')
@click.option('-n', 'nlines', default=20, show_default=True, help='Number of lines read first per driver.')
@click.option('--level', default=None, help='Only the entries at this level or above (e.g. WARNING).')
@click.option('--raw', is_flag=True, help='Show the original lines instead of the compact form.')
def logall_cmd(nlines, level, raw):
    min_level = None if level is None else _parse_level(level)
    _show_logs(tuple(lab_info['device_addresses']), nlines, min_level, None, raw, True,
               expect_never_started=True)

def _driver_client(name):
    """
    A client to the driver, without admin rights (None if it cannot be reached).
    Call with logging muted: connection errors are logged.
    """
    # Only warnings and errors from the client
    rootlogger.getChild(_driver_classes[name].Client.LOGGER_NAME).setLevel(logging.WARNING)
    return client_or_None(name, admin=False, client_name=f'loglevel-{lab_info["this_host"]}')

def _echo_log_levels():
    """
    Print the log level of all the drivers that can be reached.
    """
    def driver_level(name):
        client = _driver_client(name)
        if client is None:
            return '-'
        try:
            return client.get_log_level()
        except Exception:
            # e.g. a driver running an older version of lclib
            return '?'
        finally:
            client.disconnect()

    # In parallel: unreachable hosts take seconds to time out
    names = lab_info['device_addresses']
    with logging_muted(), concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        levels = dict(zip(names, pool.map(driver_level, names)))

    click.echo(f'{"Driver":<20}{"Host":<12}Level')
    for name, address in names.items():
        click.echo(f'{name:<20}{_host_name(address[0]):<12}{levels[name]}')
    if '-' in levels.values():
        click.echo('\n-: not reachable (not running?)')
    if '?' in levels.values():
        click.echo('?: level unknown (driver running an older version of lclib?)')

@cli.command(name='loglevel', help='Show or set the log level of driver [name] (or of its proxy server, with '
                                   '[name].proxy). Without name: the level of all reachable drivers.')
@click.argument('name', required=False)
@click.argument('level', required=False)
@click.option('--save', is_flag=True, help='Keep the driver level for its next starts.')
def loglevel_cmd(name, level, save):
    if name is None:
        _echo_log_levels()
        return

    # The driver itself, or its proxy server (power users)
    driver, part = name, 'driver'
    if name.endswith('.proxy'):
        driver, part = name[:-len('.proxy')], 'proxy'
    if driver not in lab_info['device_addresses']:
        raise click.BadParameter(f'Unknown driver {driver}.')
    if level is not None:
        level = _parse_level(level)
    elif save:
        raise click.UsageError('--save needs a level.')

    with logging_muted():
        client = _driver_client(driver)
    if client is None:
        raise click.ClickException(f'Cannot reach driver {driver} (is it running?).')
    try:
        if level is None:
            level_name = client.get_log_level(part)
        else:
            level_name = client.set_log_level(level, part, save)
    except (AttributeError, TypeError):
        # Older drivers have no get_log_level, and a set_log_level with another signature
        raise click.ClickException(f'Driver {driver} runs an older version of lclib: restart it.')
    except ValueError as e:
        # Only the first line: the rest is the remote traceback
        raise click.ClickException(str(e).splitlines()[0])
    click.echo(f'{name}: {level_name}' + (' (saved)' if save else ''))

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

    ll = _parse_level(loglevel)

    v = Vclass(address=addr, max_fps=maxfps, camera_name=name)
    v.logger.setLevel(ll)
    v.start()
    sys.exit(0)


if __name__ == "__main__":
    cli()