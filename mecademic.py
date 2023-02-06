"""
Mecademic meca500 interface

TODO: more documentation here.

TODO: how to deal with pseudomotors.
Especially: pseudo motors that emulate translation of the sample
wrt the axis of rotation.

TODO: how to better define "free moving zones".


"""
import logging
import time
import socket
import os
import threading

from . import register_proxy_client
from .base import MotorBase, SocketDriverBase, emergency_stop, DeviceException, _recv_all
from .network_conf import MECADEMIC as NET_INFO, MECADEMIC_MONITOR
from .util.uitools import ask_yes_no
from .util.future import Future
from .util.proxydevice import proxydevice, proxycall
from .datalogger import datalogger

__all__ = ['Mecademic', 'create_motors', 'MecademicMonitor']#, 'Motor']

logtags = {'type': 'motion',
           'branch': 'long',
           'device_ip': NET_INFO['device'][0],
           'device_port': NET_INFO['device'][1]
          }


# This API uses null character (\0) as end-of-line.
EOL = b'\0'

# Default joint velocity: 5% of maximum ~= 18 degrees / s
DEFAULT_VELOCITY = 5

MAX_JOINT_VELOCITY = [150., 150., 180., 300., 300., 500.]


class RobotException(Exception):
    def __init__(self, code, message=''):
        self.code = code
        self.message = f'{code}: {message}'
        super().__init__(self.message)


class MecademicMonitor:
    """
    Light-weight class that connects to the monitor port.
    """

    EOL = EOL
    DEFAULT_MONITOR_ADDRESS = MECADEMIC_MONITOR['device']
    MONITOR_TIMEOUT = 1
    NUM_CONNECTION_RETRY = 10
    MAX_BUFFER_LENGTH = 1000

    def __init__(self, monitor_address=None):

        if monitor_address is None:
            monitor_address = self.DEFAULT_MONITOR_ADDRESS

        self.logger = logging.getLogger(self.__class__.__name__)

        # Store device address
        self.monitor_address = monitor_address
        self.monitor_sock = None

        # Buffer in which incoming data will be stored
        self.recv_buffer = None
        # Flag to inform other threads that data has arrived
        self.recv_flag = None
        # Listening/receiving thread
        self.recv_thread = None

        # dict of received messages (key is message code)
        self.messages = []

        self.shutdown_requested = False

        # Start with empty message
        self.message = {}

        # Connect to device
        self.connected = False

    def start(self):
        """
        Device connection
        """
        # Prepare device socket connection
        self.monitor_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.monitor_sock.settimeout(self.MONITOR_TIMEOUT)

        for retry_count in range(self.NUM_CONNECTION_RETRY):
            conn_errno = self.monitor_sock.connect_ex(self.monitor_address)
            if conn_errno == 0:
                break

            self.logger.critical(os.strerror(conn_errno))
            time.sleep(.05)

        if conn_errno != 0:
            self.logger.critical("Can't connect to device")
            raise DeviceException("Can't connect to device")

        # Start receiving data
        self.recv_buffer = b''
        self.recv_flag = threading.Event()
        self.recv_flag.clear()
        self.recv_thread = threading.Thread(target=self._listen_recv)
        self.recv_thread.daemon = True
        self.recv_thread.start()

        self.connected = True

    def _listen_recv(self):
        """
        This threads receives all data in real time and stores it
        in a local buffer. For devices that send data only after
        receiving a command, the buffer is read and emptied immediately.
        """
        while True:
            if self.shutdown_requested:
                break
            d = _recv_all(self.monitor_sock, EOL=self.EOL)
            self.recv_buffer += d
            self.consume_buffer()
            #self.dump_buffer(f)

    def callback(self, g):
        return

    def callback_print(self, g):
        """
        print content of group
        """
        print(g)

    def consume_buffer(self):
        """
        Parse buffered messages - running on the same thread as _listen_recv.
        """
        tokens = self.recv_buffer.split(EOL)
        g = {}
        for t in tokens:
            ts = t.decode('ascii', errors='ignore')
            if not ts:
                # New group
                self.message = g
                self.callback(g)
                g = {}
            try:
                code, message = ts.strip('[]').split('][')
            except:
                code = 0
                message = ts
            code = int(code)
            g[code] = message
        self.recv_buffer = b''

    def shutdown(self):
        self.shutdown_requested = True


class MecademicMonitorLog(MecademicMonitor):

    def __init__(self, filename, monitor_address=None):
        super().__init__(monitor_address=monitor_address)
        self.filename = filename

    def callback(self, g):
        """
        Save time and joints 
        """
        with open(self.filename, 'at') as f:
            if 2230 not in g:
                return
            f.write(f'{g[2230]}, {g[2026]}\n')


@register_proxy_client
@proxydevice(address=NET_INFO['control'])
class Mecademic(SocketDriverBase):
    """
    Mecademic robot arm driver

    TODO: a good way to define limits, ranges, etc.
    """

    DEFAULT_DEVICE_ADDRESS = NET_INFO['device']
    EOL = EOL
    KEEPALIVE_INTERVAL = 60
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    DEFAULT_JOINT_POSITION = (0.0,
                              -20.37038014,
                              16.28988378,
                              0.0,
                              -(90 + -20.37038014 + 16.28988378),
                              0.0)
    # theta 1 range can be quite dangerous.
    # Undocumented feature: all limit ranges have to be at least 30 degree wide.
    DEFAULT_JOINT_LIMITS = ((-15., 15.),
                            (-21., 17.),
                            (-45, 15),
                            (-15., 15.),
                            (-112., -24),
                            (-360., 360.))
    # Adding some time to make sure that we capture all the replies
    REPLY_WAIT_TIME = .01

    # Raise error if there is no reply (e.g. because of a call that doesn't give a reply is not managed well)
    REPLY_TIMEOUT = 5.

    def __init__(self, device_address=None):
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS
        super().__init__(device_address=device_address)

        self.metacalls.update({'pose': self.get_pose,
                               'joints': self.get_joints,
                               'status': self.get_status})

        self.periodic_calls.update({'status': (self.get_status, 10)})

        self.last_error = None
        self.motion_paused = False

        self.monitor = None

        self.initialize()

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
        r = self.device_cmd(b'GetStatusRobot' + self.EOL)
        if not r:
            raise DeviceException

    def initialize(self):
        """
        First commands after connections.

        Will probably be refined depending on how the robot is used.
        """
        # Create monitor
        self.monitor = MecademicMonitor()
        self.monitor.start()

        # Set time
        self.set_RTC()

        # 1. Check current state and prompt for activation/homing
        #########################################################
        status = self.get_status()
        if status['error']:
            # Error mode
            if ask_yes_no('Robot in error mode. Clear?'):
                self.clear_errors()
            else:
                self.logger.warning('Robot still in error mode after driver initialization.')
                return
        if not status['activated']:
            if ask_yes_no('Robot deactivated. Activate?'):
                self.activate()
            else:
                self.logger.warning('Robot not activated after driver initialization')
                return
        if not status['homed']:
            # Not homed
            if ask_yes_no('Robot not homed. Home?'):
                self.home()
            else:
                self.logger.warning('Robot not homed after driver initialization.')
                return
        if status['paused']:
            self.logger.info('Motion is paused. Clearing.')
            self.clear_motion()
            self.resume_motion()

        # Set joint velocity
        jv = self.config.get('joint_velocity') or DEFAULT_VELOCITY
        self.set_joint_velocity(jv)

        self.logger.info("Initialization complete.")

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
            cmd += c
            if arg is not None:
                try:
                    arg = tuple(arg)
                except TypeError:
                    arg = (arg, )
                cmd += f'{arg}'.encode()
            cmd += self.EOL
        reply = self.device_cmd(cmd)
        return self.process_reply(reply)

    def process_reply(self, reply):
        """
        Take care of stripping and splitting raw reply from device
        Raise error if needed.
        """

        # First split along EOL in case there are more than one reply
        raw_replies = reply.split(self.EOL)

        # Convert each
        formatted_replies = []
        for r in raw_replies:
            if not r:
                continue
            r_str = r.decode('ascii', errors='ignore')
            code, message = r_str.strip('[]').split('][')
            code = int(code)
            formatted_replies.append((code, message))

        # Manage errors and other strange things here
        reply2000 = None
        for code, message in formatted_replies:
            if code == 2042:
                # Motion paused - not useful
                self.motion_paused = True
            elif code < 2000:
                # Error code.
                self.last_error = (code, message)
                self.logger.error(f'[{code}] - {message}')
            elif code > 2999:
                # Status message sent "out of the blue"
                self.logger.warning(f'{code}: {message}')
            else:
                rep = (code, message)
                if reply2000 is not None:
                    # More than one 2000 reply in one call - this should not happen
                    self.logger.warning(f'More code 2000:{reply2000[0]} - {reply2000[1]}')
                reply2000 = rep

        # Manage cases where the only reply is e.g. a 3000
        if reply2000 is None:
            reply2000 = None, None
        return reply2000

    @proxycall(admin=True)
    def set_TRF_at_wrist(self):
        """
        Sets the Tool reference frame at the wrist of the robot (70 mm below the
        flange). This makes all pose changes much easier to understand and predict.

        This is not a good solution when the center of rotation has so be above the
        flange (e.g. to keep a sample in place).
        """
        code, reply = self.send_cmd('SetTRF', (0, 0, -70, 0, 0, 0))

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
        keys = ['activated',
                'homed',
                'simulation',
                'error',
                'paused',
                'eob',
                'eom']
        try:
            status = {}
            for name, x in zip(keys, reply.split(',')):
                if x.strip() == '1':
                    status[name] = True
                elif x.strip() == '0':
                    status[name] = False
                else:
                    raise RuntimeError()
        except:
            self.logger.error(f'get_status returned {reply}')
            # try again
            status = self.get_status()

        return status

    @proxycall(admin=True)
    def set_RTC(self, t=None):
        """
        Set time. Not clear if there's a reason to set something else
        than current time...
        """
        if t is None:
            t = time.time()
        # Not documented, but setRTC actually sends a reply,
        # So no need to send two commands
        code, message = self.send_cmd('SetRTC', t)
        return

    @proxycall(admin=True)
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

    @proxycall(admin=True)
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

    @proxycall(admin=True)
    def activate_sim(self):
        """
        Activate simulation mode
        """
        code, reply = self.send_cmd('ActivateSim')

    @proxycall(admin=True)
    def deactivate_sim(self):
        """
        Activate simulation mode
        """
        code, reply = self.send_cmd('DeactivateSim')

    @proxycall(admin=True)
    def deactivate(self):
        """
        Deactivate the robot
        """
        code, reply = self.send_cmd('DeactivateRobot')
        self.logger.info(reply)
        return

    @proxycall(admin=True)
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

    @proxycall(admin=True)
    def clear_motion(self):
        """
        Clear motion
        """
        code, reply = self.send_cmd('ClearMotion')
        if code == 2044:
            self.logger.info(reply)
        else:
            self.logger.warning(reply)
        return

    @proxycall(admin=True)
    def resume_motion(self):
        """
        Resume motion
        """
        code, reply = self.send_cmd('ResumeMotion')
        if code == 2043:
            self.logger.info(reply)
        else:
            self.logger.warning(reply)
        return

    @proxycall(admin=True)
    def set_joint_velocity(self, p):
        """
        Set joint velocity as a percentage of the maximum speed.
        (See MAX_JOINT_VELOCITY)

        The last is especially important for continuous tomographic scans.
        """
        code, reply = self.send_cmd('SetJointVel', p)
        self.config['joint_velocity'] = p

    @proxycall()
    def get_joint_velocity(self):
        """
        Get joint velocity as a percentage of the maximum speed.
        (See MAX_JOINT_VELOCITY)
        """
        code, reply = self.send_cmd('GetJointVel')
        return float(reply)

    @proxycall(admin=True, block=False)
    def move_joints(self, joints, block=True):
        """
        Move joints
        """
        # Send two commands because 'MoveJoints' doesn't immediately
        # return something
        status = self.get_status()
        if status['simulation']:
            self.logger.warning('simulation mode')
        code, reply = self.send_cmd(['MoveJoints', 'GetStatusRobot'], [joints, None])
        if block:
            self.check_done()
        else:
            self.logger.info('Non-blocking motion started.')
        return self.get_joints()

    @proxycall(admin=True, block=False)
    def move_single_joint(self, angle, joint_number, block=True):
        """
        Move a single joint to given angle.
        """
        # Get current joints and change only one value
        joints = self.get_joints()
        joints[joint_number - 1] = angle
        return self.move_joints(joints, block=block)

    @proxycall(admin=True, block=False)
    def rotate_continuous(self, end_angle, duration, start_angle=None, joint_number=6, block=False):
        """
        Rotate one joint (by default 6th) from start_angle (by default current)
        to given end_angle, setting the joint velocity for the rotation to last
        given duration.

        NOTE: This function is non-blocking by default
        """
        if start_angle is not None:
            # Move to start.
            self.move_single_joint(start_angle, joint_number=joint_number)
        else:
            start_angle = self.get_joints()[joint_number-1]

        # Get current velocity
        cv = self.get_joint_velocity()

        # Velocity in degrees / seconds
        vel = abs(end_angle - start_angle)/duration

        # Percentage of maximum velocity
        p = 100 * vel/MAX_JOINT_VELOCITY[joint_number-1]
        self.logger.info(f'Setting velocity of joint {joint_number} to {vel:0.3f} degrees/seconds (p = {p})')
        self.set_joint_velocity(p)

        # Now start move
        self.move_single_joint(end_angle, joint_number=joint_number, block=block)
        
        self.logger.info(f'velocity will be {p} but was {cv} before.')
        
        # Reset the velocity
        # self.when_done(self.set_joint_velocity)

    def when_done(self, fct):
        """
        Execute fct only when motion is over.
        """
        def do_after_done():
            self.check_done()
            fct()

        Future(target=do_after_done)
        return

    @proxycall()
    def get_joints(self):
        """
        Get current joint angles.

        The manual says that GetRtJointPos is better than GetJoints
        """
        code, reply = self.send_cmd('GetRtJointPos')
        joints = [float(x) for x in reply.split(',')]
        #if joints[0] < 1600000000:
        #    # That's not right. Try again.
        #    return self.get_joints()
        # Drop the first element (timestamp)
        self.log_joints(joints[1:])
        return joints[1:]

    @datalogger.meta(field_name='joints', tags=logtags)
    def log_joints(self, joints):
        """
        Helper function just for logging.
        """
        return {'theta_1': joints[0],
                'theta_2': joints[1],
                'theta_3': joints[2],
                'theta_4': joints[3],
                'theta_5': joints[4],
                'theta_6': joints[5]}

    @proxycall(admin=True, block=False)
    def move_pose(self, pose):
        """
        Move to pose given by coordinates (x,y,z,alpha,beta,gamma)
        """
        # Send two commands because 'MovePose' doesn't immediately
        # return something
        status = self.get_status()
        if status['simulation']:
            self.logger.warning('simulation mode')
        code, reply = self.send_cmd(['MovePose', 'GetStatusRobot'], [pose, None])
        self.check_done()
        return self.get_pose()

    @proxycall()
    def get_pose(self):
        """
        Get current pose (x,y,z, alpha, beta, gamma)
        """
        code, reply = self.send_cmd('GetRtCartPos')
        pose = [float(x) for x in reply.split(',')]
        self.log_pose(pose)
        # Drop the first element (timestamp)
        return pose[1:]

    @datalogger.meta(field_name='pose', tags=logtags)
    def log_pose(self, pose):
        """
        Helper function just for logging.
        """
        return {'x': pose[0],
                'y': pose[1],
                'z': pose[2],
                'tilt': pose[3],
                'roll': pose[4],
                'rot': pose[5]}

    @proxycall()
    def check_done(self):
        """
        Poll until movement is complete.

        Implements emergency stop
        """
        with emergency_stop(self.abort):
            while True:
                # query axis status
                status = self.get_status()
                if status['eob']:
                    break
                else:
                    # Temporise
                    time.sleep(self.POLL_INTERVAL)
        self.logger.info("Finished moving robot.")

    @proxycall(admin=True, block=False)
    def move_to_default_position(self):
        """
        Move to the predefined default position.

        TODO: maybe we will have more than one of those.
        """
        self.move_joints(self.DEFAULT_JOINT_POSITION)

    @proxycall()
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

    @proxycall(admin=True)
    def set_joint_limits(self, limits):
        """
        Set joint limits. This must be done while robot is not active,
        so can be complicated.

        Since this is a critical operation, the user is prompted,
        and the default is no.
        """
        self.logger.critical("changing joint limits is a risky and rare operation. This function is currently disabled.")

        """        
        if self.isactive:
            prompt = 'Robot is active. Deactivate?'

        # Enable custom joint limits
        code, reply = self.send_cmd('SetJointLimitsCfg', 1)

        # Check if limits are already set
        current_limits = self.get_joint_limits()
        if np.allclose(current_limits, limits, atol=.1):
            self.logger.info("Limits are already set.")
            return

        # Ask user to confirm
        prompt = 'Preparing to change joint limits as follows:\n'
        for i, (low, high) in enumerate(limits):
            prompt += f' * theta {i+1}: ({low:9.5f}, {high:9.5f})\n'
        prompt += 'Are you sure you want to proceed?'
        if not ask_yes_no(prompt, yes_is_default=False):
            self.logger.error('Setting limit cancelled.')
            return

        for i, (low, high) in enumerate(limits):
            code, message = self.send_cmd('SetJointLimits', (i+1, low, high))

        self.logger.info("Joint limits have been changed.")
        """

        return

    @proxycall()
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

    @proxycall()
    @property
    def isactive(self):
        return self.get_status()['activated'] == 1

    @proxycall()
    @property
    def ishomed(self):
        return self.get_status()['homed'] == 1


class Motor(MotorBase):
    def __init__(self, name, driver, axis):
        super(Motor, self).__init__(name, driver)
        self.axis = ['x', 'z', 'y', 'tilt', 'roll', 'rot'].index(axis)

        # Convention for the lab is y up, z along propagation
        if self.axis == 1:
            self.scalar = -1.

    def _get_pos(self):
        """
        Return position in mm
        """
        return self.driver.get_pose()[self.axis]

    def _set_abs_pos(self, x):
        """
        Set absolute position
        """
        pose = self.driver.get_pose()
        pose[self.axis] = x
        new_pose = self.driver.move_pose(pose)
        return new_pose[self.axis]


def create_motors(driver):
    """
    Create the 6 pose motors.
    """
    motors = {}
    motors['bx'] = Motor('bx', driver, 'x')
    motors['by'] = Motor('by', driver, 'y')
    motors['bz'] = Motor('bz', driver, 'z')
    motors['btilt'] = Motor('btilt', driver, 'tilt')
    motors['broll'] = Motor('broll', driver, 'roll')
    motors['brot'] = Motor('brot', driver, 'rot')
    return motors
