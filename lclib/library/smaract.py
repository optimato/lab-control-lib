"""
Driver for Smaract piezos via ASCII programming interface over IP/TCP

This driver was written specifically for a three-axis motor (x,y,z) corresponding to channels (0,1,2)

Note on design: using get/set instead of @properties because most methods require a channel number.

A working subclass can be declared as follows:

::
    # Create and register the Smaract subclass, including the default driver address
    # as class attribute
    @register_driver
    @proxydevice(address=smaract_proxy_address)
    class Smaract(SmaractBase):
        DEFAULT_DEVICE_ADDRESS = smaract_driver_address

    # Create one motor. The additional argument `axis` is passed to the constructor
    # and corresponds to the driver channel index.
    @Smaract.register_motor('sx', axis=0)
    class Motor(SmaractMotor)
        pass


This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import time

from .. import proxycall, proxydevice
from ..base import MotorBase, SocketDriverBase, emergency_stop

__all__ = ['SmaractBase', 'SmaractMotor']


EOL = b'\n'

@proxydevice()
class SmaractBase(SocketDriverBase):
    """
    Smaract Driver
    """

    DEFAULT_DEVICE_ADDRESS = None
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    DEFAULT_SPEED = 1000  # um/s
    DEFAULT_ACCEL = 10000  # um/s^2 (!)
    SENSOR_MODES = {0: 'disabled', 1: 'enabled', 2: 'power save'}
    EOL = EOL

    def __init__(self, device_address=None):
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS
        super().__init__(device_address=device_address)

        self.metacalls.update({'position': lambda: [self.get_pos(0), self.get_pos(1), self.get_pos(2)],
                               'speed': lambda: [self.get_speed(0), self.get_speed(1), self.get_speed(2)]})

    def init_device(self):
        """
        Device initialization.
        """
        # Communication mode to 0-synchronous or 1- asyn.
        self.send_cmd(':SCM0')
        self.logger.info('Connection established')

        # Get number of channels
        nc = self.send_cmd(':GNC')
        self.no_channels = int(nc[1][0])
        self.logger.info(f'Number of channels is {self.no_channels}')

        # Set sensor mode to power save
        self.sensormode = 2
        self.initialized = True

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.send_cmd(':GS0')
        if not r:
            raise RuntimeError('Device is not responding.')

    def send_cmd(self, cmd):
        """
        Send command to Smaract device.
        Args:
            cmd (str): Command to send (without EOL)

        Returns: (code, values)
        """
        # Convert to bytes
        if isinstance(cmd, str):
            cmd = cmd.encode()
        cmd += self.EOL

        s = self.device_cmd(cmd)

        # Remove ':' prefix and trailing '\n'
        s = s[1:-1].decode('ascii', errors='ignore')

        # Split commas
        sl = s.split(',')

        # Numerical values after comma
        values = [float(v) for v in sl[1:]]

        # Extract code and first value
        code = sl[0].rstrip('0123456789.-')
        v0 = sl[0].split(code)[1]
        if v0:
            values = [float(v0)] + values

        return code, values

    @proxycall()
    def check_channel(self, channel):
        """
        Verify that channel is valid
        """
        channel = int(channel)
        if channel < 0 or channel >= self.no_channels:
            raise RuntimeError("'{channel}' is not a valid channel")
        return True

    @proxycall(admin=True)
    def calibrate(self, channel):
        """
        Perform calibration of given channel.
        Args:
            channel: channel index

        Returns: None
        """
        code, v = self.send_cmd(f':CS{channel}')
        if code != 'E' or (int(v[0]) != channel or int(v[1]) != 0):
            raise RuntimeError(f'Calibration failed on channel {channel}, aborting...')
        else:
            self.logger.info(f'Calibration for channel {channel} successful')

    @proxycall(admin=True, interrupt=True)
    def abort(self):
        """
        Emergency stop.
        """
        self.logger.info("ABORTING MOTION!")
        return self.send_cmd(':S')

    @proxycall()
    def check_done(self, channel):
        """
        Poll until movement is complete.
        """
        with emergency_stop(self.abort):
            while True:
                code, f = self.send_cmd(f':GS{channel}')
                if int(f[1]) in [0, 3, 9]:
                    # motor is not moving:
                    # 0 - stopped --> target reached
                    # 3 - holding voltage is on --> target reached
                    # 9 - movement reached hard limit
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        return

    @proxycall()
    def get_speed(self, channel):
        """
        Read the current closed loop speed (in um/s) for given channel.

        Args:
            channel:

        Returns:
            speed in um/s
        """
        self.check_channel(channel)

        # Get speed
        code, v = self.send_cmd(f':GCLS{channel}')  # "Get Closed Loop Speed"

        if int(v[1]) == 0:
            raise RuntimeError('Closed loop speed control is deactivated')

        speed_um_s = float(v[1])*1e-3
        self.logger.debug(f'Current maximum speed is {speed_um_s} um/s for channel {channel}')
        return speed_um_s

    @proxycall(admin=True)
    def set_speed(self, channel, v_um_s):
        """
        Set the maximum speed for a given channel in μm/s

        Args:
            channel (int): channel index
            v_um_s: speed in micrometer/s.

        Returns:
            speed in um/s as returned by the controller.
        """
        self.check_channel(channel)

        # check that speed is in the valid range
        v_nm_s = int(1000 * v_um_s)
        if v_nm_s < 1 or v_nm_s > 100000000:
            raise RuntimeError('Speed needs to be between 1 and 100000 um/s')

        # set speed
        code, v = self.send_cmd(f':SCLS{channel:d},{v_nm_s:d}')  # Set Closed Loop Speed

        # check that answer is correct
        if (code != 'E' and v[0] != channel) or v[1] != 0:
            raise RuntimeError(f'Setting speed on channel {channel} failed.')

        self.logger.debug(f'Maximum speed for channel {channel} set to {v_um_s} um/s ')

        # Extra confirmation that everything is fine
        return self.get_speed(channel)

    @proxycall(admin=True)
    def disable_speed_control(self, channel):
        """
        Deactivate closed loop speed control on given channel. Use `set_speed` with a valid value to reactivate.

        Args:
            channel (int): channel index

        Returns:
            True if the operation has succeeded.
        """
        self.check_channel(channel)
        code, v = self.send_cmd(f':SCLS{channel:d},0')

        if (code != 'E' and v[0] != channel) or v[1] != 0:
            raise RuntimeError(f'Deactivating speed control on channel {channel} failed.')

        self.logger.info(f'Speed control on channel {channel} is disabled.')
        return True

    @proxycall()
    def get_accel(self, channel):
        """
        Read the current acceleration (in um/s^2)

        Args:
            channel (int): channel index

        Returns:

        """
        self.check_channel(channel)

        # Read accel value
        code, a = self.send_cmd(f':GCLA{channel}')  # Get Closed Loop Acceleration
        accel_um_s2 = float(a[1])
        self.logger.debug(f'Current acceleration on channel {channel} is {accel_um_s2} um/s^2')

        return accel_um_s2

    @proxycall(admin=True)
    def set_accel(self, channel, a_um_s2):
        """
        Set the current acceleration in um/s^2

        Args:
            channel (int): channel index
            a_um_s2: acceleration in um/s^2

        Returns:
            acceleration in um/s^2
        """
        self.check_channel(channel)

        # check that accel. value is valid
        ai = int(a_um_s2)
        if ai < 1 or ai > 1000:
            raise RuntimeError('Acceleration needs to be between 0 and 1000 um/s^2')

        code, a = self.send_cmd(f':SCLA{channel},{ai}')
        if (code != 'E' or a[0] != channel) or a[1] != 0:
            raise RuntimeError('Setting acceleration failed')

        self.logger.debug(f'Acceleration for channel {channel} set to {a_um_s2} um/s^2')

        # Extra confirmation that everything is fine
        return self.get_accel(channel)

    @proxycall(admin=True)
    def disable_accel_control(self, channel):
        """
        Deactivate closed loop acceleration control on given channel. Use `set_accel` with a valid value to reactivate.

        Args:
            channel (int): channel index

        Returns:
            True if the operation has succeeded.
        """
        self.check_channel(channel)
        code, v = self.send_cmd(f':SCLA{channel:d},0')

        if (code != 'E' and v[0] != channel) or v[1] != 0:
            raise RuntimeError(f'Deactivating acceleration control on channel {channel} failed.')

        self.logger.info(f'Acceleration control on channel {channel} is disabled.')
        return True

    @proxycall(admin=True)
    @property
    def sensormode(self):
        """
        Current system sensor mode
          * 0: disabled
          * 1: enabled
          * 2: powersave

        Keep to powersave when possible to reduce heat production.
        This will however incur a tiny delay between sending a move command and
        the move.
        """
        # get the mode
        code, m = self.send_cmd(':GSE')

        m = int(m[0])
        if m not in list(self.SENSOR_MODES.keys()):
            raise RuntimeError('Getting sensor mode failed.')
        self.logger.info(f'Sensor mode is {self.SENSOR_MODES[m]} ({m}).')
        return m

    @sensormode.setter
    def sensormode(self, val):
        # check if val is a valid number
        if val not in [0, 1, 2]:
            raise RuntimeError('Valid power modes are 0-disabled, 1-enabled, 2-powersave')

        # set the mode
        code, v = self.send_cmd(f':SSE{val:d}')

        if (code != 'E' or v[0] != -1) or v[1] != 0:
            raise RuntimeError('Setting sensor mode failed.')

    @proxycall()
    def get_limit(self, channel):
        """
        Read back user defined software limits for a channel, if any were set

        Args:
            channel (int): channel index

        Returns:
            (inferior limit, superior limit) in um
        """
        self.check_channel(channel)

        # get limits
        code, l0 = self.send_cmd(f':GPL{channel}')

        # TODO: CONFIRM THAT THE LIMITS ARE INDEED l0[1] and l0[2]

        # if no limits,will return E<channel>,<148>:
        if code == 'E' and l0[1] == 148:
            self.logger.debug('No soft limits set')
            return None, None
        else:
            self.logger.debug(f'Limits are [{l0[1]}, {l0[2]}]')
            return (l0[1], l0[2])

    @proxycall()
    def get_pos(self, channel):
        """
        Read back the current position of the channel in um.
        """
        self.check_channel(channel)

        # get position
        code, p = self.send_cmd(f':GP{channel}')

        return float(p[1])*1e-3

    @proxycall(admin=True, block=False)
    def move_abs(self, channel, pos_abs_um):
        """
        Move stage to absolute position in um.
        Returns end position.
        """
        self.check_channel(channel)

        # move
        pos_abs_nm = int(pos_abs_um*1000)
        self.send_cmd(f':MPA{channel:d},{pos_abs_nm:d},60000')

        self.check_done(channel)

        # read motor position after move
        return self.get_pos(channel)

    @proxycall(admin=True, block=False)
    def move_rel(self, channel, pos_rel_um):
        """
        Move stage relative, in um.
        Returns end position.
        """
        return self.move_abs(channel, self.get_pos(channel) + pos_rel_um)

    @proxycall(admin=True, block=False)
    def find_referencemark(self, channel):
        """
        Search the reference mark for given channel.
        Returns 0 if found, -1 if not found
        """
        self.check_channel(channel)

        # TODO: IS CHECK_DONE CALLED AT THE RIGHT MOMENT HERE?

        code, v = self.send_cmd(f':FRM{channel:d},2,60000,1')
        if (code != 'E' or v[0] != channel) or v[1] != 0:
            self.logger.warning(f'Reference mark not found on channel {channel}')
            return -1

        self.check_done(channel)
        return 1


class SmaractMotor(MotorBase):
    def __init__(self, name, driver, axis):
        """
        SmarAct Motor. axis is the driver's channel
        """
        super(SmaractMotor, self).__init__(name, driver)
        self.axis = axis

    def _get_pos(self):
        """
        Return position in mm
        """
        # Convert from nanometers to millimeters
        return 1e-3 * self.driver.get_pos(channel=self.axis)

    def _set_abs_pos(self, x):
        """
        Set absolute dial position
        """
        return 1e-3 * self.driver.move_abs(channel=self.axis, pos_abs_um=x*1e3)

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return 1e-3 * self.driver.move_rel(channel=self.axis, pos_rel_um=x*1e3)
