"""
Mecademic meca500 interface

TODO: more documentation here.
"""

import numpy as np
import time

from .base import MotorBase, DriverBase, SocketDeviceServerBase, admin_only, emergency_stop, DeviceDisconnectException
from .network_conf import MECADEMIC as DEFAULT_NETWORK_CONF
from . import motors
from .ui_utils import ask_yes_no
from . import conf_path

__all__ = ['MecademicDaemon', 'Mecademic']#, 'Motor']

# This API uses null character (\0) as end-of-line.
EOL = b'\0'

# Default joint velocity: 25% of maximum ~= 90 degrees / s
DEFAULT_VELOCITY = 25


class RobotException(Exception):
    def __init__(self, code, message=''):
        self.code = code
        self.message = f'{code}: {message}'
        super().__init__(self.message)


class MecademicDaemon(SocketDeviceServerBase):
    """
    Mecademic Daemon, keeping connection with Robot arm.
    """

    EOL = EOL

    def __init__(self, serving_address=None, device_address=None):
        if serving_address is None:
            serving_address = DEFAULT_NETWORK_CONF['DAEMON']
        if device_address is None:
            device_address = DEFAULT_NETWORK_CONF['DEVICE']
        super().__init__(serving_address=serving_address, device_address=device_address)

    def init_device(self):
        """
        Device initialization.
        """
        # ask for firmware version to see if connection works
        version = self.device_cmd(b'GetFwVersion' + self.EOL)
        version = version.decode('ascii').strip()
        self.logger.debug(f'Firmware version is {version}')

        self.initialized = True
        return

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.device_cmd('GetStatusRobot')
        if not r:
            raise DeviceDisconnectException


class Mecademic(DriverBase):
    """
    Driver for the Meca500 robot arm

    TODO: a good way to define limits, ranges, etc.
    """

    EOL = EOL
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.

    DEFAULT_JOINT_POSITION = (0.0,
                              -20.37038014,
                              16.28988378,
                              0.0,
                              -(90 + -20.37038014 + 16.28988378),
                              0.0)

    # theta 1 range can be quite dangerous.
    DEFAULT_JOINT_LIMITS = ((-10., 10.),
                            (-21., 17.),
                            (-45, 15),
                            (-2., 2.),
                            (-112., -24),
                            (-360., 360.))

    def __init__(self, address, admin=True):
        """
        Initialise Mecademic driver (robot arm).
        """
        super().__init__(address=address, admin=admin)

        # Set time
        self.set_RTC()

        # 1. Check current state and prompt for activation/homing
        #########################################################
        status = self.get_status()
        if status[3]:
            # Error mode
            if ask_yes_no('Robot in error mode. Clear?'):
                self.clear_error()
            else:
                self.logger.warning('Robot still in error mode after driver initialization.')
                return
        if not status[0]:
            # Not activated

            # Set joint limits
            self.set_joint_limits(self.DEFAULT_JOINT_LIMITS)

            if ask_yes_no('Robot not activated. Activate?'):
                self.activate()
            else:
                self.logger.warning('Robot not activated after driver initialization')
                return
        if not status[1]:
            # Not homed
            if ask_yes_no('Robot not homed. Home?'):
                self.home()
            else:
                self.logger.warning('Robot not homed after driver initialization.')
                return

        # Other important initialization steps
        ######################################

        # Move to "default" original position

        # Configuration (posture)
        code, reply = self.send_cmd('Home')
        if code == 2003:
            # Already homed
            self.logger.warning(reply)
        else:
            self.logger.info(reply)
        return


        # TODO: create pseudo-motors

        self.logger.info(f"{self.name} initialization complete.")
        self.initialized = True

    def send_cmd(self, cmd, args=None):
        """
        Send properly formatted request to the driver
        and parse the reply.
        Replies from the robot are of the form [code][data].
        This method returns a list of tuples (int(code), data)

        args, if not none is tuple of arguments to pass as arguments
        to the command.

        cmd can be a single string, or a list of strings if multiple
        commands are to be sent in a batch. In this case, args
        should be a list of the same length.
        """
        # This looks complicated because we need to manage the
        # case of multiple commands. So in the case of single command.
        # we convert to a list with a single element.
        if isinstance(cmd, str):
            cmds = [cmd.encode()]
            args = [args]
        else:
            cmds = [c.encode() for c in cmd]
            if len(cmds) != len(args):
                raise RuntimeError('Length of command and args lists differ.')

        # Format arguments
        cmd = b''
        for c, arg in zip(cmds, args):
            if arg is not None:
                try:
                    arg = tuple(arg)
                except TypeError:
                    arg = (arg, )
                cmd += f'{arg}'.encode() + self.EOL
        reply = self.send_recv(cmd)
        return self.process_reply(reply)

    def process_reply(self, reply):
        """
        Take care of stripping and splitting raw reply from device
        Raise error if needed.
        """
        # First split along EOL in case there are more than one reply
        raw_replies = reply.split(self.EOL)[:-1]
        # Convert each
        formatted_replies = []
        for r in raw_replies:
            r_str = r.decode('ascii', errors='ignore')
            code, message = r_str.strip('[]').split('][')
            code = int(code)
            formatted_replies.append((code, message))

        # Manage errors and other strange things here
        reply2000 = None
        for code, message in formatted_replies:
            if code < 2000:
                # Error code. No point continuing
                raise RobotException(code, message)
            if code > 2999:
                # Status message sent "out of the blue"
                self.logger.warning(f'{code}: {message}')
            else:
                rep = (code, message)
                if reply2000 is not None:
                    # This should not happen
                    self.logger.critical('Received more than one code 2000:\n'
                                         + f'{reply2000:s}\n'
                                         + 10*'-'
                                         + '\n'
                                         + f'{rep:s}')
                reply2000 = rep

        return reply2000

    def get_status(self):
        """
        Get robot current status

        From documentation:
        [2007][as, hs, sm, es, pm, eob, eom]
        as: activation state (1 if robot is activated, 0 otherwise);
        hs: homing state (1 if homing already performed, 0 otherwise);
        sm: simulation mode (1 if simulation mode is enabled, 0 otherwise);
        es: error status (1 for robot in error mode, 0 otherwise);
        pm: pause motion status (1 if robot is in pause motion, 0 otherwise);
        eob: end of block status (1 if robot is idle and motion queue is empty, 0 otherwise);
        eom: end of movement status (1 if robot is idle, 0 if robot is moving).
        """
        code, reply = self.send_cmd('GetStatusRobot')
        return [bool(int(x)) for x in reply.split(',')]

    @admin_only
    def set_RTC(self, t=None):
        """
        Set time. Not clear if there's a reason to set something else
        than current time...
        """
        if t is None:
            t = time.time()
        # Send two command (the first one doesn't return anything
        code, message = self.send_cmd(['SetRTC', 'GetRTC'], [t, None])
        return

    @admin_only
    def home(self):
        """
        Home the robot
        """
        code, reply = self.send_cmd('Home')
        if code == 2003:
            # Already homed
            self.logger.warning(reply)
        else:
            self.logger.info(reply)
        return

    @admin_only
    def activate(self):
        """
        Activate the robot
        """
        code, reply = self.send_cmd('ActivateRobot')
        if code == 2001:
            # Already activated
            self.logger.warning(reply)
        else:
            self.logger.info(reply)
        return

    @admin_only
    def deactivate(self):
        """
        Deactivate the robot
        """
        code, reply = self.send_cmd('DeactivateRobot')
        self.logger.info(reply)
        return

    @admin_only
    def clear_errors(self):
        """
        Clear error status.
        """
        code, reply = self.send_cmd('ResetError')
        if code == 2006:
            # Already activated
            self.logger.warning(reply)
        else:
            self.logger.info(reply)
        return

    @admin_only
    def move_joints(self, joints):
        """
        Move joints
        """
        # Send two commands because 'MoveJoints' doesn't immediately
        # return something
        code, reply = self.send_cmd(['MoveJoints', 'GetStatusRobot'], [joints, None])
        self.check_done()
        return self.get_joints()

    def get_joints(self):
        """
        Get current joint angles.

        The manual says that GetRtJointPos is better than GetJoints
        """
        code, reply = self.send_cmd('GetRtJointPos')
        joints = [float(x) for x in reply.split(',')]
        # Drop the first element (timestamp)
        return joints[1:]

    @admin_only
    def move_pose(self, pose):
        """
        Move to pose given by coordinates (x,y,z,alpha,beta,gamma)
        """
        # Send two commands because 'MovePose' doesn't immediately
        # return something
        code, reply = self.send_cmd(['MovePose', 'GetStatusRobot'], [pose, None])
        self.check_done()
        return self.get_pose()

    def get_pose(self):
        """
        Get current pose (x,y,z, alpha, beta, gamma)
        """
        code, reply = self.send_cmd('GetRtCartPos')
        pose = [float(x) for x in reply.split(',')]
        # Drop the first element (timestamp)
        return pose[1:]

    def check_done(self):
        """
        Poll until movement is complete.

        Implements emergency stop
        """
        with emergency_stop(self.abort):
            while True:
                # query axis status
                status = self.get_status()
                if status[6]:
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        self.logger.info("Finished moving robot.")

    @admin_only
    def move_to_default_position(self):
        """
        Move to the predefined default position.

        TODO: maybe we will have more than one of those.
        """
        self.move_joints(self.DEFAULT_JOINT_POSITION)

    def get_joint_limits(self):
        """
        Get current joint limits.
        """
        limits = []
        for i in range(6):
            code, message = self.send_cmd('GetJointLimits', i+1)
            # message is of the form n, low, high
            s = message.split(',')
            limits.append((float(s[1]), float(s[2])))
        return limits

    @admin_only
    def set_joint_limits(self, limits):
        """
        Set joint limits. This must be done before robot activation.

        Since this is a critical operation, the user is prompted,
        and the default is no.
        """
        if not self.isactive:
            self.logger.error('Cannot set limits when robot is active.')
            return

        # Check if limits are already set
        current_limits = self.get_joint_limits()
        if np.allclose(current_limits, limits, atol=.1):
            self.logger.info("Limits are already set.")
            return

        # Ask user to confirm
        prompt = 'Preparing to change joint limits as follows:\n'
        for i, (low, high) in enumerate(limits):
            prompt += f' * theta {i+1}: ({low:9.5f}, {high:9.5f})\n'
        prompt = 'Are you sure you want to proceed?'
        if not ask_yes_no(prompt, yes_is_default=False):
            self.logger.error('Setting limit cancelled.')
            return

        for i, (low, high) in enumerate(limits):
            code, message = self.send_cmd('SetJointLimits', (i+1, low, high))

        self.logger.info("Joint limits have been changed.")
        return

    def abort(self):
        """
        Abort current motion.

        TODO: check what happens if this is called while robot is idle.
        """
        # Abort immediately
        self.logger.warning('Aborting robot motion!')
        code, message = self.send_cmd('ClearMotion')

        # Ready for next move
        code, message = self.send_cmd('ResumeMotion')

    @property
    def isactive(self):
        return self.get_status()[0] == 1