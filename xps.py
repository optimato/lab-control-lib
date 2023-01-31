
from .base import MotorBase, SocketDriverBase, emergency_stop, DeviceException
from .network_conf import NETWORK_CONF
from .util.proxydevice import proxydevice, proxycall
from .util.logs import logger as rootlogger

__all__ = ['XPS1', 'XPS2', 'XPS3', 'Motor']

EOL = b',EndOfAPI'


@proxydevice()
class XPS(SocketDriverBase):
    """
    XPS Driver. Name and axis are defined in the subclasses below.
    """
    EOL = EOL

    def __init__(self, name, axis, device_address=None):
        self.axis = axis
        self.group = axis.split('.')[0]
        self.name = name
        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS

        self.monitor = XPSMonitor(device_address=device_address, axis=self.axis)

        super().__init__(device_address=device_address)

        # TODO
        self.metacalls.update({})

    def init_device(self):  # not "@proxycall"?
        """
        Device initialization.
        """
        pos = self.get_pos()
        self.logger.info(f'Motor at position {pos}')
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

        self.logger.debug(f'Sending command: {cmd}')

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
        """
        self.group_kill()
        self.group_initialize()
        self.home()

    @proxycall(admin=True)
    def group_kill(self):
        """
        Kill group
        """
        return self.send_cmd(f'GroupKill({self.group})')

    @proxycall(admin=True)
    def group_initialize(self):
        """
        Initialize group (no encoder reset)
        """
        return self.send_cmd(f'GroupInitializeNoEncoderReset({self.group})')

    @proxycall()
    def get_pos(self):
        """
        Call the monitor method in case the socket is blocked by a motion command
        """
        return self.monitor.get_pos()

    @proxycall(admin=True)
    def home(self, pos=None):
        """
        Home the motors: move to 0, then back to the target position pos.
        If pos is None, return to current positions.
        """
        pos = pos or self.get_pos()
        return self.send_cmd(f'GroupHomeSearchAndRelativeMove({self.group}, {pos})')

    @proxycall(admin=True)
    def move_abs(self, pos):
        """
        Move to requested position (mm)
        """
        return self.send_cmd(f'GroupMoveAbsolute({self.axis}, {pos})')

    @proxycall(admin=True)
    def move_rel(self, disp):
        """
        Move by requested displacement disp (mm)
        """
        return self.send_cmd(f'GroupMoveRelative({self.axis}, {disp})')


@proxydevice(address=NETWORK_CONF['xps1']['control'])
class XPS1(XPS):
    """
    Driver for motor 1
    """
    DEFAULT_DEVICE_ADDRESS = NETWORK_CONF['xps1']['device']
    DEFAULT_LOGGING_ADDRESS = NETWORK_CONF['xps1']['logging']

    def __init__(self, device_address=None):
        super().__init__(name='xps1', axis='Group1.Pos')


@proxydevice(address=NETWORK_CONF['xps2']['control'])
class XPS2(XPS):
    """
    Driver for motor 2
    """
    DEFAULT_DEVICE_ADDRESS = NETWORK_CONF['xps2']['device']
    DEFAULT_LOGGING_ADDRESS = NETWORK_CONF['xps2']['logging']

    def __init__(self, device_address=None):
        super().__init__(name='xps2', axis='Group2.Pos')


@proxydevice(address=NETWORK_CONF['xps3']['control'])
class XPS3(XPS):
    """
    Driver for motor 3
    """
    DEFAULT_DEVICE_ADDRESS = NETWORK_CONF['xps3']['device']
    DEFAULT_LOGGING_ADDRESS = NETWORK_CONF['xps3']['logging']

    def __init__(self, device_address=None):
        super().__init__(name='xps3', axis='Group3.Pos')


class XPSMonitor(SocketDriverBase):
    """
    A second pseudo-driver that connects only to probe real-time status.
    """

    DEFAULT_LOGGING_ADDRESS = None
    EOL = EOL

    def __init__(self, device_address, axis):
        self.axis = axis

        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS

        super().__init__(device_address=device_address)

    # Borrow methods defined above...
    send_cmd = XPS.send_cmd
    get_error_string = XPS.get_error_string

    def init_device(self):
        """
        Nothing to do here. It is assumed that the main class XPS has done all the
        initialization.
        """
        self.initialized = True

    def get_pos(self):
        """
        Get position of the group.
        """
        command = f'GroupPositionCurrentGet({self.axis}, double *)'
        self.logger.debug(f'Sending command: {command}')
        reply = self.send_cmd(command)
        return float(reply)


class Motor(MotorBase):

    def __init__(self, name, driver):  # removed axis parameter
        """
        Newport Motor. axis is the driver's channel
        """
        super(Motor, self).__init__(name, driver)

    def _get_pos(self):  # does this need to refer to XPSMonitor instead of XPS?
        """
        Return position in mm
        """
        return self.driver.get_pos()

    def _set_abs_pos(self, x):
        """
        Set absolute dial position
        """
        return self.driver.move_abs(x)

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.move_rel(x)
