"""
Driver control panel based on NiceGUI
"""

from .. import get_config, _driver_classes, client_or_None, DAEMON_PORT, logs
from ..daemon import daemon_client, API_VERSION
import copy
import datetime
import logging
import time

run = None
ui = None
monitor = None

class LogPanel:
    """
    Side panel showing the logs of the selected drivers, merged by time and updated live.
    """

    INTERVAL = 2.         # Time (in seconds) between two reads of the logs
    FIRST_LINES = 50      # Lines shown first when a driver is selected
    LINES = 500           # Lines read per driver at the next reads
    MAX_LINES = 2000      # Lines kept in the panel

    # Line colors for the levels
    LEVEL_CLASSES = {'WARNING': 'text-orange-600', 'ERROR': 'text-red-600', 'CRITICAL': 'text-red-600'}

    def __init__(self, labname, daemons, driver_names):
        """
        labname: the lab package name
        daemons: the daemon client of each host ({host: client})
        driver_names: the names of all the drivers (to align the lines)
        """
        self.labname = labname
        self.daemons = daemons
        self.width = max(len(name) for name in driver_names) if driver_names else 0
        self.selected = {}          # {driver: host}
        self.follower = logs.LogFollower()
        self.reported = {}          # Problems already shown {driver: problem}
        self.paused = False

        with ui.column().classes('w-full h-full gap-1 p-2'):
            with ui.row().classes('w-full items-center gap-2'):
                ui.label('Logs').classes('text-xl font-bold')
                ui.space()
                self.level_select = ui.select(['DEBUG', 'INFO', 'WARNING', 'ERROR'], value='DEBUG',
                                              label='Level').props('dense').classes('w-28')
                self.pause_button = ui.button('Pause', icon='pause', on_click=self.toggle_pause).props('flat dense')
                ui.button('Clear', icon='clear_all', on_click=lambda: self.log.clear()).props('flat dense')
            self.log = ui.log(max_lines=self.MAX_LINES).classes('w-full h-[80vh] text-xs')
            self.log.push('Check drivers to follow their logs here.', classes='text-gray-500')
        ui.timer(self.INTERVAL, self.update)

    def select(self, driver, host, selected):
        """
        Start or stop following the log of a driver.
        """
        if selected:
            self.selected[driver] = host
        else:
            self.selected.pop(driver, None)
            # If selected again, start again from its last lines
            self.follower.last.pop(driver, None)
            self.reported.pop(driver, None)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.set_text('Resume' if self.paused else 'Pause')
        self.pause_button.props(f'icon={"play_arrow" if self.paused else "pause"}')

    def _read(self, selected):
        """
        Read the end of the logs of the selected drivers from their daemons (runs on a thread).

        Returns ({driver: lines}, {driver: problem}).
        """
        lines, problems = {}, {}
        for driver, host in selected.items():
            daemon = self.daemons.get(host)
            if daemon is None or not daemon.connected:
                problems[driver] = f'Daemon on {host} not reachable.'
                continue
            n = self.LINES if driver in self.follower.last else self.FIRST_LINES
            try:
                lines[driver] = daemon.tail(self.labname, driver, n)['lines']
            except Exception as e:
                # Only the first line: the rest is the remote traceback
                problems[driver] = str(e).splitlines()[0]
        return lines, problems

    async def update(self):
        """
        Show the new entries of the logs of the selected drivers, merged by time.
        """
        if self.paused or not self.selected:
            return
        lines, problems = await run.io_bound(self._read, dict(self.selected))

        min_level = logs.level_number(self.level_select.value)
        def shown(entry):
            if min_level <= logging.DEBUG:
                return True
            return entry.level is not None and logs.level_number(entry.level) >= min_level

        new = {}
        for driver, driver_lines in lines.items():
            if driver not in self.selected:
                # Unselected in the meantime
                continue
            first = driver not in self.follower.last
            added, entries, complete = self.follower.new_entries(driver, logs.parse_log_lines(driver_lines))
            if first:
                self.log.push(f'--- {driver}: last lines ---', classes='text-gray-500')
            elif not complete:
                self.log.push(f'--- {driver}: lines may have been skipped ---', classes='text-orange-600')
            if added is not None and shown(added[0]):
                self._push(driver, *added)
            new[driver] = [entry for entry in entries if shown(entry)]
        for driver, entry in logs.merge_log_entries(new):
            self._push(driver, entry)

        # Drivers whose log cannot be read, shown once (and again if the problem changes)
        for driver, problem in problems.items():
            if self.reported.get(driver) != problem:
                self.log.push(f'--- {driver}: {problem} ---', classes='text-orange-600')
        self.reported = problems

    def _push(self, driver, entry, added_lines=None):
        """
        Add an entry to the panel, in the same compact form as `lc log` (or only the lines
        added to an entry already shown).
        """
        classes = self.LEVEL_CLASSES.get(entry.level, '')
        if added_lines is None:
            if entry.time is None:
                time_text = ' ' * 12
            else:
                time_text = datetime.datetime.fromtimestamp(entry.time).strftime('%H:%M:%S.%f')[:-3]
            logger_text = f'[{entry.name}] ' if entry.name not in (None, driver) else ''
            self.log.push(f'{time_text}  {driver:<{self.width}}  {entry.level or "":<8} {logger_text}{entry.message}',
                          classes=classes)
            added_lines = entry.lines[1:]

        # e.g. a traceback
        indent = ' ' * (12 + 2 + self.width + 2 + 9)
        for line in added_lines:
            self.log.push(indent + line, classes=classes)

class GridRow:
    """
    Class representing a row in a grid.
    """

    # Status label color, and visibility of the start and stop buttons, for each state
    STYLES = {'ONLINE': ('text-green-600', False, True),
              'STARTING': ('text-blue-600', False, True),
              'NOT RESPONDING': ('text-red-600', False, True),
              'UNMANAGED': ('text-orange-600', False, True),
              'FAILED': ('text-red-600', True, False),
              'STOPPING': ('text-gray-600', False, False),
              'OFFLINE': ('text-black', True, False),
              'NO DAEMON': ('text-gray-600', False, False),
              'OLD DAEMON': ('text-red-600', False, False)}

    # Time (in seconds) given to the client to connect to a driver that just became ready
    CONNECT_GRACE = 5.

    # Number of lines shown in the log dialog
    LOG_LINES = 200

    def __init__(self, device_info, log_panel):
        self.device_info = device_info
        self.log_panel = log_panel
        self.name = device_info['name']
        self.labname = device_info['labname']
        self.daemon = device_info['daemon']
        self.hostname = device_info['hostname']
        self.state = None
        self.startup_time = None
        self.unreachable_since = None
        # Why the daemon of the host cannot be used: (state, explanation), or None
        self.daemon_problem = None
        if device_info.get('client') is None:
            self.client = client_or_None(self.name, keep_trying=True, client_name='driver_control_panel')
            self.client.logger.setLevel(50)
        self.host_label = ui.label(self.hostname).classes('text-lg')
        self.name_label = ui.label(self.name).classes('text-lg cursor-pointer hover:underline').on('click', self.show_log)
        self.name_label.tooltip('End of its log')
        self.uptime_label = ui.label('Uptime: 0.0 h').classes('text-lg')
        self.status_label = ui.label('UNKNOWN').classes('text-lg')
        with self.status_label:
            # Shows the error of a failed driver
            self.status_tooltip = ui.tooltip('')
        self.status_tooltip.set_visibility(False)
        self.log_checkbox = ui.checkbox(on_change=lambda e: self.log_panel.select(self.name, self.hostname, e.value))
        self.log_checkbox.tooltip('Follow its log in the side panel')
        self.start_button = ui.button(icon='play_arrow', on_click=self.start).props('round dense color=green-600').classes('shadow-xs')
        self.stop_button = ui.button(icon='stop', on_click=self.shutdown).props('round dense color=red-600').classes('shadow-xs')

    @property
    def client(self):
        """
        The client to the driver, shared by the pages of all the browsers.
        """
        return self.device_info['client']

    @client.setter
    def client(self, client):
        self.device_info['client'] = client

    def update_state(self, daemon_status=None, daemon_problem=None):
        """
        Update the state of the device.

        daemon_status: the status of this driver according to the daemon of its host
                       (None if the daemon is not available or does not manage the driver)
        daemon_problem: why the daemon of the host cannot be used, as (state, explanation),
                        or None
        """
        self.daemon_problem = daemon_problem

        # Check through direct client
        alive = self.client.connected
 
        if alive:
            try:
                self.startup_time = self.client.server_startup_time
            except Exception as e:
                print(f'Failed to get startup time for {self.name}: {e}')
                self.startup_time = None

        # Combine with what the daemon knows about the driver process
        daemon_state = daemon_status['state'] if daemon_status else None

        # Since when the daemon reports the driver as ready but the client cannot reach it
        if alive or daemon_state != 'running':
            self.unreachable_since = None
        elif self.unreachable_since is None:
            self.unreachable_since = time.time()

        if daemon_state == 'stopping':
            self.state = 'STOPPING'
        elif alive:
            # Managed: started by the daemon. Unmanaged: started by hand (lstart)
            self.state = 'ONLINE' if daemon_state in ('starting', 'running') else 'UNMANAGED'
        elif daemon_problem is not None:
            self.state = daemon_problem[0]
        elif daemon_state == 'starting':
            self.state = 'STARTING'
        elif daemon_state == 'running':
            if time.time() - self.unreachable_since < self.CONNECT_GRACE:
                self.state = 'STARTING'
            else:
                self.state = 'NOT RESPONDING'
        elif daemon_state == 'exited' and daemon_status['failed']:
            self.state = 'FAILED'
        else:
            self.state = 'OFFLINE'

        # Tooltip: the last line of the output of a failed driver (usually the exception),
        # or why the daemon cannot be used
        tooltip = ''
        if self.state == 'FAILED':
            lines = [line for line in daemon_status['error_tail'] or [] if line.strip()]
            tooltip = lines[-1] if lines else ''
        elif daemon_problem is not None:
            tooltip = daemon_problem[1]
        self.status_tooltip.set_text(tooltip)
        self.status_tooltip.set_visibility(bool(tooltip))

        self.update_style()
    
    def start(self):
        """
        Start the device.
        """
        # Check that the daemon can be used
        if self.daemon is None or not self.daemon.connected:
            ui.notify(f'Daemon on {self.hostname} is not running.')
            return
        if self.daemon_problem is not None:
            ui.notify(self.daemon_problem[1])
            return

        # Start the driver. The daemon returns immediately: the startup is then
        # followed by update_state.
        try:
            self.daemon.start(lab=self.labname, driver=self.name)
        except Exception as e:
            # Only the first line: the rest is the remote traceback
            ui.notify(f'Failed to start driver {self.name} on {self.hostname}: {str(e).splitlines()[0]}')
            return
        self.state = 'STARTING'
        self.update_style()
        ui.notify(f'Starting driver {self.name} on {self.hostname}.')

    def update_style(self):
        """
        Update the style of the device row based on its state.
        """
        if self.startup_time is not None:
            uptime = time.time() - self.startup_time
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            seconds = uptime % 60
            self.uptime_label.set_text(f'Uptime: {int(hours)}:{int(minutes):02}:{int(seconds):02}')
        else:
            self.uptime_label.set_text("Uptime: N/A")
        
        # Update status label and button visibility based on state
        state = self.state if self.state in self.STYLES else 'UNMANAGED'
        color, show_start, show_stop = self.STYLES[state]
        all_colors = ' '.join({c for c, _, _ in self.STYLES.values()})
        self.status_label.classes(remove=all_colors).classes(color).set_text(state)
        self.start_button.set_visibility(show_start)
        self.stop_button.set_visibility(show_stop)

    async def show_log(self):
        """
        Show the end of the driver log (or of its process output), fetched from the daemon.
        """
        if self.daemon is None or not self.daemon.connected:
            ui.notify(f'Daemon on {self.hostname} is not running.')
            return
        if self.daemon_problem is not None:
            ui.notify(self.daemon_problem[1])
            return

        # Default source: the log file, or the process output if the driver never became ready
        result = await self._fetch_log(None)
        if result is None:
            return

        def display(result):
            title.set_text(f'{self.name} on {self.hostname}: {result["path"]}')
            log.clear()
            for line in result['lines']:
                log.push(line)

        async def switch_source(e):
            result = await self._fetch_log(e.value)
            if result is not None:
                display(result)

        with ui.dialog() as dialog, ui.card().classes('w-full max-w-[1200px]'):
            title = ui.label().classes('text-lg font-bold')
            log = ui.log().classes('w-full h-[60vh] text-xs')
            with ui.row().classes('w-full justify-end'):
                ui.toggle({'log': 'Log file', 'out': 'Process output'}, value=result['source'],
                          on_change=switch_source)
                ui.button('Close', on_click=dialog.close)
        display(result)

        # Opens the dialog and waits until it is closed
        await dialog
        dialog.delete()

    async def _fetch_log(self, source):
        """
        Get the end of the driver log from the daemon (None if it failed).
        """
        try:
            return await run.io_bound(self.daemon.tail, self.labname, self.name, self.LOG_LINES, source)
        except Exception as e:
            # Only the first line: the rest is the remote traceback
            ui.notify(f'Could not get the log of {self.name}: {str(e).splitlines()[0]}')
            return None

    def shutdown(self):
        """
        Shutdown the device.
        """
        # Show confirmation dialog
        with ui.dialog() as dialog, ui.card():
            ui.label(f'Shutdown driver {self.name} on {self.hostname}?')
            ui.button('Yes', on_click=lambda e: (dialog.close(), self._do_shutdown()))
            ui.button('No', on_click=dialog.close)
        dialog.open()

    def _do_shutdown(self):
        """
        Perform the actual shutdown.
        """
        try:
            if self.client.connected:
                # Ask the driver to shut down
                self.client.ask_admin(True, True)
                self.client.kill_server()
                # Create a new client ready for the next start
                self.client = client_or_None(self.name, keep_trying=True, client_name='driver_control_panel')
                self.client.logger.setLevel(50)
            elif (self.state in ('STARTING', 'NOT RESPONDING') and self.daemon is not None
                  and self.daemon.connected and self.daemon_problem is None):
                # The driver cannot be reached: ask the daemon to stop its process
                self.daemon.kill_process(lab=self.labname, driver=self.name)
            self.state = 'OFFLINE'
            self.startup_time = None
            self.update_style()
            ui.notify(f'Shut down driver {self.name} on {self.hostname}.')
        except Exception as e:
            ui.notify(f'Failed to shut down driver {self.name} on {self.hostname}: {e}')

class DeviceManagerApp:

    def __init__(self):
        """
        Initialize the DeviceManagerApp
        """
        global run, ui
        import nicegui
        from nicegui import run, ui
        nicegui.app.native.start_args['gui'] = 'gtk'#'qt'

        # Get lab configuration
        config = get_config()
        self.labname = config['module']
        host_ips = config['host_ips'].copy()
        control_ip = host_ips.pop('control')
        self.host_list = [('control', control_ip)] + list(host_ips.items())

        # Connect to monitor
        global monitor
        monitor = client_or_None('monitor', keep_trying=True)
        time.sleep(.5)
        if not monitor.connected:
            #raise RuntimeError("Could not connect to monitor.")
            print('[WARNING] Could not connect to monitor.')

        # Connect to host daemons
        self.daemons = {}
        for host, ip in self.host_list:
            try:
                # Create a constantly-trying-to-connect client
                c = daemon_client(address=(ip, DAEMON_PORT), reconnect="always")
                c.logger.setLevel(50)
                self.daemons[host] = c
            except Exception as e:
                print(f'[WARNING] Could not connect to daemon on {host} ({ip}): {e}')
                self.daemons[host] = None

        # Driver addresses
        device_addresses = {name: cls.Server.ADDRESS for name, cls in _driver_classes.items()}

        device_info = {}
        for name, cls in _driver_classes.items():
            # Get the driver address
            address = cls.Server.ADDRESS[0]
            # Get the host name
            hl = [host for host, ip in self.host_list if ip==address]
            hostname = hl[0] if hl else None
            if not hl:
                print(f'Device {name} has host ip {address}, which corresponds to no host')
            # Add to the device info dictionary
            device_info[name] = {'name':name, 
                                 'labname':self.labname,
                                 'hostname':hostname,
                                 'address':address,
                                 'daemon':self.daemons.get(hostname)}

        self.device_info = device_info
        self.entries = []

    def setup_ui(self):
        """
        Set up the UI components.
        """
        self.entries = []
        ui.page_title('Driver control panel')

        # A spinner to show while updating
        self.spinner = ui.spinner(size='lg').classes('absolute top-4 right-4 z-50 hidden')

        # Drivers on the left, logs of the selected drivers on the right
        with ui.splitter(value=50).classes('w-full h-[95vh]') as splitter:
            with splitter.after:
                self.log_panel = LogPanel(self.labname, self.daemons, list(self.device_info))

            with splitter.before:
                with ui.column().classes('w-full flex flex-col gap-2 items-center pr-4'):  # Use a vertical layout
                    self.title_label = ui.label(f'Driver control panel').classes('text-3xl font-bold text-center')
                    self.subtitle_label = ui.label(f'{self.labname}').classes('text-xl font-bold text-center')
                    with ui.row().classes('w-full gap-2 justify-center'):
                        self.start_all = ui.button('Start all', on_click=self.start_all_drivers).classes('text-lg font-bold').props('color=green-600 icon=play_arrow')
                        self.stop_all = ui.button('Stop all', on_click=self.stop_all_drivers).classes('text-lg font-bold').props('color=red-600 icon=stop')
                        self.restart_all = ui.button('Restart all', on_click=self.restart_all_drivers).classes('text-lg font-bold').props('color=orange-600 icon=restart_alt')
                    with ui.grid(columns='80px 120px 1fr auto auto auto').classes('w-full gap-2'):
                        ui.label('Host').classes('text-lg font-bold text-left')
                        ui.label('Driver').classes('text-lg font-bold text-left')
                        ui.label('Uptime').classes('text-lg font-bold text-left')
                        ui.label('Status').classes('text-lg font-bold text-left')
                        ui.label('Log').classes('text-lg font-bold text-left')
                        ui.label('Action').classes('text-lg font-bold text-left')
                    sep = ui.separator().classes('w-full h-1 bg-slate-200')  # Add a separator

                    # Sort by host
                    for host_name, address in self.host_list:
                        for driver_name, info in self.device_info.items():
                            if info['address'] == address:
                                with ui.grid(columns='80px 120px 1fr auto auto auto').classes('w-full gap-2'):
                                    self.entries.append(GridRow(self.device_info[driver_name], self.log_panel))
                                sep = ui.separator().classes('w-full h-1 bg-slate-200')  # Add a separator
                sep.set_visibility(False)

    def start_all_drivers(self, e):
        """Start all drivers."""
        for entry in self.entries:
            if entry.state in ('OFFLINE', 'FAILED'):
                entry.start()

    def stop_all_drivers(self, e):
        """Stop all drivers."""
        for entry in self.entries:
            if entry.state != 'OFFLINE':
                entry.shutdown()

    def restart_all_drivers(self, e):
        """Restart all drivers."""
        for entry in self.entries:
            if entry.state != 'OFFLINE':
                entry.shutdown()
        time.sleep(1)
        self.update_state()
        for entry in self.entries:
            if entry.state in ('OFFLINE', 'FAILED'):
                entry.start()

    def update_state(self):
        """Update the state of the UI."""
        self.spinner.classes(remove='hidden')

        # Status of all the drivers managed by each daemon (one call per host), or the
        # reason why the daemon cannot be used
        statuses, problems = {}, {}
        for host, daemon in self.daemons.items():
            problem = self._daemon_problem(host, daemon)
            if problem is None:
                try:
                    statuses[host] = daemon.status_all()
                except Exception as e:
                    # Only the first line: the rest is the remote traceback
                    problem = ('NO DAEMON', f'Daemon on {host}: {str(e).splitlines()[0]}')
            if problem is not None:
                problems[host] = problem

        for entry in self.entries:
            host_statuses = statuses.get(entry.hostname, {})
            entry.update_state(host_statuses.get(f'{self.labname}_{entry.name}'), problems.get(entry.hostname))
        self.spinner.classes(add='hidden')

    @staticmethod
    def _daemon_problem(host, daemon):
        """
        Why the daemon of the host cannot be used, as (state shown for its drivers,
        explanation), or None if it can.
        """
        if daemon is None or not daemon.connected:
            reason = daemon.connection_error if daemon is not None else None
            return ('NO DAEMON', f'Daemon on {host} not reachable' + (f': {reason}.' if reason else '.'))
        try:
            version = daemon.api_version()
        except AttributeError:
            # Daemon older than the version check
            version = 1
        except Exception as e:
            return ('NO DAEMON', f'Daemon on {host}: {str(e).splitlines()[0]}')
        if version < API_VERSION:
            return ('OLD DAEMON', f'Daemon on {host} too old: update lclib on that host and restart '
                                  f'the daemon (python -m lclib -r).')
        return None

    async def periodic_update(self):
        """Periodically update the state."""
        await run.io_bound(self.update_state)

    def run(self, *args, **kwargs):
        """Run the NiceGUI app."""
        # The UI is built for each browser, in a page function: since NiceGUI 3, a UI built
        # outside of one makes NiceGUI run the whole program again at each visit.
        @ui.page('/')
        def page():
            # Its own rows, log panel and updates; the connections are shared
            panel = copy.copy(self)
            panel.setup_ui()
            ui.timer(1.0, panel.periodic_update)

        ui.run(*args, **kwargs)


# Run the app
if __name__ in {"__main__", "__mp_main__"}:
    app = DeviceManagerApp()
    #app.run(reload=False, native=True, window_size=(750, 1200), fullscreen=False)
    app.run(reload=False)
