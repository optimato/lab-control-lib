"""
Base classes.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import threading
import json
import logging
import os
import errno
import time
import atexit
import socket
import signal
from select import select

from . import proxycall, get_config
from .util import FileDict, Future
from .logs import logger as rootlogger

class MotorLimitsException(Exception):
    pass


class DeviceException(Exception):
    pass


def _recv_all(sock, EOL=b'\n'):
    """
    Receive all data from socket (until EOL)
    * all bytes *
    """
    ret = sock.recv(1024)
    if not ret:
        # This happens if the connection was closed at the other end
        return ret
    while not ret.endswith(EOL):
        try:
            ret += sock.recv(1024)
        except TimeoutError:
            rootlogger.exception(f'EOL not reached after {ret}')
            raise
        except:
            raise
    return ret


class emergency_stop:

    stop_method = None

    def __init__(self, stop_method):
        try:
            # Won't work if not in main thread
            signal.signal(signal.SIGINT, self.signal_handler)
        except ValueError:
            pass
        self.local_stop_method = stop_method

    @classmethod
    def set_stop_method(cls, stop_method):
        cls.stop_method = stop_method

    @classmethod
    def signal_handler(cls, sig, frame):
        if cls.stop_method is not None:
            cls.stop_method()

    def __enter__(self):
        self.set_stop_method(self.local_stop_method)

    def __exit__(self, exc_type, exc_value, traceback):
        self.__class__.stop_method = None


class DriverBase:
    """
    Base for all drivers
    """

    logger = None                       # Place-holder. Gets defined at construction.
    motors = {}
    DEFAULT_CONFIG = {}

    def __init__(self):
        """
        Initialization.
        """

        # register exit functions
        atexit.register(self.shutdown)

        # Get logger if not set in subclass
        if self.logger is None:
            self.logger = rootlogger.getChild(self.__class__.__name__)

        # Set default name here. Can be overridden by subclass, for instance to allow multiple instances to run
        # concurrently
        if not hasattr(self, 'name'):
            self.name = self.__class__.__name__

        # Load (or create) config dictionary
        self.config_filename = os.path.join(get_config()['conf_path'], 'drivers', self.name + '.json')
        self.config = FileDict(self.config_filename)

        # Make sure all default keys are present
        for k, v in self.DEFAULT_CONFIG.items():
            self.config.setdefault(k, v)

        # Dictionary of metadata calls
        self.metacalls = {}

        # Periodic calls for logging
        self.periodic_calls = {}
        self.periodic_futures = {}

        self.initialized = False

    def init_device(self):
        """
        Device initialization.
        """
        raise NotImplementedError

    def start_periodic_calls(self):
        """
        Start periodic calls used as heartbeat and for data logging.
        """
        for label, d in self.periodic_calls.items():
            self.periodic_futures[label] = Future(self._periodic_call, args=d)

    def _periodic_call(self, method, interval):
        """
        This thread runs on a separate thread and calls
        the given method at a given interval.
        """
        t0 = time.time()
        n = 0
        while True:
            n += 1
            if not self.initialized:
                time.sleep(max(0, t0 + n*interval - time.time()))
                continue
            try:
                method()
            except socket.timeout:
                self.logger.exception(f'Socket Timeout after calling method {self.__class__.__name__}.{method.__name__}')
                break
            except DeviceException:
                self.logger.exception('Device disconnected.')
                break

            # Try to keep the beat
            time.sleep(max(0, t0 + n * interval - time.time()))


    @proxycall()
    def get_meta(self, metakeys=None):
        """
        Return the data described by the list
        of keys in metakeys. If metakeys is None: return all
        available meta.
        """

        if metakeys is None:
            metakeys = self.metacalls.keys()

        meta = {}
        for key in metakeys:
            call = self.metacalls.get(key)
            if call is None:
                meta[key] = 'unknown'
            else:
                meta[key] = call()
        return meta

    @proxycall()
    def set_log_level(self, level):
        """
        Set logging level for this driver only.
        """
        self.logger.setLevel(level)

    def shutdown(self):
        """
        Shutdown procedure registered with atexit.
        """
        pass

    @classmethod
    def register_motor(cls, motor_name, **kwargs):
        """
        A decorator to register a motor class associated with this driver.

        kwargs are eventual additional arguments to pass to motor constructor.
        """
        # We don't want to update the base class dict
        if not cls.motors:
            cls.motors = {}

        def f(motor_cls):
            cls.motors[motor_name] = (motor_cls, kwargs)
            return motor_cls
        return f

    @classmethod
    def create_motors(cls, driver):
        """
        Instantiate all motors given driver
        """
        return {mname:mcls(name=mname, driver=driver, **kwargs) for mname, (mcls, kwargs) in cls.motors.items()}


class SocketDriverBase(DriverBase):
    """
    Base class for all drivers working through a socket.
    """

    EOL = b'\n'                         # End of API sequence (default is \n)
    DEFAULT_DEVICE_ADDRESS = None       # The default address of the device socket.
    DEVICE_TIMEOUT = None               # Device socket timeout
    NUM_CONNECTION_RETRY = 2            # Number of times to try to connect
                                        # fdm: it's "tries", not "retries", so it mustn't be set to 0!
    KEEPALIVE_INTERVAL = 10.            # Default Polling (keep-alive) interval
    logger = None
    REPLY_WAIT_TIME = 0.                # Time before reading reply (needed for asynchronous connections)
    REPLY_TIMEOUT = 60.                  # Maximum time allowed for the reception of a reply

    def __init__(self, device_address):
        """
        Initialization.
        """
        super().__init__()

        # Store device address
        self.device_address = device_address
        self.device_sock = None
        self.shutdown_requested = False

        self.logger.debug(f'Driver {self.name} will connect to {self.device_address[0]}:{self.device_address[1]}')

        # Attributes initialized (or re-initialized) in self.connect_device
        # device_cmd lock
        self.cmd_lock = threading.Lock()
        # Buffer in which incoming data will be stored
        self.recv_buffer = None
        # Flag to inform other threads that data has arrived
        self.recv_flag = None
        # Listening/receiving thread
        self.recv_thread = None
        # Receiver lock
        self.recv_lock = threading.Lock()

        # Connect to device
        self.connected = False
        self.connect_device()

        # Initialize the device
        self.initialized = False
        self.init_device()
        self.logger.info('Device initialized')

    def connect_device(self):
        """
        Device connection
        """
        # Prepare device socket connection
        self.device_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.device_sock.settimeout(self.DEVICE_TIMEOUT)

        for retry_count in range(self.NUM_CONNECTION_RETRY):
            conn_errno = self.device_sock.connect_ex(self.device_address)
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
        self.recv_thread = Future(target=self._listen_recv)

        self.connected = True
        self.logger.info(f'Driver {self.name} connected to {self.device_address[0]}:{self.device_address[1]}')

    def _listen_recv(self):
        """
        This threads receives all data in real time and stores it
        in a local buffer. For devices that send data only after
        receiving a command, the buffer is read and emptied immediately.
        """
        while True:
            rlist, _, elist = select([self.device_sock], [], [self.device_sock], .5)
            if elist:
                self.logger.critical('Exceptional event with device socket.')
                break
            if rlist:
                # Incoming data
                with self.recv_lock:
                    d = _recv_all(rlist[0], EOL=self.EOL)
                    self.recv_buffer += d
                    self.recv_flag.set()
            if self.shutdown_requested:
                break

    def device_cmd(self, cmd: bytes, reply=True) -> bytes:
        """
        Send command to the device, NOT adding EOL and return the reply.

        Args:
            cmd: (bytes) pre-formatted command to send.
            reply: (bool) if False, do not wait for reply (default: True)

        Returns:
            reply (bytes) or None
        """
        if not self.connected:
            raise RuntimeError('Device not connected.')
        if not self.initialized:
            self.logger.info('Device not (yet?) initialized.')

        with self.cmd_lock:

            # Flush the replies
            response = self.get_recv_buffer()

            # Pass command to device
            if isinstance(cmd, str):
                cmd = cmd.encode()

            self.device_sock.sendall(cmd)

            if reply:
                # Wait for reply
                time.sleep(self.REPLY_WAIT_TIME)
                if not self.recv_flag.wait(timeout=self.REPLY_TIMEOUT):
                    raise TimeoutError('Device reply timed out.')

                # Concatenate replies
                response += self.get_recv_buffer()

            else:
                response = None
        return response

    def get_recv_buffer(self):
        """
        Read and reset the recv buffer. This can be used to flush the buffer.
        """
        with self.recv_lock:

            # Reply is in the local buffer
            data = self.recv_buffer

            # Clear the local buffer
            self.recv_buffer = b''

            # Clear flag
            self.recv_flag.clear()

        return data


    def terminal(self):
        """
        Create a terminal session to send commands directly to the device.
        """
        print('Enter command and hit return. Empty line will exit.')
        prompt = f'[{self.name}] >> '
        while True:
            cmd = input(prompt)
            if not cmd:
                break
            try:
                reply = self.device_cmd(cmd.encode() + self.EOL)
                print(reply)
            except Exception as e:
                print(repr(e))

    def close_device(self):
        """
        Driver clean up on shutdown.
        """
        self.device_sock.close()
        self.connected = False
        self.initialized = False

    def driver_status(self):
        """
        Some info about the current state of the driver.
        """
        raise NotImplementedError

    def shutdown(self):
        """
        Clean shutdown of the driver.
        """
        if not self.connected:
            return
        # Tell the polling thread to abort. This will ensure that all the rest is wrapped up
        self.shutdown_requested = True
        self.logger.info('Shutting down connection to driver.')

    def stop(self):
        if not self.connected:
            raise RuntimeError('Not connected.')
        self.close_device()
        return

    def restart(self):
        try:
            self.stop()
        except RuntimeError:
            pass
        self.connect_device()
        self.init_device()


class MotorBase:
    """
    Representation of a motor (any object that has one translation / rotation axis).

    User and dial positions are different and controlled by self.offset and self.scalar
    Dial = (User*scalar)-offset
    """
    def __init__(self, name, driver):
        # Store motor name and driver instance
        self.name = name
        self.driver = driver

        # Attributes
        self.offset = None
        self.scalar = None
        self.limits = None

        # Store logger
        self.logger = logging.getLogger(name)

        # File name for motor configuration
        self.config_file = os.path.join(get_config()['conf_path'], 'motors', name + '.json')

        # Load offset configs
        self._load_config()

    def _get_pos(self):
        """
        Return *dial* position in mm or degrees
        """
        raise NotImplementedError

    def _set_abs_pos(self, x):
        """
        Set absolute *dial* position in mm or degrees
        """
        raise NotImplementedError

    def _set_rel_pos(self, x):
        """
        Change position relative in mm or degrees. x is in _dial_ units
        """
        return self._set_abs_pos(self._get_pos() + x)

    def _user_to_dial(self, user):
        """
        Converts user position to a dial position
        """
        return (user * self.scalar) - self.offset

    def _dial_to_user(self, dial):
        """
        Converts a dial position to a user position
        """
        return (dial + self.offset)/self.scalar

    def mv(self, x, block=True):
        """
        Absolute move to *user* position x

        Returns final USER position if block=True (default). If block=False, returns
        the thread that will terminate when motion is complete.
        """
        self._within_limits(x, raise_error=True)
        if not block:
            t = threading.Thread(target=self._set_abs_pos, args=[self._user_to_dial(x)])
            t.start()
            return t
        else:
            return self._dial_to_user(self._set_abs_pos(self._user_to_dial(x)))

    def mvr(self, x, block=True):
        """
        Relative move by position x

        Returns final USER position if block=True (default). If block=False, returns
        the thread that will terminate when motion is complete.
        """
        self._within_limits(self.pos + x, raise_error=True)
        if not block:
            t = threading.Thread(target=self._set_rel_pos, args=[self.scalar * x])
            t.start()
            return t
        else:
            return self._dial_to_user(self._set_rel_pos(self.scalar * x))

    def lm(self):
        """
        Return *user* soft limits
        """
        # Limits as stored in dialed values. Here they are offset into user values
        if self.scalar > 0:
            return self._dial_to_user(self.limits[0]), self._dial_to_user(self.limits[1])
        else:
            return self._dial_to_user(self.limits[1]), self._dial_to_user(self.limits[0])

    def set_lm(self, low, high):
        """
        Set *user* soft limits
        """
        if low >= high:
            raise RuntimeError(f'Low limit ({low}) should be lower than high limit ({high})')
        # Limits are stored in dial values
        self.limits = sorted([self._user_to_dial(low), self._user_to_dial(high)])
        self._save_config()

    @property
    def pos(self):
        """
        Current *user* position
        """
        return (self._get_pos() + self.offset)/self.scalar

    @pos.setter
    def pos(self, value):
        self.mv(value)

    def where(self):
        """
        Return (dial, user) position
        """
        x = self._get_pos()
        return x, self._dial_to_user(x)

    def set(self, pos):
        """
        Set user position
        """
        self.offset = (self.scalar * pos) - self._get_pos()
        self._save_config()

    def set_scalar(self, scalar):
        """
        Set a scalar value for conversion between user and dial positions
        Dial = scalar*User_pos - offset
        """
        self.scalar = scalar
        self._save_config()
        print ('You have just changed the scalar. The motor limits may need to be manually updated.')

    def get_meta(self, returndict):
        """
        Place metadata in `returndict`.

        Note: returndict is used instead of a normal method return
        so that this method can be run on a different thread.
        """

        dx, ux = self.where()
        returndict['scalar'] = self.scalar
        returndict['offset'] = self.offset
        returndict['pos_dial'] = dx
        returndict['pos_user'] = ux
        returndict['lim_user'] = self.lm()
        returndict['lim_dial'] = self.limits
        returndict['driver'] = self.driver.name

        return

    def _within_limits(self, x, raise_error=False):
        """
        Check if *user* position x is within soft limits.
        """
        valid = self.limits[0] < self._user_to_dial(x) < self.limits[1]
        if raise_error and not valid:
            raise MotorLimitsException(f'{self.limits[0]} < {self._user_to_dial(x)} < {self.limits[1]}')
        return valid

    def _save_config(self):
        """
        Save *dial* limits and offset
        """
        data = {'limits': self.limits, 'offset': self.offset, 'scalar': self.scalar}
        with open(self.config_file, 'w') as f:
            json.dump(data, f)

    def _load_config(self):
        """
        Load limits and offset
        """
        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
        except IOError:
            self.logger.warning('Could not find config file "%s". Continuing with default values.' % self.config_file)
            # Create path
            try:
                os.makedirs(os.path.split(self.config_file)[0])
            except OSError as e:
                if e.errno == errno.EEXIST:
                    pass
                else:
                    raise
            self.limits = (-1., 1.)
            self.offset = 0.
            self.scalar = 1.
            # Save file
            self._save_config()
            return False
        self.limits = data["limits"]
        self.offset = data["offset"]
        self.scalar = data["scalar"]
        self.logger.info('Loaded stored limits, scalar and offset.')
        return True
