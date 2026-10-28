"""
Driver control panel based on NiceGUI
"""

from .. import get_config, _driver_classes, client_or_None, DAEMON_PORT
from ..daemon import daemon_client, API_VERSION
import time

run = None
ui = None
monitor = None

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

    def __init__(self, device_info):
        self.name = device_info['name']
        self.labname = device_info['labname']
        self.daemon = device_info['daemon']
        self.hostname = device_info['hostname']
        self.state = None
        self.startup_time = None
        self.unreachable_since = None
        # Why the daemon of the host cannot be used: (state, explanation), or None
        self.daemon_problem = None
        self.client = client_or_None(self.name, keep_trying=True, client_name='driver_control_panel')
        self.client.logger.setLevel(50)
        self.host_label = ui.label(self.hostname).classes('text-lg')
        self.name_label = ui.label(self.name).classes('text-lg')
        self.uptime_label = ui.label('Uptime: 0.0 h').classes('text-lg')
        self.status_label = ui.label('UNKNOWN').classes('text-lg')
        with self.status_label:
            # Shows the error of a failed driver
            self.status_tooltip = ui.tooltip('')
        self.status_tooltip.set_visibility(False)
        self.log_button = ui.button(icon='article', on_click=self.show_log).props('round dense flat').classes('shadow-xs')
        self.start_button = ui.button(icon='play_arrow', on_click=self.start).props('round dense color=green-600').classes('shadow-xs')
        self.stop_button = ui.button(icon='stop', on_click=self.shutdown).props('round dense color=red-600').classes('shadow-xs')

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
        ui.page_title('Driver control panel')

        # A spinner to show while updating
        self.spinner = ui.spinner(size='lg').classes('absolute top-4 right-4 z-50 hidden')

        with ui.column().classes('w-full flex flex-col max-w-[800px] gap-2 items-center'):  # Use a vertical layout
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
                            self.entries.append(GridRow(self.device_info[driver_name]))
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
        self.setup_ui()
        ui.timer(1.0, self.periodic_update)
        ui.run(*args, **kwargs)


# Run the app
if __name__ in {"__main__", "__mp_main__"}:
    app = DeviceManagerApp()
    #app.run(reload=False, native=True, window_size=(750, 1200), fullscreen=False)
    app.run(reload=False)
