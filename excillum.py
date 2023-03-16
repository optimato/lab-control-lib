"""
Deriver to access and change the state of the Excillum source.

Rough history:
First version: Leo 2018
Current version Pierre 2022
"""
import time

from . import register_proxy_client
from .base import SocketDriverBase
from .network_conf import EXCILLUM as NET_INFO
from .util.uitools import ask_yes_no
from .util.proxydevice import proxydevice, proxycall
from .datalogger import datalogger

logtags = {'type': 'source',
           'branch': 'both',
           'device_ip': NET_INFO['device'][0],
           'device_port': NET_INFO['device'][1]
          }

EOL = b'\n'

def try_float(value):
    """
    Convert to float if possible
    """
    try:
        return float(value)
    except ValueError:
        return value


def float_or_None(value):
    """
    Convert value to None if not float for storage into influxdb.
    """
    try:
        return float(value)
    except ValueError:
        return None


@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class Excillum(SocketDriverBase):
    """
    Excillum Driver.
    """

    DEFAULT_DEVICE_ADDRESS = NET_INFO['device']
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    EOL = EOL
    KEEPALIVE_INTERVAL = 60

    def __init__(self, device_address=None):
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS

        super().__init__(device_address=device_address)
        self.metacalls.update({'state': lambda: self.state,
                               'jet_is_stable': lambda: self.jet_is_stable,
                               'jet_pump_frequency': lambda: self.jetpump_frequency,
                               'generator_high_voltage': lambda: self.generator_high_voltage,
                               'generator_emission_power_w': lambda: self.generator_emission_power_w,
                               'generator_emission_current_a': lambda: self.generator_emission_current_a,
                               'spotsize_x_um': lambda: self.spotsize_x_um,
                               'spotsize_y_um': lambda: self.spotsize_y_um,
                               'spot_position_x_um': lambda: self.spot_position_x_um,
                               'spot_position_y_um': lambda: self.spot_position_y_um,
                               'vacuum_pressure_mbar': lambda: self.vacuum_pressure_mbar,
                               })

        # Start periodic calls
        self.periodic_calls.update({'status': (self.status, 20)})
        self.start_periodic_calls()

    def init_device(self):
        """
        Device initialization.
        """
        # ask for firmware version to see if connection works
        version = self.send_cmd(b'#version')
        self.logger.info(f'Firmware version is {version}')

        self.send_cmd(b'#admin', b'state?')

        # Announce current state
        state = self.get_state()
        self.logger.info(f'Source state: {state}')

        self.initialized = True
        return

    @proxycall()
    @datalogger.meta(field_name='status', tags=logtags)
    def status(self):
        """
        Wrapper method used to retrieve the general status of the source.

        Used mostly for automated data logging.
        """
        status = {'jet_pump_frequency': float_or_None(self.jetpump_frequency),
                  'generator_high_voltage': float_or_None(self.generator_high_voltage),
                  'generator_emission_power_w': float_or_None(self.generator_emission_power_w),
                  'generator_emission_current_a': float_or_None(self.generator_emission_current_a),
                  'spotsize_x_um': float_or_None(self.spotsize_x_um),
                  'spotsize_y_um': float_or_None(self.spotsize_y_um),
                  'spot_position_x_um': float_or_None(self.spot_position_x_um),
                  'spot_position_y_um': float_or_None(self.spot_position_y_um),
                  'vacuum_pressure_mbar': float_or_None(self.vacuum_pressure_mbar),
                  'jet_pressure': float_or_None(self.jet_pressure),
                  }
        return status

    @proxycall(admin=True)
    def send_cmd(self, cmd, replycmd=None):
        """
        Send properly formatted request to the driver
        and parse the reply.

        if replycmd is not None, cmd and replycmd are sent
        one after the other. This is a simple way to deal with
        'cmd' that do not return anything.

        cmd and replycmd should not include the EOL (\\n)
        """
        # Convert to bytes
        try:
            cmd = cmd.encode()
            replycmd = replycmd.encode()
        except AttributeError:
            pass

        # Format arguments
        cmd += self.EOL
        if replycmd is not None:
            cmd += replycmd + self.EOL

        reply = self.device_cmd(cmd)

        self.logger.debug(f'Sent: "{cmd}"')
        self.logger.debug(f'Received: "{reply}"')

        return reply.strip(self.EOL).decode('utf-8', errors='ignore')

    @proxycall(admin=True)
    def source_admin(self):
        """
        Request the admin status for source control.
        Needed for many commands, but should still be
        used as little as possible.
        """
        return self.send_cmd('#admin', '#whoami')

    @proxycall()
    @datalogger.meta(field_name="state", tags=logtags)
    def get_state(self):
        """
        Get source state.
        """
        return self.send_cmd('state?').strip("'")

    @proxycall(admin=True, block=False)
    def set_state(self, target_state, blocking=True):
        """
        Set the source state.

        If blocking is false, return without waiting for state change
        completion.
        """
        current_state = self.get_state()
        if current_state == target_state:
            self.logger.info(f'Already in state "{current_state}"')
            return

        if current_state.endswith("..."):
            # This means that the source is still in the process
            # of reaching the state
            current_state = current_state.strip('.')
            if current_state == target_state:
                self.logger.info(f'Already going to state "{target_state}"')
                return
            if ask_yes_no('Source is busy. Override?', yes_is_default=True):
                self.logger.info(f'Aborting "{current_state}..."')
            else:
                self.logger.info(f'Not changing state from "{current_state}..." to "{target_state}"')
                return

        self.logger.warning(f'Going from "{current_state}" to "{target_state}"')

        # Send command
        cmd = f'state={target_state}'
        reply = self.send_cmd(cmd)

        # Wait for completion
        # This can go through multiple states
        new_state = current_state + ""
        while reply.endswith("..."):
            reply = self.get_state()
            if reply.startswith("error"):
                raise RuntimeError(reply)
            if new_state != reply:
                self.logger.info(f'Going from "{new_state}" to "{reply}"')
                new_state = reply
                print(current_state)
            if not blocking:
                return
            time.sleep(1)

        self.logger.info(f'Source state: "{reply}"')

    @proxycall(admin=True)
    @property
    def state(self):
        return self.get_state()

    @state.setter
    def state(self, target_state):
        self.set_state(target_state)

    @proxycall(admin=True)
    @property
    #@datalogger.meta(field_name="spotsize_x_um", tags=logtags)
    def spotsize_x_um(self):
        """
        Source spot size along x in microns.
        """
        return try_float(self.send_cmd("spotsize_x_um?"))

    @spotsize_x_um.setter
    def spotsize_x_um(self, value):
        value = float(value)
        self.send_cmd(f"spotsize_x_um={value}")

    @proxycall(admin=True)
    @property
    #@datalogger.meta(field_name="spotsize_x_um", tags=logtags)
    def spotsize_y_um(self):
        """
        Source spot size along y in microns.
        """
        return try_float(self.send_cmd("spotsize_y_um?"))

    @spotsize_y_um.setter
    def spotsize_y_um(self, value):
        value = float(value)
        self.send_cmd(f"spotsize_y_um={value}")

    @proxycall(admin=True)
    @property
    def generator_emission_current_a(self):
        return try_float(self.send_cmd("generator_emission_current?"))

    @generator_emission_current_a.setter
    def generator_emission_current_a(self, value):
        value = float(value)
        self.send_cmd(f"generator_emission_current={value}")

    @proxycall(admin=True)
    @property
    def generator_emission_power_w(self):
        return try_float(self.send_cmd("generator_emission_power?"))

    @generator_emission_power_w.setter
    def generator_emission_power_w(self, value):
        value = float(value)
        self.send_cmd(f"generator_emission_power={value}")

    @proxycall(admin=True)
    @property
    def generator_high_voltage(self):
        return try_float(self.send_cmd("generator_high_voltage?"))

    @generator_high_voltage.setter
    def generator_high_voltage(self, value):
        value=float(value)
        self.send_cmd(f"generator_high_voltage={value}")

    @proxycall()
    @property
    def vacuum_pressure_mbar(self):
        return try_float(self.send_cmd("vacuum_pressure_mbar_short_average?"))

    @property
    def jet_pressure_pa(self):
        return try_float(self.send_cmd("jet_pressure_average?"))

    @proxycall()
    @property
    def spot_position_x_um(self):
        """
        Spot position in x (microns)
        """
        return try_float(self.send_cmd("spot_position_x_um?"))

    @proxycall()
    @property
    def spot_position_y_um(self):
        """
        Spot position in y (microns)
        """
        return try_float(self.send_cmd("spot_position_y_um?"))

    @proxycall()
    @property
    def jetpump_frequency(self):
        """
        Jet pump frequency (in Hz)
        """
        return try_float(self.send_cmd('jetpump_frequency?'))

    @proxycall()
    @property
    def jet_is_stable(self):
        """
        Check if the jet is stable
        """
        return self.send_cmd('jet_is_stable?')

    @proxycall()
    @property
    def jet_pressure(self):
        """
        Jet pressure TODO: units?
        """
        return try_float(self.send_cmd('jet_pressure?'))
