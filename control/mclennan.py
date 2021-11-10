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

import socket
import time
import os
import errno
import threading
import logging
import datetime

from .base import MotorBase, DriverBase
from . import conf_path

__all__ = ['McLennan', 'Motor']

DEFAULT_MICROSTEPS = 20000
DEFAULT_ACCELERATION = 2
DEFAULT_DECELERATION = 2
DEFAULT_VELOCITY = 2
DEFAULT_EMERGENCY_DECELERATION = 20
DEFAULT_CURRENT = 2.1


class McLennan(DriverBase):

    limits = (-200, 200)

    def __init__(self, host='192.168.0.60', port=7776, name=None, poll_interval=10.):
        """
        Initialise McLennan driver (coarse translation motors).
        """
        DriverBase.__init__(self, poll_interval=poll_interval)

        self.host = host
        self.port = port

        # name=None is not acceptable because multiple connections are possible.
        if name is None:
            self.name = self.__class__.__name__ + str(self.port)
        else:
            self.name = name

        self.logger = logging.getLogger("McLennan Driver (%s)" % self.name)

        # This will run the initialisation on the thread
        self.start_thread()

    def _init(self):
        """
        McLennan driver initialisation - running on the polling thread.
        """
        self.logger.info("Initialising McLennan controller.")

        # create socket object
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # creates the socket object controller
        self.sock.settimeout(5)  # set timeout in seconds

        # connect
        conn_errno = self.sock.connect_ex((self.host, self.port))
        retry_count = 0  # counter for retries, limit to 10 retries
        while conn_errno != 0:  # and conn_errno != 114:
            time.sleep(.05)

            conn_errno = self.sock.connect_ex((self.host, self.port))
            retry_count += 1
            if retry_count > 10:
                raise RuntimeError('Connection refused.')

        # ask for firmware version to see if connection works
        s, v = self.cmd_send('RV')
        self.logger.info('Connected to motor, firmware is %s' % v)

        # turn Ack/Nack on
        self.cmd_send('PR4')

        self.logger.info('Setting defaults...')

        # microsteps per revolution, according to table in the manual, needs to be set before AC and DC
        self.set_microstep_resolution(DEFAULT_MICROSTEPS)
        # acceleration in rev/s/s
        self.set_accel(DEFAULT_ACCELERATION)
        # deceleration in rev/s/s
        self.set_decel(DEFAULT_DECELERATION)
        # velocity in rev/s
        self.set_vel(DEFAULT_VELOCITY)
        # emergency deceleration for fast stops. If spinning at 2 rev/s AM=20 should stop in 0.1 s
        self.set_emergency_decel(DEFAULT_EMERGENCY_DECELERATION)
        # # motor current in amps, check with mclennan what values are good
        self.set_current(DEFAULT_CURRENT)

        # Unique filename for storing absolute position
        self.persistence_file = os.path.join(conf_path, 'mclennan', self.host.replace('.', '_') + '_' + str(self.port))
        self.logger.info('Persistence file is "%s"' % self.persistence_file)

        if not os.path.exists(self.persistence_file):
            self.logger.warn('Persistence file does not exist. Absolute position initialised to 0.')
            # Create path
            try:
                os.makedirs(os.path.split(self.persistence_file)[0])
            except OSError as e:
                if e.errno == errno.EEXIST:
                    pass
                else:
                    raise
            self.write_current_position(0.)

    def _poll(self):
        """
        We need an actual call to the driver to keep the connection alive.
        """
        self.get_accel()

    def mqtt_payload(self):
        """
        MQTT payload
        """
        return {'xnig/drivers/mclennan_%s/pos' % self.name: self.read_current_position()}

    def enable(self):
        """
        Enable motor. Motors are enabled by default when switching the controllers on
        so this function is not really needed that often. However it might be useful to
        disable motors sometimes when not moving or when switching the controllers off
        """
        s, v = self.cmd_send('ME')
        if s != '%':
            raise RuntimeError('Enabling motor failed!')

    def disable(self):
        """
        Disable motor
        """
        s, v = self.cmd_send('MD')
        if s != '%':
            raise RuntimeError('Disabling motor failed!')

    def cmd_send(self, cmd):
        """
        Send a command to a controller and reads back the input
        """

        with self._lock:
            cmd = self.input_parse(cmd)
            self.sock.sendall(cmd)
            # feedback
            try:  # at first run, Ack/Nack might be off, need to handle timeout on read from drive
                o = self.sock.recv(128)
                while o[-1:] != '\r':
                    o += self.sock.recv(128)
                # check what it means
                s, v = self.output_parse(o)
            except socket.timeout:
                raise RuntimeError('Communication timed out')
        return s, v

    @staticmethod
    def input_parse(str_in):
        """
        Take a command from the Host Command Set and convert it
        to a bytestring that can be read by the controller
        Input should be a string something like
           XX
        or
           XXAB
        where XX is the Command, e.g. RV (Read the firmware Version) and
        AB is the optional value, e.g. VE2.5 (set VElocity to 2.5 rev/s)
        """
        # split input string into individual characters
        str_out = list(str_in)
        # convert to bytestring
        str_out = bytearray([ord(i) for i in str_out])
        # header and encoder
        str_out = bytearray([0, 7]) + str_out + bytearray(['\r'])
        return str_out

    @staticmethod
    def output_parse(str_in):
        """
        Take the answer from the controller and convert into human readable format
        """
        str_out = [i for i in str_in]  # convert to listdir
        str_out = str_out[2:-1]  # strip header and <cr>

        # parse
        if len(str_out) == 1:  # controller returned a success/fail symbol
            return str_out[0], None
        else:
            # get command (first two symbols)
            cmdname = str_out.pop(0) + str_out.pop(0)
            # get rid of '=' sign
            str_out.pop(0)
            if str_out[0].isalpha():
                value = ''.join(str_out)
            else:
                value = float(''.join(str_out))
            return cmdname, value

    def _finish(self):
        """
        Clean up
        """
        # disconnect socket
        self.sock.close()

    def move_rel(self, dx):
        """
        Move relative, in mm
        the ballscrew has a pitch of 2 mm, micro-stepping is set to 20,000 steps per revolution
        so 1 microstep corresponds to 2 mm/20'000 steps = 100 nm (?)
        """
        dx = float(dx)

        # Update absolute position
        new_position = self.read_current_position() + dx
        self._check_limits(new_position)

        # convert distance to revolutions
        # first get the microstep resolution as per table in the Manual
        c, v = self.get_microstep_resolution()

        # number of microsteps
        no_microsteps = int(dx*v/2.)  # (dx in mm) * (microsteps/revolution) / (2 mm/revolution)

        # maximum number of microsteps per move is limited by hardware
        if no_microsteps < -2147483647 or no_microsteps > 2147483647:
            raise RuntimeError('Step too large: %d. Should be < 2147483647.')

        # move
        c, v = self.cmd_send('FL'+str(no_microsteps))

        # Write new position
        self.write_current_position(new_position)
        return self.read_current_position()

    def move_abs(self, x):
        """
        Move absolute, in mm.
        This method relies on self.pos to have a valid value. There is a possibility that
        the absolute position accumulate errors with time.
        """
        move = x - self.read_current_position()
        return self.move_rel(move)

    def _check_limits(self, x):
        """
        Check that limits are satisfied
        """
        assert (x > self.limits[0]) and (x < self.limits[1])

    def get_microstep_resolution(self):
        return self.cmd_send('EG')

    def set_microstep_resolution(self, microstep_resolution):
        if microstep_resolution not in list(range(200, 51201)):
            raise RuntimeError('Wrong microstep resolution value, please select an integer between 200 and 51200.')
        s, v = self.cmd_send(('EG'+str(microstep_resolution)))
        if '?' in s:
            raise RuntimeError('Could not set microsteps')

    def get_accel(self):
        return self.cmd_send('AC')

    def set_accel(self, accel):
        s, v = self.cmd_send('AC'+str(accel))
        if '?' in s:
            raise RuntimeError('Could not set acceleration')

    def get_decel(self):
        return self.cmd_send('DC')

    def set_decel(self, decel):
        s, v = self.cmd_send('DC'+str(decel))
        if '?' in s:
            raise RuntimeError('Could not set deceleration')

    def get_vel(self):
        return self.cmd_send('VE')

    def set_vel(self, vel):
        s, v = self.cmd_send('VE'+str(vel))
        if '?' in s:
            raise RuntimeError('Could not set velocity')

    def get_accel_max(self):
        return self.cmd_send('MA')

    def set_accel_max(self, accel):
        s, v = self.cmd_send('MA'+str(accel))
        if '?' in s:
            raise RuntimeError('Could not set maximum acceleration')

    def get_emergency_decel(self):
        return self.cmd_send('AM')

    def set_emergency_decel(self, decel):
        s, v = self.cmd_send('AM'+str(decel))
        if '?' in s:
            raise RuntimeError('Could not set emergency deceleration')

    def get_current(self):
        return self.cmd_send('CC')

    def set_current(self, current):
        s, v = self.cmd_send('CC'+str(current))
        if '?' in s:
            raise RuntimeError('Could not set current')

    # Methods created by Ronan for reading and writing the current position to file
    def read_current_position(self):
        """
        Read latest position from persistence file
        """
        lines = open(self.persistence_file, 'r').readlines()
        posns = lines[0].strip().split(',')
        position = float(posns[0])
        return position

    def write_current_position(self, position):
        """
        Store new position in persistence file
        """
        new_line = '%9.4f,%25s\n' % (position, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if not os.path.exists(self.persistence_file):
            lines = [new_line]
        else:
            lines = [new_line] + open(self.persistence_file, 'r').readlines()
        if len(lines) >= 10:
            lines = lines[:10]
        open(self.persistence_file, 'w').writelines(lines)
        self.logger.info(new_line)


class Motor(MotorBase):
    def __init__(self, name, driver):
        super(Motor, self).__init__(name, driver)
        self.limits = (-31, 31)

    def _get_pos(self):
        return self.driver.read_current_position()

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
