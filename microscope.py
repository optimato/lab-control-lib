"""
Optique Peter microscope driver

Old docstring with a lot of important information:
'''
Communication with the TANGO controller for the Optique Peter microscope through
a socket.
version 0 17.03.2017, Hans
- get_pos_focus --> gets the current position of focus axis
- get_soft_lim_focus --> reads back python internal soft limits of focus axis
- set_soft_lim_focus --> sets python internal soft limits of focus axis
- get_hard_lim_focus --> reads back hard limits of focus axis
- move_rel_focus --> moves focus axis relative
- move_abs_focus --> moves focus axis absolute
- move_rel_scinti --> moves scintillator wheel relative
- move_to_lo_position_focus --> moves focus axis to low soft limit
- move_to_hi_position_focus --> moves focus axis to high soft limit
- move_to_center_position_focus --> moves focus to center position between lo and hi HARD limits

version 0.1 08.11.2017, Hans
pysertial was not connecting anymore, instead throwing an error about hardware
flow control. Fixed by adding "dsrdtr=True,rtscts=True" to the create serial
function.
something is wrong with motor speed or acceleration. When initializing directly
from python, the focus (and scinti wheel) do not move. The motors seem to have
insufficient torque to drive the stagesself.
Starting the SwitchBoard software on the camserver and loading the .ini file
with "good" settings fixes the problem. Need to implement slow enough movement
and accel. here in the init function to allow the stages to move at all
a vel of 0.3 is too much, 0.1 seems to work fine, need to fine tune this (tomorrow...)
version 1.0 20.12.2017 Hans
changed communication from serial (pyserial) to socket, which gets rid of the
need to create a virtual serial device on the local machine

The control box is set up for three axes, although we have only two:
X(1) axis: camera rotation (not used)
Y(2) axis: focus
Z(3) axis: scintillator mount
The instruction set has its own syntax, and the python module pyserial takes
care of transmitting them.
Most important parameters like motor properties and speeds are stored in the
TANGO box. These should not be tinkered with.

----------------------
Instruction syntax:
----------------------
The instructions and parameters are sent as ASCII strings with a terminating
carriage return [CR], which is 0x0d hex. Characters should be lower case, but
upper and camel-case are also accepted. The parameters are separated by a space
character. This provides easy access to all functions by using a simple terminal
program such as HyperTerminal. A typical instruction syntax is as follows:
[!,?][instruction][SP][optional axis] [parameter1][SP][parameter2] [etc...] [CR]
[!,?] Read/write specifier, required by most instructions **:
! (exclamation mark) = to write parameter, execute an instruction etc.
? (question mark) = to read data (returns settings, or status, etc.)
[instruction] : Is the instruction word itself.
[SP] : Space (ASCII 0x20 hex) as separation.
[optional axis] : Axis character x, y, z or a if only one axis must be
addressed.
[parameter] : Usually integer or floating point numbers, floating point uses
decimal point, no comma.
[CR] : Termination (ASCII 0x0d hex), causes instruction execution.
A read instruction may return more than one parameter. In many cases the
number of returned parameters depends on the amount of available axes:
[axis X] [if available: axis Y] [if available: axis Z] [if available: axis A]

Example: read or set the velocity of the x axis:
    '?vel x\r' sends the command "retrieve the velocity setting for x axis"
               To get the value, need to read the output from the port with
               read(nbits) or read_all(), see below
    '!vel x 1\r' sets the velocity setting for x axis to 1

----------------------
Translation to python
----------------------
To open a port use:
   COMPORT to TCP port forwarding on the camserver
baudrate, bytesize, stopbits and parity should take the values above, as these
are needed to talk to the TANGO.
timeout sets a read timeout, leave as none since socket takes care of this.
For further detail refer to socket documentation

Send and recieve strings:
The function sendall(str) sends the string str to the Controller.
the function recv(nbits) reads and returns nbits from the socket.
ATTENTION!!!
after sending a string, a readback should always be performed to check the
status.
ATTENTION!!!
Writing is fine, as python will always wait till the full string was sent to
the port. Reading timing is tricky, as it might take some time for the return
string to arrive. This must be taken into consideration
'''

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import socket
import os
import time
import logging
import threading

from .util.uitools import ask_yes_no

logger = logging.getLogger("Microscope driver")


import time

from . import register_proxy_client
from .base import MotorBase, SocketDriverBase, emergency_stop, DeviceException
from .network_conf import AEROTECH as NET_INFO
from .util.proxydevice import proxydevice, proxycall

__all__ = ['Microscope', 'Motor']

@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class Microscope(SocketDriverBase):
    """
    Optique Peter microscope driver. Talks to tango box througy pyserial.
    """
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    EOL = b'\n'

    def __init__(self):
        """
        Connect to the TANGO control box.
        """

        self.periodic_calls.update({'status': (self.status, 10.)})

        super().__init__()

        # self.metacalls.update({'focus': self.get_focus})

        """
        # some variables that will be used by other functions
        self.cal_done_y = False
        self.rm_done_y = False
        self.hard_limit_lo_y = None  # store maximum possible values for soft limits
        self.hard_limit_hi_y = None
        self.soft_limit_lo_y = None  # store soft limits
        self.soft_limit_hi_y = None
        self.pos_y = None  # current motor position
        self.pos_z = None
        self.timeout_t = 30
        """


        logger.info('Initializing microscope')

        # open the port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout_t)

        # connect
        conn_errno = self.sock.connect_ex((host, port))
        retry_count = 0 # counter for retries, limit to 10 retries
        while conn_errno != 0:
            print(os.strerror(conn_errno))
            time.sleep(.05)
            conn_errno = self.sock.connect_ex((host,port))
            retry_count += 1
            if retry_count > 10:
                print('connection refused, aborting...')
                return

        # read back some controller info to see if it is displayed correctly
        ver = self._send_cmd('?ver')

        # display output just for fun...
        logger.info('Tango controller %s' % ver)

        # check which axes are active. Enable Y and Z, disable X
        # 0 disables axis, but doesnt switch off motor
        # -1 disables axis and turns motor off
        logger.info('Enabling  motors...')
        self._send_cmd('!axis -1 1 1', reply=False)

        # read back axis status
        axis_active = self._send_cmd('?axis')
        logger.info('Axis status is %s' % axis_active)

        # check if the axes are already calibrated before driving
        status_limit = self._send_cmd('?statuslimit')
        # The status information is arranged in 4 groups.
        # The ASCII character string positions are:
        #  0 ...  3: Group 1 => cal state of axis 0-3 (x,y,z,a) '-' or 'A'
        #  4 ...  7: Group 2 => rm state of axis 0-3 (x,y,z,a) '-' or 'D'
        #  8 ... 11: Group 3 => lower soft limit state of axis 0-3 (x,y,z,a) -,L
        # 12 ... 15: Group 4 => upper soft limit state of axis 0-3 (x,y,z,a) -,L
        #
        # We want y-axis
        is_y_cal = status_limit[1]
        is_y_rm = status_limit[5]
        is_y_sl_lo = status_limit[9]
        is_y_sl_hi = status_limit[13]
        # and z axis which has only a lower limit switch (cal)
        # however this is ignored

        # print status
        y_cal_set = (is_y_cal == 'A')
        y_rm_set = (is_y_rm == 'D')
        logger.info('Focus low hard limit is ' + ('' if y_cal_set else 'not') + ' set')
        logger.info('Focus high hard limit is ' + ('' if y_rm_set else 'not') + ' set')

        # Each time TANGO is restarted, it needs to home the motors. It will store
        # 'hard limits' in its memory. The soft limits are for user definition within python.
        if not y_cal_set or not y_rm_set:
            reset = ask_yes_no("""Hard limits not set. Perform initialization?
            ATTENTION!!! Please remove scintillator cap before proceeding!!!""",
                               yes_is_default=False,
                               help="""This will result in a !reset command being sent to the control box,
               which will force a restart similar to a power on.
               The controller will be unresponsive for a couple of seconds,
               then start re-initialization.""")

            if not reset:
                logger.warn('Homing not performed.')
                return
            else:
                logger.warn('Resetting...')
                self._send_cmd('!reset', reply=False)
                # wait a bit for the controller to respond again
                time.sleep(5)
                # Proceed with calibration...
                self._perform_focus_calibration()

        # read and store the soft limits
        lim = self._send_cmd('?lim y')
        self.soft_limit_lo_y, self.soft_limit_hi_y = [float(x) for x in lim.split()]

        # hard_limits are set only if homing was performed
        if self.hard_limit_lo_y is None:
            self.hard_limit_lo_y = self.soft_limit_lo_y
        if self.hard_limit_hi_y is None:
            self.hard_limit_hi_y = self.soft_limit_hi_y
        assert self.soft_limit_hi_y <= self.hard_limit_hi_y
        assert self.soft_limit_lo_y >= self.hard_limit_lo_y

        # Current focus position
        self.pos_y = self.get_pos_focus()

    def _send_cmd(self, cmd, reply=True):
        """
        Send command through socket and return reply if reply=True
        """
        r = None
        with self._lock:
            self.sock.sendall(cmd + '\r')
            if reply:
                r = self.sock.recv(128)
                while r[-1:] != '\r':
                    r += self.sock.recv(128)
        return r

    def _perform_focus_calibration(self):
        """
        Drive the focus (TANGO y axis) to lower and higher limit switches for calibration
        TANGO should software limit 100 um away from the lower limit switch and
        sets the absolute 0 position there.
        The motor will drive very slowly, and there is a hard timeout limit of 120 s.
        """
        # set socket to non-blocking while driving calibration
        self.sock.settimeout(None)
        logger.info('Driving focus-axis to lower limit switch...')
        while True:
            res = self._send_cmd('!cal y')
            # this returns: 'A' after a successful calibration or
            #               'E' if an error occurred (cal was unsuccessful)
            #               'T' if a timeout occurred (cal was unsuccessful)
            #               '-' the axis is not present
            res = res[1]  # only y-axis
            if res == 'A':
                # Success
                logger.info('Successfully reached lower limit')
                focus_pos = self._send_cmd('?pos y')
                self.hard_limit_lo_y = float(focus_pos)
                break
            elif res == 'T':
                # Time out. Try again.
                logger.warn('Focus lower limit calibration timed out, retrying...')
            elif res == 'E':
                # An error occurred, get error
                h = self._send_cmd('?help')
                # reset timeout before raising
                self.sock.settimeout(self.timeout_t)
                raise RuntimeError(h)
            else:
                # reset timeout before raising
                self.sock.settimeout(self.timeout_t)
                raise RuntimeError('Unknown error. "!cal y" returned "%s".' % res)

        # High limit
        logger.info('Driving focus-axis to higher limit switch...')
        while True:
            res = self._send_cmd('!rm y')
            # this returns: 'A' after a successful calibration or
            #               'E' if an error occurred (cal was unsuccessful)
            #               'T' if a timeout occurred (cal was unsuccessful)
            #               '-' the axis is not present
            res = res[1]  # only y-axis
            if res == 'D':
                logger.info('Successfully reached higher limit')
                focus_pos = self._send_cmd('?pos y')
                self.hard_limit_hi_y = float(focus_pos)
                break
            elif res == 'T':
                # move timeout, drive again
                logger.warn('Focus higher limit calibration timed out, retrying...')
            elif res == 'E':
                # an error occurred, get error
                h = self._send_cmd('?help')
                # reset timeout
                self.sock.settimeout(self.timeout_t)
                raise RuntimeError(h)
            else:
                # reset timeout
                self.sock.settimeout(self.timeout_t)
                raise RuntimeError('Unknown error. "!rm y" returned "%s".' % res)

        # reset timeout
        self.sock.settimeout(self.timeout_t)

        # Recenter focus
        self.move_to_center_position_focus()

        return

    def hard_lim_focus(self):
        """
        Focus hard limits
        """
        return self.hard_limit_lo_y, self.hard_limit_hi_y

    def get_soft_lim_focus(self):
        """
        Get the soft limits of the focus motor.
        ATTENTION! This gets the python internal soft limits.
        It does NOT read the soft limits inside the Tango controller!
        """
        return self.soft_limit_lo_y, self.soft_limit_hi_y

    def set_soft_lim_focus(self, lo=None, hi=None):
        """
        Set the soft limits of the focus motor.
        ATTENTION! This sets the python internal soft limits.
        It does NOT change the soft limits inside the Tango controller!
           Example:
               self.soft_lim_focus(lo=0.5) sets lower limit to 0.5 mm
        """
        if lo is not None:
            if type(lo) is not float and type(lo) is not int:
                raise RuntimeError('Invalid input "%s" for low soft limit.' % lo)
            if lo < self.hard_limit_lo_y:
                raise RuntimeError('Low limit out of bounds')
            self.soft_limit_lo_y = lo

        if hi is not None:
            if type(lo) is not float and type(lo) is not int:
                raise RuntimeError('Invalid input "%s" for high soft limit.' % hi)
            if hi > self.hard_limit_hi_y:
                raise RuntimeError('Low limit out of bounds')
            self.soft_limit_hi_y = hi

    def get_pos_focus(self):
        """
        Read the current position of the focus from the controller
        """
        # get position from hardware
        pos = self._send_cmd('?pos y')
        self.pos_y = float(pos)
        return self.pos_y

    def move_to_center_position_focus(self):
        """
        Move the microscope to the center between low and high hard limits.
        Will perform move even if outside of soft limits (needs user confirmation)!!!
        """
        # check if center position is outside of soft limits# prompt for user confirmation if it is
        center_pos = (self.hard_limit_lo_y + self.hard_limit_hi_y) / 2.
        if center_pos < self.soft_limit_lo_y or center_pos > self.soft_limit_hi_y:
            logger.warn('Center position outside soft limits')
            if not ask_yes_no("Center position outside soft limits. Proceed anyway?", yes_is_default=False):
                logger('Aborted move to center position')
                return

        # Proceed
        self.sock.settimeout(None)
        print('moving focus to center position...')
        while True:
            status = self._send_cmd('!moc y')[1]
            # check if successful
            if status == '@':
                # success
                # reset timeout
                self.sock.settimeout(self.timeout_t)
                return
            elif status == 'T':
                logger.warn('Move timeout, retrying...')
            elif status == 'E':
                h = self._send_cmd('?help')
                # reset timeout
                self.sock.settimeout(self.timeout_t)
                raise RuntimeError(h)
            else:
                # reset timeout
                self.sock.settimeout(self.timeout_t)
                raise RuntimeError('Unknown error. "!moc y" returned "%s".' % status)

    def move_abs_focus(self, y):
        """
        Move the focus absolute, units in [mm]
        """
        # check if input is a scalar
        if type(y) is not int and type(y) is not float:
            raise RuntimeError('Invalid input %s.' % y)

        # check if value is within limits
        if y < self.soft_limit_lo_y or y > self.soft_limit_hi_y:
            raise RuntimeError('Move value outside bounds.')

        moay = self._send_cmd('!moa y %s' % y)
        if moay[1] == '@':
            # success. store new positions
            self.pos_y = y
            return self.pos_y
        elif moay[1] == 'E':
            # get error description
            h = self._send_cmd('?help')
            raise RuntimeError(h)
        else:
            raise RuntimeError('Unknown error. "!moa y" returned %s' % moay[1])

    def move_to_lo_position_focus(self):
        """
        Move focus to high software limit
        """
        return self.move_abs_focus(self.soft_limit_lo_y)

    def move_to_hi_position_focus(self):
        """
        Move focus to high software limit
        """
        return self.move_abs_focus(self.soft_limit_hi_y)

    def move_rel_focus(self, dy):
        """
        Move the focus relative, units in [mm]
        """
        return self.move_abs_focus(self.get_pos_focus() + dy)


    def move_rel_scinti(self, deg):
        """
        Move the scintillator wheel relative, units in [deg]

        TODO: figure out exactly the relation between motor steps and position.
        For the moment (after quick test), assume 4132 motor revolutions are needed
        per 360 rotation. Each revolution has 59648 (micro-) steps.

        ATTENTION! These numbers do not really mean anything, as I got them from the
        SwitchBoard software. They make the motor work with the Joystick, however it
        is unclear what the actual motor specs are and the gear to scintillator wheel.
        """
        # check if input is a scalar
        if type(deg) is not int and type(deg) is not float:
            raise RuntimeError('Invalid input: %s.' % deg)

        # check if objective are moved back
        if not ask_yes_no('Is the objective moved back (needed for 20x and 40x)?', yes_is_default=False):
            print('Aborted')
            return

        # Move.
        # For the scinti wheel modulo mode is active, meaning no limit switches.
        # Motor position seems to go from 0 to about 246465536. Using relative
        # movement here instead of absolute ,removes the need for modulo calculation.
        # Transform input (deg) into motor steps
        mostp_z = int(deg*246465536/360.)
        morz = self._send_cmd('!mor z %s' % mostp_z)
        if morz[2] == '@':
            # success
            pass
        elif morz[1] == 'E': # error
            # get error description
            h = self._send_cmd('?help')
            raise RuntimeError(h)
        else:
            raise RuntimeError('Unknown error. "!mor z" returned %s' % morz[2])

        # get absolute pposition of the scinti wheel
        # not sure if this is useful or even works, needs testing
        pos = self._send_cmd('?pos z')
        self.pos_z = float(pos)
        return self.pos_z
