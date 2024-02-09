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
import serial
import threading

from . import register_proxy_client
from .base import MotorBase, SocketDriverBase
from .network_conf import MICROSCOPE as NET_INFO
from .util.proxydevice import proxydevice, proxycall
from .util.future import Future

__all__ = ['Microscope']


@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class Microscope(SocketDriverBase):
    """
    Optique Peter microscope driver. Talks to tango box through pyserial.

    Much of the SocketDriverBase mechanics is the same, so we reuse this.
    """

    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    EOL = b'\r'                         # End of API sequence
    DEVICE_TIMEOUT = None               # Device socket timeout
    KEEPALIVE_INTERVAL = 10.            # Default Polling (keep-alive) interval
    logger = None
    REPLY_WAIT_TIME = 0.01              # Time before reading reply (needed for asynchronous connections)
    REPLY_TIMEOUT = 60.                 # Maximum time allowed for the reception of a reply

    LOCAL_DEFAULT_CONFIG = {'port_name':'COM3',
                            'baudrate':'57600',
                            'bytesize':8,
                            'parity':'N',
                            'stopbits':2,
                            'timeout':1,
                            'write_timeout':1
                            }
    DEFAULT_CONFIG = SocketDriverBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(LOCAL_DEFAULT_CONFIG)

    def __init__(self):
        """
        Connect to the TANGO control box.

        NOTE: there are only two axes enabled:
        Y: represents the focus
        Z: represents the scintillator wheel.
        """
        # Pass "fake" device address for logging purposes
        super().__init__(device_address=('localhost', self.config['port_name']))

        # TODO: add periodic call
        #self.periodic_calls.update({'status': (self.status, 10.)})

    def connect_device(self):
        """
        Device connection. Shadows SocketDriverBase.connect_device
        """
        # Prepare device socket connection
        # We call the Serial object a "socket" to reuse the
        # object in other calls
        self.device_sock = serial.Serial(port=self.config['port_name'],
                                        baudrate=self.config['baudrate'],
                                        bytesize=self.config['bytesize'],
                                        parity=self.config['parity'],
                                        stopbits=self.config['stopbits'],
                                        timeout=self.config['timeout'],
                                        write_timeout=self.config['write_timeout']
                                        )

        # Alias write -> sendall so that SocketDriverBase.device_cmd works also here
        self.device_sock.sendall = self.device_sock.write

        # Start receiving data
        self.recv_buffer = b''
        self.recv_flag = threading.Event()
        self.recv_flag.clear()
        self.recv_thread = Future(target=self._listen_recv)
        self.connected = True

    def _listen_recv(self):
        """
        This also shadows SocketDriverBase._listen_recv because we can't use
        select on the serial device.
        """
        while True:
            with self.recv_lock:
                d = self.device_sock.read_until(expected=self.EOL)
                self.recv_buffer += d
                self.recv_flag.set()
            if self.shutdown_requested:
                    break

    @proxycall(admin=True)
    def send_cmd(self, cmd: str, reply=True):
        """
        Send properly formatted request to the driver
        and parse the reply.

        If reply is False, do not expect a reply.

        EOL (\r) is appended to cmd so should not be part of cmd.
        """
        # Convert to bytes
        if type(cmd, str):
            cmd = cmd.encode()

        # Format arguments
        cmd += self.EOL

        resp = self.device_cmd(cmd, reply=reply)

        if resp is not None:
            return resp.decode('utf-8', errors='ignore')
        else:
            return None

    def init_device(self):
        """
        Initialization procedure for the microscope.
        """

        # read back some controller info to see if it is displayed correctly
        ver = self.send_cmd('?ver')

        # display output just for fun...
        self.logger.info(f'Tango controller version: {ver}')

        # check which axes are active. Enable Y and Z, disable X
        # 0 disables axis, but doesn't switch off motor
        # -1 disables axis and turns motor off
        self.logger.info('Enabling  motors...')
        reply = self.send_cmd('!axis -1 1 1', '?axis')
        self.logger.info(f'Axis status is {reply}')

    @proxycall()
    def focus_hl_status(self):
        """
        Return whether focus hard limits (low, high) are set
        """
        status_limit = self.send_cmd('?statuslimit')
        return status_limit[1] == 'A', status_limit[5] == 'D'

    @proxycall()
    def wheel_hl_status(self):
        """
        Return whether focus hard limits (low, high) are set
        """
        status_limit = self.send_cmd('?statuslimit')
        return status_limit[2] == 'A', status_limit[6] == 'D'

    @proxycall(admin=True)
    def home(self):
        """
        Find hard limits through homing.
        """
        # Each time TANGO is restarted, it needs to home the motors. It will store
        # 'hard limits' in its memory. The soft limits are for user definition within python.
        """
        self.send_cmd('!reset', reply=)
        time.sleep(5)
        """
        raise RuntimeError('This can break the scintillator wheel so currently deactivated')
