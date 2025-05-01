"""
Driver control panel based on NiceGUI
"""

from .. import get_config, _driver_classes, client_or_None, DAEMON_PORT
from ..daemon import daemon_client
import time

run = None
ui = None
monitor = None

class GridRow:
    """
    Class representing a row in a grid.
    """

    def __init__(self, device_info):
        self.name = device_info['name']
        self.labname = device_info['labname']
        self.daemon = device_info['daemon']
        self.hostname = device_info['hostname']
        self.state = None
        self.startup_time = None
        self.client = client_or_None(self.name, keep_trying=True, client_name='driver_control_panel')
        self.client.logger.setLevel(50)
        self.host_label = ui.label(self.hostname).classes('text-lg')
        self.name_label = ui.label(self.name).classes('text-lg')
        self.uptime_label = ui.label('Uptime: 0.0 h').classes('text-lg')
        self.status_label = ui.label('UNKOWN').classes('text-lg')
        self.start_stop_button = ui.button(icon='play_arrow', on_click=self.toggle_state).props('round dense').classes('shadow-xs')

    def update_state(self):
        """
        Update the state of the device.
        """
        # Check through direct client
        alive = self.client.connected
 
        if alive:
            try:
                self.startup_time = self.client.server_startup_time
            except Exception as e:
                print(f'Failed to get startup time for {self.name}: {e}')
                self.startup_time = None

        # Check if the daemon is running
        if self.daemon is None or not self.daemon.connected:
            managed = False
        else:
            running = self.daemon.running()
            if f'{self.labname}_{self.name}' in running:
                managed = True
            else:
                managed = False
        self.state = [['OFFLINE', 'NOT RESPONDING'], ['UNMANAGED', 'ONLINE']][alive][managed] 
        self.update_style()

    def toggle_state(self, e):
        """
        Toggle the state of the device.
        """
        if  self.state == 'OFFLINE':
            self.start()
        else:
            print('here')
            with ui.dialog() as dialog, ui.card():
                ui.label(f'Shutdown driver {self.name} on {self.hostname}?')
                ui.button('Yes', on_click=lambda e: (dialog.close(), self.shutdown()))
                ui.button('No', on_click=dialog.close)
            dialog.open()
    
    def start(self):
        """
        Start the device.
        """
        # Check if the daemon is running
        if self.daemon is None:
            ui.notify(f'Daemon on {self.hostname} is not running.')
            return

        # Start the driver
        try:
            self.daemon.start(lab=self.labname, driver=self.name)
            self.state = 'ONLINE'
            self.update_style()
            ui.notify(f'Started driver {self.name} on {self.hostname}.')
        except Exception as e:
            ui.notify(f'Failed to start driver {self.name} on {self.hostname}: {e}')

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
        if self.state == 'ONLINE':
            self.status_label.classes(remove='text-black text-red-600 text-orange-600').classes('text-green-600').set_text('ONLINE')
            self.start_stop_button.props('color=red-600 icon=stop')
        elif self.state == 'OFFLINE':
            self.status_label.classes(remove='text-green-600 text-red-600 text-orange-600').classes('text-black').set_text('OFFLINE')
            self.start_stop_button.props('color=green-600 icon=play_arrow')
        elif self.state == 'NOT RESPONDING':
            self.status_label.classes(remove='text-green-600 text-black text-orange-600').classes('text-red-600').set_text('NOT RESPONDING')
            self.start_stop_button.props('color=red-600 icon=stop')
        else:
            self.status_label.classes(remove='text-green-600 text-black text-red-600').classes('text-orange-600').set_text('UNMANAGED')
            self.start_stop_button.props('color=red-600 icon=stop')

    def shutdown(self):
        """
        Shutdown the device.
        """
        # Shutdown the driver using a direct client
        try:
            if self.client.connected:
                # Ask the driver to shut down
                self.client.ask_admin(True, True)
                self.client.kill_server()
                # Create a new client ready for the next start
                self.client = client_or_None(self.name, keep_trying=True, client_name='driver_control_panel')
                self.client.logger.setLevel(50)
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
            with ui.grid(columns='80px 120px 1fr auto auto').classes('w-full gap-2'):
                ui.label('Host').classes('text-lg font-bold text-left')
                ui.label('Driver').classes('text-lg font-bold text-left')
                ui.label('Uptime').classes('text-lg font-bold text-left')
                ui.label('Status').classes('text-lg font-bold text-left')
                ui.label('Action').classes('text-lg font-bold text-left')
            sep = ui.separator().classes('w-full h-1 bg-slate-200')  # Add a separator

            # Sort by host
            for host_name, address in self.host_list:
                for driver_name, info in self.device_info.items():
                    if info['address'] == address:
                        with ui.grid(columns='80px 120px 1fr auto auto').classes('w-full gap-2'):
                            self.entries.append(GridRow(self.device_info[driver_name]))
                        sep = ui.separator().classes('w-full h-1 bg-slate-200')  # Add a separator
        sep.set_visibility(False)

    def start_all_drivers(self, e):
        """Start all drivers."""
        for entry in self.entries:
            if entry.state == 'OFFLINE':
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
            if entry.state == 'OFFLINE':
                entry.start()

    def update_state(self):
        """Update the state of the UI."""
        self.spinner.classes(remove='hidden')
        #for card in self.driver_cards:

        for entry in self.entries:
            entry.update_state()
        self.spinner.classes(add='hidden')

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
