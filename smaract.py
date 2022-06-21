"""
Driver for smaract piezos via ASCII programming interface over IP/TCP

Communication can be realized by using the python wrapper for TCP communication,
socket, which basically can send/receive strings to/from an IP:port addressed
see documentation on builtin python socket module, e.g.
https://docs.python.org/3/library/socket.html

Some notes from the manual:
Each MCS has a maximum number of channels (see GNC). Commands that are directed
to a specific channel require a channel index to address the selected channel.
The channel indexes are zero based. Note that the number of channels is
constant for a given system and describes the number of positioners and/or end
effectors that may be connected to the system and not the number that currently
are connected to the system.

----------------------
Instruction syntax:
----------------------
Each command consists of an initial character (':', 0x3a), an ASCII string
coding the actual command (hereafter referred to as command string) and a
termination character (line feed, 0x0a). Empty strings (i.e. a colon character
followed by a line feed character) are ignored. All characters between a line
feed and a colon are also ignored. Generally, command strings have the
following format:
<command name>[param][,param]...
The command name is a combination of uppercase letters. Parameters are given
as decimal values and may be positive or negative.

Answer strings have the same format - a combination of uppercase letters and
optional parameters. If a command could not be executed for some reason, an
error answer string is returned in the format
E<sourceChannel>,<errorCode>.
The <sourceChannel> indicates which channel of the system generated the error.
The value is zero based. If the value of <sourceChannel> is -1, this indicates
that the error does not originate from a specific channel, but rather from the
overall system. An <errorCode> of 0 indicates that the command was successful
and therefore corresponds to an acknowledge.

version 0 18.10.2017 hans
METHODS LIST
 - Constructor: connects, homes, and sets some sensible values for speed and accel
 - speed_get --> get currend speed setting
 - speed_set --> set currend speed setting
 - accel_get --> get currend accel. setting
 - accel_set --> set currend accel. setting
 - sensormode_get --> gets the power settings of the sensor
 - sensormode_set --> sets the power settings of the sensor
 - pos_get --> read back current position
 - move_abs --> move absolute
 - move_rel --> move relative
 - referencemark_find --> search the encoder reference mark
 - parse_feedback --> helper function to read feedback from controller
"""

import time

from .base import MotorBase, DriverBase, SocketDeviceServerBase, admin_only, emergency_stop, DeviceException
from .network_conf import SMARACT as DEFAULT_NETWORK_CONF
from .ui_utils import ask_yes_no

__all__ = ['SmaractDaemon', 'Smaract', 'Motor']

DEFAULT_SPEED = 1000000  # nm/s
DEFAULT_ACCEL = 10000  # um/s^2 (!)
SENSOR_MODES = {0: 'disabled', 1: 'enabled', 2: 'power save'}

EOL = b'\n'


class SmaractDaemon(SocketDeviceServerBase):
    """
    Smaract Daemon
    """

    DEFAULT_SERVING_ADDRESS = DEFAULT_NETWORK_CONF['DAEMON']
    DEFAULT_DEVICE_ADDRESS = DEFAULT_NETWORK_CONF['DEVICE']
    EOL = EOL

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
        # Communication mode to 0-synchronous or 1- asyn.
        self.device_cmd(b':SCM0\n')
        self.logger.info('Connection established')

        self.initialized = True
        return

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.device_cmd(b':GS0\n')
        if not r:
            raise DeviceException


class Smaract(DriverBase):
    """
    Driver for Smaract piezo stage.
    """

    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    EOL = EOL

    def __init__(self, address, admin=True, **kwargs):
        """
        Connects to daemon.
        """
        if address is None:
            address = DEFAULT_NETWORK_CONF['DAEMON']

        super().__init__(address=address, admin=admin)

        self.metacalls.update({'position': lambda: [self.get_pos(0), self.get_pos(1), self.get_pos(2)],
                               'speed': lambda: [self.get_speed(0), self.get_speed(1), self.get_speed(2)]})

        # Get number of channels
        nc = self.send_recv(b':GNC\n')
        self.no_channels = int(nc[1][0])
        self.logger.info('Number of channels is %d' % self.no_channels)

        # Prompt user input to continue initialization
        # TODO: skip this step if the speed and accelerations are already the default values.
        if ask_yes_no('Do you want to set default motor speed and accelerations?'):

            # Set speed to a reasonable value for all channels
            for ind_channel in range(int(self.no_channels)):
                self.set_speed(ind_channel, DEFAULT_SPEED)

            # Set acceleration to something sensible for all channels
            for ind_channel in range(int(self.no_channels)):
                self.set_accel(ind_channel, DEFAULT_ACCEL)

        # Set sensor mode to power save
        self.set_sensormode(2)

        if ask_yes_no('Do you want to recalibrate the motors (needed only if setup has changed)?', yes_is_default=False):

            # Perform calibration
            for ind_channel in range(self.no_channels):
                code, v = self.send_recv(b':CS%d\n' % ind_channel)
                if code != 'E' or (int(v[0]) != ind_channel or int(v[1]) != 0):
                    raise RuntimeError('Calibration failed on channel %d, aborting...' % ind_channel)
                else:
                    self.logger.info('Calibration for channel %d successful' % ind_channel)
                time.sleep(2)  # Wait 2 seconds after each calibration

        # Prompt user if reference  mark search should be performed
        if ask_yes_no('Proceed with search for reference mark for all channels?', yes_is_default=False):

            # Perform calibration
            for ind_channel in range(self.no_channels):
                count_retries = 3  # if not found, retry this many times
                while count_retries > 0:
                    mark_found = self.find_referencemark(ind_channel)
                    count_retries += mark_found
                    if not mark_found:
                        self.logger.warn('Reference mark not found on channel %d, retrying...' % ind_channel)
                    else:
                        self.logger.info('Reference mark found for channel %d' % ind_channel)
                        break
                if count_retries < 1:
                    # Should an exception be raised here?
                    self.logger.error('Reference mark not found on channel %d' % ind_channel)

                # Move all motors to the 0 position
                self.logger.info('Moving to 0 position...')
                self.move_abs(ind_channel, 0)

    def send_recv(self, msg):
        """
        Communicate with controller and parse output.

        Return tuple (code, values)
        """
        s = self._send_recv(msg)

        # Remove ':' prefix and trailing '\n'
        s = s[1:-1]

        # Check if there are commas in the strings, then strip the values
        sl = s.split(',')

        code = str(list(filter(str.isalpha, sl[0])))
        values = [float(sl[0].strip(code))] + [float(v) for v in sl[1:]]

        return code, values

    def check_channel(self, channel):
        """
        Verify that channel is valid
        """
        channel = int(channel)
        if channel < 0 or channel >= self.no_channels:
            raise RuntimeError("'%s' is not a valid channel" % str(channel))
        return True

    def abort(self):
        """
        Emergency stop.
        """
        self.logger.info("ABORTING MOTION!")
        self.send_recv(b':S\n')

    def check_done(self, channel):
        """
        Poll until movement is complete.
        """
        with emergency_stop(self.abort):
            while True:
                code, f = self.send_recv(b':GS%d\n' % channel)
                if int(f[1]) in [0, 3, 9]:
                    # motor is not moving:
                    # 0 - stopped --> target reached
                    # 3 - holding voltage is on --> target reached
                    # 9 - movement reached hard limit
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        return

    def get_speed(self, channel):
        """
        Reads the current closed loop speed for a channel in nm/s
        Channels is an integer with index start on 0.
        ATTENTION!!! A speed value of 0 will mean speed control is deactivated
        Returns speed in nm/s
        """
        self.check_channel(channel)

        # Get speed
        code, v = self.send_recv(b':GCLS%d\n' % channel)  # "Get Closed Loop Speed"

        if int(v[1]) == 0:
            self.logger.info('Closed loop speed control is deactivated')
            return 0
        else:
            self.logger.info('Current max. speed is %f um/s for channel %d' % (float(v[1])*1e-3, channel))
            return int(v[1])

    @admin_only
    def set_speed(self, channel, v_nm_s):
        """
        Set the max. speed for a given channel in nm/s
        Channels is an integer with index start on 0.
        ATTENTION!!! A speed value of 0 will deactivate speed control
        """
        self.check_channel(channel)

        # check that speed is in the valid range
        if v_nm_s < 0 or v_nm_s > 100000000:
            raise RuntimeError('Speed needs to be between 0 and 100000000')

        # set speed
        code, v = self.send_recv(b':SCLS%d,%d\n' % (channel, v_nm_s))  # Set Closed Loop Speed

        # check that answer is correct
        if (code != 'E' and v[0] != channel) or v[1] != 0:
            raise RuntimeError('Setting speed on channel %d failed.' % channel)

        # Is this necessary?
        self.get_speed(channel)

    def get_accel(self, channel):
        """
        Read the current acceleration in um/s^2 (!)
        Channels is an integer with index start on 0.
        ATTENTION!!! An accel. value of 0 means accel control is deactivated.
        """
        self.check_channel(channel)

        # Read accel value
        code, a = self.send_recv(b':GCLA%d\n' % channel)  # Get Closed Loop Acceleration
        self.logger.info('Current accel. is %f um/s^2 on channel %d' % (float(a[1]), channel))

        return float(a[1])

    @admin_only
    def set_accel(self, channel, a_um_s2):
        """
        Set the current acceleration in um/s^2 (!)
        Channels is an integer with index start on 0.
        ATTENTION!!! An accel. value of 0 means accel control is deactivated.
        """
        self.check_channel(channel)

        # check that accel. value is valid
        if a_um_s2 < 0 or a_um_s2 > 10000000:
            raise RuntimeError('Acceleration needs to be between 0 and 1000')

        code, a = self.send_recv(b':SCLA%d,%d\n' % (channel, a_um_s2))
        if (code != 'E' or a[0] != channel) or a[1] != 0:
            raise RuntimeError('Setting acceleration failed')

        # Is this needed?
        self.get_accel(channel)

    def get_sensormode(self):
        """
        Get the current system sensor mode
        0-disabled, 1-enabled, 2-powersave
        Keep to powersave when possible to reduce heat production.
        This will however incur a tiny delay between sending a move command and
        the move.
        """
        # get the mode
        code, m = self.send_recv(b':GSE\n')

        # Quick hack to make this part work again, but maybe self.parse_feedback should be modified.
        m = int(m[0])
        if m not in list(SENSOR_MODES.keys()):
            raise RuntimeError('Getting sensor mode failed.')
        self.logger.info('Sensor mode is %s' % SENSOR_MODES[m])
        return m

    @admin_only
    def set_sensormode(self, val):
        """
        Set the current system sensor mode
        0-disabled, 1-enabled, 2-powersave
        Keep to powersave when possible to reduce heat production.
        This will however incur a tiny delay between sending a move command and
        the move.
        """
        # check if val is a valid number
        if val not in [0, 1, 2]:
            raise RuntimeError('Valid power modes are 0-disabled, 1-enabled, 2-powersave')

        # set the mode
        code, v = self.send_recv(b':SSE%d\n' % val)

        if (code != 'E' or v[0] != -1) or v[1] != 0:
            raise RuntimeError('Setting sensor mode failed.')

        self.get_sensormode()

    def get_limit(self, channel):
        """
        Read back user defined software limits for a channel, if any were set
        """
        self.check_channel(channel)

        # get limits
        code, l0 = self.send_recv(b':GPL%d\n' % channel)

        # if no limits,will return E<chanel>,<148>:
        if code == 'E' and l0[1] == 148:
            self.logger.info('No soft limits set')
            return None, None
        else:
            self.logger.info('Limits are %f to %f' % (l0[1], l0[2]))
            return l0

    def get_pos(self, channel):
        """
        Read back the current position of the channel in nm.
        """
        self.check_channel(channel)

        # get position
        code, p = self.send_recv(b':GP%d\n' % channel)

        return float(p[1])

    @admin_only
    def move_abs(self, channel, pos_abs_nm):
        """
        Move stage to absolute position in nm.
        Returns end position.
        """
        self.check_channel(channel)

        # move
        self.send_recv(b':MPA%d,%d,60000\n' % (channel, pos_abs_nm))

        self.check_done(channel)

        # read motor position after move
        return self.get_pos(channel)

    @admin_only
    def move_rel(self, channel, pos_rel_nm):
        """
        Move stage relative, in nm.
        Returns end position.
        """
        return self.move_abs(channel, self.get_pos(channel) + pos_rel_nm)

    @admin_only
    def find_referencemark(self, channel):
        """
        Prompt the reference mark search for channel.
        Returns 0 if found, -1 if not found
        """
        self.check_channel(channel)

        code, v = self.send_recv(b':FRM%d,2,60000,1\n' % channel)
        if (code != 'E' or v[0] != channel) or v[1] != 0:
            self.logger.warning('Reference mark not found on channel %d' % channel)
            return -1

        self.check_done(channel)
        return 1


class Motor(MotorBase):
    def __init__(self, name, driver, axis):
        """
        SmarAct Motor. axis is the driver's channel
        """
        super(Motor, self).__init__(name, driver)
        self.axis = axis

    def _get_pos(self):
        """
        Return position in mm
        """
        # Convert from nanometers to millimeters
        return 1e-6 * self.driver.get_pos(channel=self.axis)

    def _set_abs_pos(self, x):
        """
        Set absolute dial position
        """
        return 1e-6 * self.driver.move_abs(channel=self.axis, pos_abs_nm=x*1e6)

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return 1e-6 * self.driver.move_rel(channel=self.axis, pos_rel_nm=x*1e6)
