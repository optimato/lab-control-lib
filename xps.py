
from .base import MotorBase, SocketDriverBase, emergency_stop, DeviceException
from .network_conf import XPS as NET_INFO
from .util.proxydevice import proxydevice, proxycall
from .util.logs import logger as rootlogger

__all__ = ['XPS', 'Motor']

EOL = b',EndOfAPI'


@proxydevice(address=NET_INFO['control'])
class XPS(SocketDriverBase):
    """
    XPS Driver
    """

    DEFAULT_DEVICE_ADDRESS = NET_INFO['device']
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    EOL = EOL
    DEVICE_TIMEOUT = 1

    def __init__(self, device_address=None):
        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS

        super().__init__(device_address=device_address)

        self.monitor = XPSMonitor()

        # Default group
        # TODO: understand what is the 'S' group

        # TODO
        self.metacalls.update({})

    def init_device(self):
        """
        Device initialization.
        """
        # pos = self.get_pos(0)
        # self.logger.info(f'Motor at position {pos}')
        self.initialized = True
        return

    def wait_call(self):
        """
        Keep-alive call
        """
        self.send_cmd('TODO')

    def send_cmd(self, cmd, parse_error=True):
        """
        Send command and parse reply
        """
        # Convert to bytes
        if isinstance(cmd, str):
            cmd = cmd.encode()
        cmd += self.EOL + b'\n'

        s = self.device_cmd(cmd)

        # Remove trailing EOL
        s = s[:-9].decode('ascii', errors='ignore')

        # Check if there are commas in the strings, then strip the values
        sl = s.split(',')

        code = int(sl[0])

        if not parse_error:
            return code, sl[1]

        if code == 0:
            return sl[1]
        elif code == -108:
            raise RuntimeError('TCP/IP connection closed by an administrator')
        else:
            error_string = self.get_error_string(code)
            raise RuntimeError(error_string)

    @property
    def groups(self):
        """
        Return list of group names
        """
        return self.config['groups']

    @groups.setter
    def groups(self, gr):
        self.config['groups'] = gr

    def get_error_string(self, error_code):
        """
        Get string explaining error code.

        do_raise = True will catch code != 0 to avoid recursive calls with send_cmd
        """
        code, error = self.send_cmd(f'ErrorStringGet({error_code}, char *)', parse_error=False)
        if code != 0:
            raise RuntimeError(f'Error {code}')
        return error

    @proxycall(admin=True)
    def recalibrate(self):
        """
        Kill group, reinitialize, and home.

        TODO: why 'S'?
        """
        self.group_kill(group='S')
        self.group_initialize(group='S')
        self.home(group='S')

    @proxycall(admin=True)
    def group_kill(self, group):
        """
        Kill group
        """
        return self.send_cmd(f'GroupKill({group})')

    @proxycall(admin=True)
    def group_initialize(self, group):
        """
        Initialize group (no encoder reset)
        """
        return self.send_cmd(f'GroupInitializeNoEncoderReset({group})')

    @proxycall()
    def group_get_pos(self, group, Nelem=1):
        """
        Get current position along given axis ['X', 'Y' or 'Z], or [0, 1, 2]
        TODO: understand when "Nelem" would not be 1.
        """
        command = f'GroupPositionCurrentGet({group}{", double *"*Nelem})'
        self.logger.debug(f'Sending command: {command}')
        reply = self.send_cmd(command)
        return tuple(float(x) for x in reply.split(','))

    @proxycall(admin=True)
    def home(self, group, pos=None):
        """
        Home the motors: move to (0,0,0), then back to the target position pos.
        If pos is None, return to current positions.
        """
        pos = pos or self.group_get_pos(group)
        pos_str = ', '.join([str(p) for p in pos])
        return self.send_cmd(f'GroupHomeSearchAndRelativeMove({group}, {pos_str})')

    @proxycall(admin=True)
    def group_move_abs(self, pos, group):
        """
        Move to requested position.
        """
        pos_str = ', '.join([str(p) for p in pos])
        return self.send_cmd(f'GroupMoveAbsolute({group}, {pos_str})')

    @proxycall(admin=True)
    def group_move_rel(self, displacement, group):
        """
        Move by requested displacement
        """
        disp_str = ', '.join([str(d) for d in displacement])
        return self.send_cmd(f'GroupMoveRelative({group}, {disp_str})')

    @proxycall()
    def get_pos(self, axis):
        """
        Get position of given axis.
        """
        group = self.group + self.AXIS_LABELS[axis]
        return self.group_get_pos(group)

    @proxycall(admin=True)
    def move_abs(self, pos, axis):
        """
        Move one specific axis to given position.
        """
        group = self.group + self.AXIS_LABELS[axis]
        return self.group_move_abs(pos, group)

    @proxycall(admin=True)
    def move_rel(self, disp, axis):
        """
        Move one specific axis by given displacement.
        """
        group = self.group + self.AXIS_LABELS[axis]
        return self.group_move_rel(disp, group)

class XPSMonitor(SocketDriverBase):
    """
    A second pseudo-driver that connects only to probe real-time status.
    """

    DEFAULT_DEVICE_ADDRESS = NET_INFO['device']
    DEFAULT_LOGGING_ADDRESS = None
    EOL = EOL

    def __init__(self, device_address=None):

        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS

        super().__init__(device_address=device_address)

        # Make logger child of main driver
        self.logger = rootlogger.getChild('XPS.' + self.__class__.__name__)

    # Borrow methods defined above...
    send_cmd = XPS.send_cmd
    get_error_string = XPS.get_error_string

    def init_device(self):
        """
        Nothing to do here. It is assumed that the main class XPS has done all the
        initialization.
        """
        self.initialized = True

    def group_get_pos(self, group, Nelem):
        """
        Get position of all `Nelem` elements of the group `group`.
        """
        command = f'GroupPositionCurrentGet({group}{", double *"*Nelem})'
        self.logger.debug(f'Sending command: {command}')
        reply = self.send_cmd(command)
        return tuple(float(x) for x in reply.split(','))

class Motor(MotorBase):

    def __init__(self, name, driver, axis):
        """
        Newport Motor. axis is the driver's channel
        """
        super(Motor, self).__init__(name, driver)
        self.axis = axis

    def _get_pos(self):
        """
        Return position in mm
        """
        return self.driver.get_pos(self.axis)

    def _set_abs_pos(self, x):
        """
        Set absolute dial position
        """
        return self.driver.move_abs(self.axis, x)

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.move_rel(self.axis, x)
