"""
Deriver to access and change the state of the Excillum source.

Rough history:
First version: Leo 2018
Current version Pierre 2022
"""
import time
import sys

from .base import MotorBase, DriverBase, SocketDeviceServerBase, admin_only, emergency_stop, DeviceException
from .network_conf import EXCILLUM as DEFAULT_NETWORK_CONF
from .ui_utils import ask_yes_no

EOL = b'\n'


class ExcillumDaemon(SocketDeviceServerBase):
    """
    Excillyum Daemon, keeping connection with Robot arm.
    """

    DEFAULT_SERVING_ADDRESS = DEFAULT_NETWORK_CONF['DAEMON']
    DEFAULT_DEVICE_ADDRESS = DEFAULT_NETWORK_CONF['DEVICE']
    EOL = EOL
    KEEPALIVE_INTERVAL = 60

    def __init__(self, serving_address=None, device_address=None):
        if serving_address is None:
            serving_address = self.DEFAULT_SERVING_ADDRESS
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS
        super().__init__(serving_address=serving_address, device_address=device_address)

    def init_device(self):
        """
        Device initialization.
        """
        # ask for firmware version to see if connection works
        version = self.device_cmd(b'#version' + self.EOL)
        version = version.decode('utf-8').strip(self.EOL)
        self.logger.debug(f'Firmware version is {version}')

        self.initialized = True
        return

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.device_cmd(b'state?' + self.EOL)
        if not r:
            raise DeviceException


class Excillum(DriverBase):
    """
    Driver for the Excillum liquid-metal-jet source.
    """

    EOL = EOL

    def __init__(self, address=None, admin=True):
        """
        Initialization.
        """
        if address is None:
            address = DEFAULT_NETWORK_CONF['DAEMON']

        super().__init__(address=address, admin=admin)

        state = self.get_state()
        self.logger.info(f'Source state: {state}')


    def send_cmd(self, cmd, replycmd=None):
        """
        Send properly formatted request to the driver
        and parse the reply.
        Replies from the robot are of the various form, so no
        preprocessing is done.

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
        if replycmd is not None:
            cmd += self.EOL + replycmd + self.EOL
        reply = self.send_recv(cmd)
        return reply.strip(self.EOL).decode('utf-8', errors='ignore')

    @admin_only
    def source_admin(self):
        """
        Request the admin status for source control.
        Needed for many commands, but should still be
        used as little as possible.
        """
        return self.send_cmd('#admin', '#whoami')

    def get_state(self):
        """
        Get source state.
        """
        return self.send_cmd('state?').strip("'")

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

    @property
    def state(self):
        return self.get_state()

    @state.setter
    def state(self, target_state):
        self.set_state(target_state)

    @property
    def spotsize_x_um(self):
        return self.send_cmd("spotsize_x_um?")

    @property
    def spotsize_y_um(self):
        return self.send_cmd("spotsize_y_um?")

    @property
    def generator_emission_current_a(self):
        return self.send_cmd("generator_emission_current?")

    @property
    def generator_emission_power_w(self):
        return self.send_cmd("generator_emission_power?")

    @property
    def generator_high_voltage(self):
        return self.send_cmd("generator_high_voltage?")

    @property
    def vacuum_pressure_pa(self):
        return self.send_cmd("vacuum_pressure_mbar_short_average?")

    @property
    def jet_pressure_pa(self):
        return self.send_cmd("jet_pressure_average?")

    @property
    def spot_position_x_um(self):
        return self.send_cmd("spot_position_x_um?")

    @property
    def spot_position_y_um(self):
        return self.send_cmd("spot_position_y_um?")
