"""
Deriver to access and change the state of the Excillum source.

Rough history:
First version: Leo 2018
Current version Pierre 2022
"""
import time

from .base import SocketDriverBase, DeviceException
from .network_conf import HOST_IPS, EXCILLUM as NET_INFO
from .ui_utils import ask_yes_no
from .util.proxydevice import proxydevice, proxycall

EOL = b'\n'


@proxydevice(address=HOST_IPS['control'])
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

    def init_device(self):
        """
        Device initialization.
        """
        # ask for firmware version to see if connection works
        version = self.send_cmd(b'#version')
        self.logger.info(f'Firmware version is {version}')

        # Announce current state
        state = self.get_state()
        self.logger.info(f'Source state: {state}')

        self.initialized = True
        return

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.send_cmd(b'state?')
        if not r:
            raise DeviceException

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

    @proxycall()
    @property
    def spotsize_x_um(self):
        return self.send_cmd("spotsize_x_um?")

    @proxycall()
    @property
    def spotsize_y_um(self):
        return self.send_cmd("spotsize_y_um?")

    @proxycall()
    @property
    def generator_emission_current_a(self):
        return self.send_cmd("generator_emission_current?")

    @proxycall()
    @property
    def generator_emission_power_w(self):
        return self.send_cmd("generator_emission_power?")

    @proxycall()
    @property
    def generator_high_voltage(self):
        return self.send_cmd("generator_high_voltage?")

    @proxycall()
    @property
    def vacuum_pressure_pa(self):
        return self.send_cmd("vacuum_pressure_mbar_short_average?")

    @property
    def jet_pressure_pa(self):
        return self.send_cmd("jet_pressure_average?")

    @proxycall()
    @property
    def spot_position_x_um(self):
        return self.send_cmd("spot_position_x_um?")

    @proxycall()
    @property
    def spot_position_y_um(self):
        return self.send_cmd("spot_position_y_um?")

    @proxycall()
    @property
    def jetpump_frequency(self):
        return self.send_cmd('jetpump_frequency?')
