"""
Newport XPS control driver

This file is part of labcontrol-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import time

from .. import  proxycall, proxydevice
from ..base import MotorBase, SocketDriverBase, emergency_stop
from ..util import Future

EOL = b',EndOfAPI'


@proxydevice()
class XPS(SocketDriverBase):
    """
    XPS Driver. Name and axis are defined in the subclasses below.
    """
    EOL = EOL
    POLL_INTERVAL = 0.05     # temporization for rapid status checks during moves.


    def __init__(self, name, axis, device_address=None):
        self.axis = axis
        self.group = axis.split('.')[0]
        self.name = name
        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS

        # A second light-weight connection used for motion (blocking)
        self.motion = XPSMotion(device_address=device_address, axis=self.axis)

        super().__init__(device_address=device_address)

        self.metacalls.update({'position': self.get_pos})

        # Start periodic calls
        self.periodic_calls.update({'position': (self.get_pos, 20),
                                    'status' : (self.motion.get_pos, 20)})
        self.start_periodic_calls()

    def init_device(self):
        """
        Device initialization.
        """
        pos = self.get_pos()
        self.logger.info(f'Motor at position {pos}')
        self.initialized = True
        return

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

    @proxycall()
    def controller_status(self):
        """
        Controller status
        """
        self.send_cmd('ControllerStatusGet(int *)')

    @proxycall()
    def group_status(self):
        """
        Group status
        """
        self.send_cmd(f'GroupStatusGet({self.group}, int *)')
        
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
        Get position of the group.
        """
        reply = self.send_cmd(f'GroupPositionCurrentGet({self.axis}, double *)')
        return float(reply)

    @proxycall(admin=True)
    def home(self, pos=None):
        """
        Home the motors: move to 0, then back to the target position pos.
        If pos is None, return to current positions.
        """
        pos = pos or self.get_pos()
        return self.send_cmd(f'GroupHomeSearchAndRelativeMove({self.group}, {pos})')

    @proxycall(admin=True, block=False)
    def move_abs(self, pos):
        """
        Move to requested position (mm)
        """
        future = Future(self.motion.move_abs, args=(pos,))
        self.check_done()
        return future.result()

    @proxycall(admin=True, block=False)
    def move_rel(self, disp):
        """
        Move by requested displacement disp (mm)
        """
        future = Future(self.motion.move_rel, args=(disp,))
        self.check_done()
        return future.result()

    @proxycall(admin=True)
    def check_done(self):
        """
        Poll until movement is complete.
        """
        with emergency_stop(self.abort):
            while True:
                # query axis status
                moving = self.motion_status()
                if not moving:
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        self.logger.debug("Finished moving stage.")

    @proxycall(admin=True, interrupt=True)
    def abort(self):
        """
        Abort call
        """
        print('Calling motion abort')
        try:
            self.send_cmd(f'GroupMoveAbort({self.group})')
        except RuntimeError:
            # Error -27 means successfully aborted
            pass

    @proxycall()
    def motion_status(self):
        """
        Get current motion status
        0: not moving
        1: moving
        """
        return int(self.send_cmd(f'GroupMotionStatusGet({self.group}, int *)'))


class XPSMotion(SocketDriverBase):
    """
    A second pseudo-driver that connects to send blocking motion commands.
    """

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
        reply = self.send_cmd(f'GroupPositionCurrentGet({self.axis}, double *)')
        return float(reply)

    def move_rel(self, disp):
        """
        Move by requested displacement disp (mm). This call blocks until done or
        until motion is aborted
        """
        return self.send_cmd(f'GroupMoveRelative({self.axis}, {disp})')

    def move_abs(self, pos):
        """
        Move to requested position (mm)
        """
        return self.send_cmd(f'GroupMoveAbsolute({self.axis}, {pos})')


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
