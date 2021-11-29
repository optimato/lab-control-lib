"""
Base classes.

User and dial positions are different and controlled by self.offset and self.scalar
Dial = (User*scalar)-offset


Escaped commands API processed by the daemon, implemented in DeviceServerBase:
ADMIN: Request admin rights
NOADMIN: Rescind admin rights
DISCONNECT: Shutdown connection
STATUS: Return current status of the daemon

Additional commands implemented in SocketDeviceServerBase:
STOP: Disconnect from device (admin only)
 return OK or error message
START: Connect to device and run initialization (admin only)
 return OK or error message
RESTART: Disconnect, then reconnect and initialize the device (admin only)
 return OK or error message
"""
import threading
import json
import logging
import os
import errno
import time
import atexit
import socket
import functools


from . import __DAEMON__, config, conf_path

class MotorLimitsException(Exception):
    pass


def _recv_all(socket, EOL='\n'):
    """
    Receive all data from socket (until EOL)
    """
    ret = socket.recv(1024)
    while not ret.endswith(EOL):
        ret += socket.recv(1024)
    return ret


def nonblock(fin):
    """
    Decorator to make any function or method non-blocking
    """
    def fout(*args, **kwargs):
        block = 'block' not in kwargs or kwargs.pop('block')
        if block:
            return fin(*args, **kwargs)
        else:
            t = threading.Thread(target=fin, args=args, kwargs=kwargs)
            t.start()
            return t
    return fout


def prompt(text, default='y'):
    """
    Prompt script with yes or no input
    :param str text: text to feature in prompt
    :param str default: default answer (if no input is given i.e. return key)
    :return: bool (answered yes or no)
    """
    if default == 'y':
        qappend = "[y]/n"
    elif default == 'n':
        qappend = 'y/[n]'
    else:
        raise ValueError("Default answer must be 'y' or 'n'")
    ans = input(text + qappend)
    if ans == '':
        ans = default
    while ans != 'n' and ans != 'y':
        input('invalid input, please answer ''y'' or ''n'': ')
    if ans == "y":
        return True
    else:
        return False


def admin_only(method):
    """
    Decorator for methods that can be executed only in admin mode.
    """
    @functools.wraps(method)
    def f(self, *args, **kwargs):
        if self.admin:
            return method(self, *args, **kwargs)
        raise RuntimeError("Method '{0}.{1}' requires admin rights".format(self.__class__.__name__, method.__name__))
    return f


class emergency_stop:
    """
    Simple context manager to call emergency stop in case of keyboard interrupt.
    By default the exception is reraised in case the calling code has more clean up to do.

    with emergency_stop(self.stop):
        [do something that could be interrupted, e.g. motor move]
        [this code is interrupted and self.stop is called if ctrl-C is hit]
    TODO: add some logging
    """
    def __init__(self, stop_method):
        """
        Register stop_method as emergency stop method.
        """
        self.stop_method = stop_method

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is KeyboardInterrupt:
            self.stop_method()


class DeviceServerBase:
    """
    Base class for all serving connections to a device, meant to run as a daemon.

    This base class implements the server socket that on which clients can connect.
    """

    CLIENT_TIMEOUT = 1
    NUM_CONNECTION_RETRY = 10
    ESCAPE_STRING = '^'
    logger = None

    def __init__(self, serving_address):
        """
        Initialization.
        """

        # Get logger if not set in subclass
        if self.logger is None:
            self.logger = logging.getLogger(self.__class__.__name__)

        # Store address
        self.serving_address = serving_address

        # register exit functions
        atexit.register(self.shutdown)

        # Set default name here. Can be overriden by subclass, for instance to allow multiple instances to run
        # concurrently
        self.name = self.__class__.__name__

        # Initialize the device
        self.init_device()

        # Prepare thread lock
        self._lock = threading.Lock()

        # Prepare client socket connection
        self.client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.client_sock.settimeout(self.CLIENT_TIMEOUT)

        # Shutdown flag
        self.shutdown_requested = False

        # No thread is admin
        self.admin = None

        # Thread dictionary
        self.threads = {}

    def init_device(self):
        """
        Device connection
        """
        raise NotImplementedError

    def listen(self):
        """
        Infinite listening loop for new connections.
        """
        self.client_sock.listen(5)
        while True:
            if self.shutdown_requested:
                self.shutdown()
            try:
                client, address = self.client_sock.accept()
                # Client is in blocking mode
                client.settimeout(None)
                new_thread = threading.Thread(target=self._serve, args=(client, address))
                new_thread.daemon = True
                new_thread.start()
                self.threads[new_thread.ident] = new_thread
            except socket.timeout:
                continue

    def _serve(self, client, address):
        """
        Serve a new client.
        """

        while True:
            # Read data
            data = _recv_all(client)

            # Check for escape
            if data.startswith(self.ESCAPE_STRING):
                reply = self.parse_escaped(data)

                # Special case: reply is None means: exit the loop and shut down this client.
                if reply is None:
                    break

                # Send reply back to client
                client.sendall(reply)

                continue

            # Pass (or parse) command for device
            reply = self.device_cmd(data)

            # Return to client
            client.sendall(reply)

        # Done
        client.close()

        # Thread cleans itself up
        ident = threading.get_ident()
        if self.admin == ident:
            self.admin = None
        self.threads.pop(ident)

    def device_cmd(self, cmd):
        """
        Pass the command to the device.
        """
        raise NotImplementedError

    def parse_escaped(self, cmd):
        """
        Parse escaped command and return reply.
        """
        cmd = cmd.strip(self.ESCAPE_STRING).strip()

        if cmd == 'ADMIN':
            ident = threading.get_ident()
            if self.admin is None:
                self.admin = ident
                return 'OK'
            if self.admin == ident:
                return 'Already admin'
            else:
                return 'Admin rights claimed by other client'

        if cmd == 'NOADMIN':
            ident = threading.get_ident()
            if self.admin != ident:
                return 'Admin rights were not granted. Nothing to do.'
            else:
                self.admin = None
                return 'Admin rights rescinded'

        if cmd == 'DISCONNECT':
            # Understood by the thread loop as a thread shutdown signal
            return None

        if cmd == 'STATUS':
            # Return some status.
            return 'TODO: some useful status info, maybe in json format'

        return f'Error: unknown command {cmd}'

    def close_device(self):
        """
        Driver clean up on shutdown.
        """
        raise NotImplementedError

    def shutdown(self):
        """
        Clean shutdown of the driver.
        """
        # Tell the polling thread to abort. This will ensure that all the rest is wrapped up
        self.close_device()
        self.logger.info('Shutting down.')


class SocketDeviceServerBase(DeviceServerBase):
    """
    Base class for all serving connections to a socket device.
    """

    DEVICE_TIMEOUT = 1        # Device socket timeout
    ENDOFAPI = '\n'           # End-of-message sequence (default is \n)

    def __init__(self, serving_address, device_address):
        """
        Initialization.
        """
        # Store device address
        self.device_address = device_address
        self.device_sock = None
        self.logger.debug(f'Daemon  {self.name} will connect to {self.device_address[0]}:{self.device_address[1]}')

        # Prepare serving side
        super().__init__(serving_address=serving_address)

        self.connected = False
        self.initialized = False

        # Connect to device
        self.connect_device()

        # Initialize device
        self.init_device()

    def init_device(self):
        """
        Device initialization. Could be interactive.
        """
        self.initialized = True
        raise NotImplementedError

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
            raise RuntimeError('Connection refused.')

        self.connected = True
        self.logger.info(f'Daemon {self.name} connected to {self.device_address[0]}:{self.device_address[1]}')

    def device_cmd(self, cmd):
        """
        Pass the command to the device.

        By default, the command is simply forwarded.
        """
        with self._lock:
            # Pass command to device
            self.device_sock.sendall(cmd)

            # Receive reply
            reply = _recv_all(self.device_sock, self.ENDOFAPI)
        return reply

    def close_device(self):
        """
        Driver clean up on shutdown.
        """
        self.device_sock.close()
        self.connected = False
        self.initialized = False

    def parse_escaped(self, cmd):
        """
        Parse escaped command.
        """

        if cmd == 'STOP':
            if not self.connected:
                return 'Device not connected'
            try:
                self.close_device()
                return 'OK'
            except BaseException as error:
                return str(error)

        if cmd == 'START':
            if self.connected:
                return 'Device already connected'
            try:
                self.connect_device()
                self.init_device()
                return 'OK'
            except BaseException as error:
                return str(error)

        if cmd == 'RESTART':
            if not self.connected:
                return 'Device not connected'
            try:
                self.close_device()
                self.connect_device()
                self.init_device()
                return 'OK'
            except BaseException as error:
                return str(error)

        return super().parse_escaped(cmd)


class DriverBase:
    """
    Base for all drivers
    """

    TIMEOUT = 15
    NUM_CONNECTION_RETRY = 10
    ESCAPE_STRING = '^'
    ENDOFAPI = '\n'
    logger = None

    def __init__(self, address, admin):
        """
        Initialization.
        If admin is True, control is asked.
        """

        # Get logger if not set in subclass
        if self.logger is None:
            self.logger = logging.getLogger(self.__class__.__name__)

        # Store host and port
        self.address = address

        # register exit functions
        atexit.register(self.shutdown)

        # Set default name here. Can be overriden by subclass, for instance to allow multiple instances to run
        # concurrently
        self.name = self.__class__.__name__

        self.logger.debug(f'Driver {self.name} will connect to {self.address[0]}:{self.address[1]}')

        self.admin = admin
        self.sock = None
        self.connected = False

        # Connect
        self.connect()

        # Request admin rights if needed
        if admin:
            reply = self.send_recv(self.ESCAPE_STRING + 'ADMIN\n')
            if reply.strip != 'OK':
                raise RuntimeError(f'Could not request admin rights: {reply}')

    def connect(self):
        """
        Connect socket.
        """
        # Prepare device socket connection
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.sock.settimeout(self.TIMEOUT)

        for retry_count in range(self.NUM_CONNECTION_RETRY):
            conn_errno = self.sock.connect_ex(self.address)
            if conn_errno == 0:
                break

            self.logger.critical(os.strerror(conn_errno))
            time.sleep(.05)

        if conn_errno != 0:
            raise RuntimeError('Connection refused.')

        self.connected = True
        self.logger.info(f'Driver {self.name} connected to {self.address[0]}:{self.address[1]}')

    def shutdown(self):
        """
        Clean shutdown of the driver.
        """
        self.sock.close()
        self.logger.debug(f'Driver {self.name}: connection to {self.address[0]}:{self.address[1]} closed.')

    def send(self, msg):
        """
        Send message (byte string) to socket.
        """
        try:
            self.sock.sendall(msg)
        except socket.timeout:
            raise RuntimeError('Communication timed out')

    def recv(self):
        """
        Read message from socket.
        """
        r = _recv_all(self.sock, EOL=self.ENDOFAPI)
        return r

    def _send_recv(self, msg):
        """
        Send message to socket and return reply message.
        """
        self.send(msg)
        r = self.recv()
        return r

    def send_recv(self, msg):
        """
        Send message to socket and return reply message.
        (can be overloaded by subclass)
        """
        return self._send_recv(msg)


class MotorBase:
    """
    Representation of a motor (any object that has one translation / rotation axis).
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
        self.config_file = os.path.join(conf_path, 'motors', name + '.json')

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
        Change position relative in mm or degrees
        """
        return self._set_abs_pos(self._get_pos() + (self.scalar * x))

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
        if not self._within_limits(x):
            raise MotorLimitsException()
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
        if not self._within_limits(self.pos + x):
            raise MotorLimitsException()
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
        return self._dial_to_user(self.limits[0]), self._dial_to_user(self.limits[1])

    def set_lm(self, low, high):
        """
        Set *user* soft limits
        """
        if low >= high:
            raise RuntimeError("Low limit (%f) should be lower than high limit (%f)" % (low, high))
        # Limits are stored in dial values
        vals = [self._user_to_dial(low), self._user_to_dial(high)]  # to allow for scalar to be negative (flips limits)
        self.limits = (min(vals), max(vals))
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

    def _within_limits(self, x):
        """
        Check if *user* position x is within soft limits.
        """
        return self.limits[0] < self._user_to_dial(x) < self.limits[1]

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