"""
functions to control the long range McLennan motors via the Applied Motion
Products ST5 drives. Similar to the smaract piezo motors, the drives are
controlled over TCP with ASCII strings. The command set can be found in the
Host_Command_Reference_Rev_1.pdf.
To set up the drives for communication check the
ST5-10-QSi_Hardware Manual_920-0004E.pdf.
First setup of the motors can be done with the ST Configurator software
available from the support section of www.applied-motion.com
Here, custom motor for each drive needs to be set up, setting to be changed are
--> Maximum current 4.2 A for parallel wiring (for seroal wiring it would be 2.1 A)
--> Holding torque 1.63 Nm
--> Rotor inertia 340 g cm**2
leave the rest as default settings.
Then need to Download to drive to store settings permanently.
###############################################################################
Communication can be realized by using the python wrapper for TCP communication,
socket, which basically can send/receive strings to/from an IP:port addressed
see documentation on builtin python socket module, e.g.
https://docs.python.org/3/library/socket.html
the controller drops the connection every so often, so needto keep it open
by polling it in the background.
ATTENTION! Once communication has been established, the control computer
'owns' the communication, meaning that no other computer might communicate
with the drive until the drives have been physically switched off and on again
###############################################################################
The basic structure of a command packet from the host to the drive is always a
text string followed by a carriage return (no line feed required). The text
string is always composed of the command itself, followed by any parameters
used by the command. The carriage return denotes the end of transmission to
the drive.

     XXAB<cr>

The function self.input_parse() takes care of adding the <cr> as well as
an appropriate header.
XX symbolizes the command itself, which is always composed of two capital
letters. 'A' symbolizes the first of two possible parameters, and 'B' symbolizes
the second. Parameters 1 and 2 vary in length, can be letters or numbers, and
are often optional. The '<cr>' symbolizes the carriage return which terminates
the command string. How the carriage return is generated in your application
will depend on your host software. Once a drive receives the <cr> it will
determine whether or not it understood the preceding characters as a valid
command. If it did understand the command the drive will either execute or
buffer the command. If Ack/Nack is turned on (see PR command), the drive will
also send an Acknowledge character (Ack) back to the host. The Ack for an
executed command is % (percent sign), and for a buffered command is * (asterisk).
If the drive did not understand the command it will do nothing. If Ack/Nack is
turned on a Nack will be sent, which is signified by a ? (question mark). The
Nack is usually accompanied by a numerical code that indicates a particular error.

Responses from the drive will be sent with a similar syntax to the associated
SCL commandself.
      XX=A
'XX' symbolizes the command itself, which is always composed of two capital
letters. 'A' symbolizes the requested data, and may be presented in either
Decimal or Hexadecimal format (see the IF command). The '<cr>' symbolizes the
carriage return which terminates the response string.
###############################################################################
version 0 06.11.2017 hans, not working
version 0.1 8.12.2017 workig
METHOD LIST
 - self.axis_connect
 - self.axis_enable
 - self.cmd_send
 - self.input_parse
 - self.output_parse
 - self.axis_enable
 - self.axis_disable
 - self.axis_poll
 - self.axis_poll_stop
 - self.axis_move_rel
 - self.current_set (and _get)
 - self.vel_set (and _get)
 - self.accel_set (and _get)
 - self.accel_max_set (and _get)
 - self.decel_set (and _get)
 - self.microstep_resolution_set (and _get)
TO DO
- implement a software based coord system that keeps tack of the total number
  of steps moved and returns the actual position

^The above TO DO was done by Ronan 17/08/2018
Functions:
 - self.read_current_position()
 - seld.write_current_position()
 - self.axis_move_abs()
were added.
Reading and writing positions use Numpy and save in a txt format - maybe someone
who is better at coding can change this in future if necessary.
The absolute movement function is simply based off reading the current position
and subsequently calling the relative movement function.
"""

import time
import json

from . import register_proxy_client
from .base import MotorBase, SocketDriverBase, emergency_stop, DeviceException
from .util.uitools import ask_yes_no
from .util.proxydevice import proxydevice, proxycall
from .network_conf import NETWORK_CONF

__all__ = ['McLennan1', 'McLennan2', 'McLennan3', 'Motor']

# This API uses carriage return (\r) as end-of-line.
EOL = b'\r'

# microsteps per revolution, according to table in the manual, needs to be set before AC and DC
DEFAULT_MICROSTEPS = 20000

# acceleration in rev/s/s
DEFAULT_ACCELERATION = 2

# deceleration in rev/s/s
DEFAULT_DECELERATION = 2

# velocity in rev/s
DEFAULT_VELOCITY = 2

# emergency deceleration for fast stops. If spinning at 2 rev/s AM=20 should stop in 0.1 s
DEFAULT_EMERGENCY_DECELERATION = 20

# motor current in amps, check with mclennan what values are good
DEFAULT_CURRENT = 2.1

# motor limits in mm
DEFAULT_LIMITS = (-20, 20)

# Bitmasks for status return
STATUS_STRINGS = ['Motor Enabled (Motor Disabled if this bit = 0)',  # 0x0001
                  'Sampling (for Quick Tuner)',  # 0x0002
                  'Drive Fault (check Alarm Code)',  # 0x0004
                  'In Position (motor is in position)',  # 0x0008
                  'Moving (motor is moving)',  # 0x0010
                  'Jogging (currently in jog mode)',  # 0x0020
                  'Stopping (in the process of stopping from a stop command)',  # 0x0040
                  'Waiting (for an input; executing a WI command)',  # 0x0080
                  'Saving (parameter data is being saved)',  # 0x0100
                  'Alarm present (check Alarm Code)',  # 0x0200
                  'Homing (executing an SH command)',  # 0x0400
                  'Waiting (for time; executing a WD or WT command)',  # 0x0800
                  'Wizard running (Timing Wizard is running)',  # 0x1000
                  'Checking encoder (Timing Wizard is running)',  # 0x2000
                  'Program is running',  # 0x4000
                  'Initializing (happens at power up)']  # 0x8000


@proxydevice()
class McLennan(SocketDriverBase):
    """
    McLennan driver
    McLennan controllers don't have encoders, so we need to store
    and increment a software position based on the passed commands.
    That makes things a bit more complicated.
    """

    EOL = EOL
    ballscrew_length = 2.    # Displacement for one full revolution
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    EOL = EOL

    def __init__(self, device_address, name):
        """
        Constructor requires 'name' to differentiate multiple instances.
        """
        self.name = name
        super().__init__(device_address=device_address)

        self.metacalls.update({'position': self.get_pos,
                               'current': self.get_current,
                               'velocity': self.get_vel,
                               'microstep_resolution': self.get_microstep_resolution
                               })

    def init_device(self):
        """
        Device initialization.
        """
        # ask for firmware version to see if connection works
        version, _ = self.send_cmd('RV')
        self.logger.debug(f'Firmware version is {version}')

        # turn Ack/Nack on
        self.send_cmd('PR4')

        if ask_yes_no('Set defaults? (probably needed only the first time)', yes_is_default=False):
            self.logger.info('Setting defaults...')
            self.set_microstep_resolution(DEFAULT_MICROSTEPS)
            self.set_accel(DEFAULT_ACCELERATION)
            self.set_decel(DEFAULT_DECELERATION)
            self.set_vel(DEFAULT_VELOCITY)
            self.set_decel_max(DEFAULT_EMERGENCY_DECELERATION)
            self.set_current(DEFAULT_CURRENT)
            self.set_limits(DEFAULT_LIMITS)
            self.logger.info('Done setting defaults.')

        position = self.get_pos()
        if position is None:
            if ask_yes_no('No position recorded! Set to 0.0?'):
                position = 0.0
                self.set_pos(position)

        self.logger.info(f'Initial position: {position:0.2f}')

        # TODO: how to name motors?
        # Create motor
        # self.motor = {'rot': Motor('rot', self)}
        # motors['rot'] = self.motor['rot']

        self.logger.info(f"McLennan ({self.name}) initialization complete.")
        self.initialized = True
        return

    def parse_escaped(self, cmd):
        """
        Parse extra commands because of persistence.
        """
        out = cmd.split(b'PERSIST')

        if len(out) == 1:
            # Not a 'PERSIST' command. continue parsing
            return super().parse_escaped(cmd)

        cmd, payload = out
        payload = payload.decode()

        print(f'payload: {payload}')

        if cmd == b'GET':
            # pass persistence value
            value = self.persistence_conf.get(payload)
            return json.dumps({payload: value}).encode()
        if cmd == b'SET':
            # Set a persistence value
            self.persistence_conf.update(json.loads(payload))
            return b'OK'
        else:
            return b'Error: unknown command ' + cmd

    def send_cmd(self, cmd):
        """
        Pass command to the device after slight reformatting.
        """
        # Convert command to the right format before sending.
        if isinstance(cmd, str):
            cmd = cmd.encode()
        out = b'\x00\x07' + cmd + self.EOL
        reply = self.device_cmd(out)

        # strip header and \r
        r = reply[2:-1].decode('ascii', errors='ignore')

        # Try to split around '='
        rs = r.split('=')

        print(f'rs = {rs}')

        # If it failed, the controller returned a success/fail symbol
        if len(rs) == 1:
            return rs[0], None

        return rs[0], rs[1]

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.send_cmd('RV')
        if not r:
            raise DeviceException

    @proxycall(admin=True)
    def enable(self):
        """
        Enable motor. Motors are enabled by default when switching the controllers on
        so this function is not really needed that often. However it might be useful to
        disable motors sometimes when not moving or when switching the controllers off
        """
        s, v = self.send_cmd('ME')
        if s != '%':
            self.logger.critical('Enabling motor failed!')

    @proxycall(admin=True)
    def disable(self):
        """
        Disable motor
        """
        s, v = self.send_cmd('MD')
        if s != '%':
            self.logger.critical('Disabling motor failed!')

    @proxycall(admin=True)
    def move_rel(self, dx):
        """
        Move relative, in mm

        the ballscrew has a pitch of 2 mm, micro-stepping is set to 20,000 steps per revolution
        so 1 microstep corresponds to 2 mm/20'000 steps = 100 nm (?)
        TODO: IS IT TRUE FOR ALL MOTORS?
        """
        dx = float(dx)

        # Get limits
        low_lim, high_lim = self.get_limits()

        # Get current position
        pos = self.get_pos()

        if pos is None:
            self.logger.critical('Move aborted. Current position undefined. Use `set_pos` to set.')
            return

        # Check limits
        if (pos + dx) < low_lim:
            self.logger.critical(f'Move by {dx} mm goes beyond lower limit ({pos} + {dx} < {low_lim})')
            return
        if (pos + dx) > high_lim:
            self.logger.critical(f'Move by {dx} mm goes beyond higher limit ({pos} + {dx} > {high_lim})')
            return

        # first get the microstep resolution
        ms = self.get_microstep_resolution()

        # number of microsteps
        no_microsteps = int(dx*ms/self.ballscrew_length)

        # maximum number of microsteps per move is limited by hardware
        if no_microsteps < -2147483647 or no_microsteps > 2147483647:
            self.logger.critical(f'Step too large: {no_microsteps}. Should be < 2147483647.')
            return

        # move
        c, v = self.send_cmd(f'FL{no_microsteps}')
        self.check_done()
        self.logger.info("Motion finished.")

        # Write new position
        self.set_pos(pos + dx)
        return self.get_pos()

    @proxycall()
    def get_status(self):
        """
        Get status from driver.
        Return a list of 16 bool corresponding to the list STATUS_STRINGS at the top
        of the file.
        """
        s, v = self.send_cmd('SC')
        vint = int(v, base=16)
        codes = [bool(vint & 2**i) for i in range(16)]
        return codes

    @staticmethod
    def parse_status(codes):
        """
        Parse status_value
        """
        return [STATUS_STRINGS[i] for i in range(16) if codes[i]]

    @proxycall()
    def check_done(self):
        """
        Poll until movement is complete.
        """
        with emergency_stop(self.abort):
            while True:
                # query status
                codes = self.get_status()
                if not codes[4]:
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        return

    @proxycall()
    def abort(self):
        """
        Emergency stop
        """
        self.logger.critical("ABORTING MOTION!")
        self.send_cmd('ST')
        self.check_done()
        self.logger.info("Motion aborted. Position is now undefined.")
        self.set_pos(None)

    @proxycall(admin=True, block=False)
    def move_abs(self, x):
        """
        Move absolute, in mm.
        This method relies on the recorded software position to have a valid value.
        There is a possibility that the absolute position accumulate errors with time.
        """
        pos = self.get_pos()
        if pos is None:
            self.logger.critical('Move aborted. Current position undefined. Use `set_pos` to set.')
            return

        move = x - self.get_pos()
        return self.move_rel(move)

    @proxycall()
    def get_microstep_resolution(self):
        """
        Get number of microsteps per revolution
        """
        c, v = self.send_cmd('EG')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command EG failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_microstep_resolution(self, microstep_resolution):
        """
        Set number of microsteps per revolution
        """
        microstep_resolution = int(microstep_resolution)
        if (microstep_resolution < 201) or (microstep_resolution > 51200):
            self.logger.critical(f'Microstep resolution should be between 200 and 51200.')
            return
        s, v = self.send_cmd(f'EG{microstep_resolution}')
        if '?' in s:
            self.logger.critical('Error setting microsteps')
        return

    @proxycall()
    def get_accel(self):
        """
        Get acceleration (in revolution / s^2)
        """
        c, v = self.send_cmd('AC')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command AC failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_accel(self, accel):
        """
        Set acceleration (in revolution / s^2)
        """
        accel = int(accel)
        s, v = self.send_cmd(f'AC{accel}')
        if '?' in s:
            self.logger.critical('Could not set acceleration')
        return

    @proxycall()
    def get_decel(self):
        """
        Get deceleration (in revolution / s^2)
        """
        c, v = self.send_cmd('DC')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command DC failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_decel(self, decel):
        """
        Set acceleration (in revolution / s^2)
        """
        decel = int(decel)
        s, v = self.send_cmd(f'DC{decel}')
        if '?' in s:
            self.logger.critical('Could not set deceleration')
        return

    @proxycall()
    def get_vel(self):
        """
        Get acceleration (in revolution / s^2)
        """
        c, v = self.send_cmd('VE')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command VE failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_vel(self, vel):
        """
        Set velocity (in revolution / s)
        """
        vel = int(vel)
        s, v = self.send_cmd(f'VE{vel}')
        if '?' in s:
            self.logger.critical('Could not set velocity')
        return

    @proxycall()
    def get_accel_max(self):
        """
        Get maximum acceleration (in revolution / s^2)
        """
        c, v = self.send_cmd('MA')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command MA failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_accel_max(self, accel):
        """
        Set acceleration (in revolution / s^2)
        """
        accel = int(accel)
        s, v = self.send_cmd(f'MA{accel}')
        if '?' in s:
            self.logger.critical('Could not set maximum acceleration')
        return

    @proxycall()
    def get_decel_max(self):
        """
        Get maximum deceleration (in revolution / s^2)
        """
        c, v = self.send_cmd('AM')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command AM failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_decel_max(self, decel):
        """
        Set maximum acceleration (in revolution / s^2)
        """
        decel = int(decel)
        s, v = self.send_cmd(f'AM{decel}')
        if '?' in s:
            self.logger.critical('Could not set maximum deceleration')
        return

    @proxycall()
    def get_current(self):
        """
        Get current (in amps)
        """
        c, v = self.send_cmd('CC')
        try:
            v = float(v)
        except ValueError:
            self.logger.critical(f'Command CC failed (return value is {v}')
            raise
        return v

    @proxycall(admin=True)
    def set_current(self, cc):
        """
        Set current (in amps)
        """
        cc = int(cc)
        s, v = self.send_cmd(f'CC{cc}')
        if '?' in s:
            self.logger.critical('Could not set current')
        return

    @proxycall()
    def get_pos(self):
        """
        Get (software) position (in mm)
        """
        # Send escape command
        return self.config.get('position')

    @proxycall(admin=True)
    def set_pos(self, pos):
        """
        Set (software) position (in mm)
        This doesn't move the motor itself!
        """
        self.config['position'] = pos

    @proxycall()
    def get_limits(self):
        """
        Get (software) limits (in mm)
        """
        return self.config.get('limits')

    @proxycall(admin=True)
    def set_limits(self, limits):
        """
        Set (software) limits (in mm)
        """
        self.config['limits'] = limits


NET_INFO = NETWORK_CONF['mclennan1']
@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class McLennan1(McLennan):
    """
    Driver for motor 1
    """
    def __init__(self, device_address=None):
        """
        Constructor requires 'name' to differentiate multiple instances.
        """
        self.name = 'mclennan1'
        super().__init__(device_address=NETWORK_CONF[self.name]['device'], name=self.name)


NET_INFO = NETWORK_CONF['mclennan2']
@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class McLennan2(McLennan):
    """
    Driver for motor 2
    """
    def __init__(self, device_address=None):
        """
        Constructor requires 'name' to differentiate multiple instances.
        """
        self.name = 'mclennan2'
        super().__init__(device_address=NETWORK_CONF[self.name]['device'], name=self.name)


NET_INFO = NETWORK_CONF['mclennan3']
@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class McLennan3(McLennan):
    """
    Driver for motor 3
    """
    def __init__(self, device_address=None):
        """
        Constructor requires 'name' to differentiate multiple instances.
        """
        self.name = 'mclennan3'
        super().__init__(device_address=NETWORK_CONF[self.name]['device'], name=self.name)


class Motor(MotorBase):
    def __init__(self, name, driver):
        super(Motor, self).__init__(name, driver)
        self.limits = (-31, 31)

    def _get_pos(self):
        return self.driver.get_pos()

    def _set_abs_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.move_abs(x)

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.move_rel(x)

