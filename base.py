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
from select import select

from . import conf_path


ESCAPE_STRING = b'^'


class MotorLimitsException(Exception):
    pass


class DeviceException(Exception):
    pass


class DaemonException(Exception):
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
        ret += sock.recv(1024)
    return ret


def _send_all(sock, msg):
    """
    Convert str to byte (if needed) and send on socket.
    """
    if isinstance(msg, str):
        msg = msg.encode()
    sock.sendall(msg)


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
            return True



class DeviceServerBase:
    """
    Base class for all serving connections to a device, meant to run as a daemon.

    This base class implements the server socket on which clients can connect.
    """

    CLIENT_TIMEOUT = 1
    NUM_CONNECTION_RETRY = 10
    EOL = b'\n'           # End of API sequence (default is \n)
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
        self.name = self.__class__.__name__.lower()

        # Prepare thread lock
        self._lock = threading.Lock()

        # Prepare client socket connection
        self.client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.client_sock.settimeout(self.CLIENT_TIMEOUT)

        # Shutdown flag
        self.shutdown_requested = False

        # No thread is admin
        self.admin = None

        # Thread dictionary
        self.threads = {}

        # Stats dictionary
        self.stats = {'startup': time.time()}

    def listen(self):
        """
        Infinite listening loop for new connections.
        """
        self.client_sock.bind(self.serving_address)
        self.client_sock.listen(5)
        while True:
            if self.shutdown_requested:
                self.shutdown()
                break
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
        # Driver is shut down
        self.logger.info('Shutdown complete')
        return

    def _serve(self, client, address):
        """
        Serve a new client.
        """
        ident = threading.get_ident()
        ident_key = f'{ident}'
        self.stats[ident_key] = {'startup': time.time(),
                                 'reply_number': 0,
                                 'total_reply_time': 0.,
                                 'total_reply_time2': 0.,
                                 'min_reply_time': 100.,
                                 'max_reply_time': 0.}

        self.logger.info(f'Client #{ident} connected ({address})')

        while True:
            # Check for shutdown signal
            if self.shutdown_requested:
                break

            # Read data
            data = _recv_all(client, EOL=self.EOL)
            if not data:
                self.logger.warning(f'Client {ident} disconnected.')
                break

            # Process the raw data sent by the client
            t0 = time.time()
            reply = self.process_command(data)
            dt = time.time() - t0

            self.stats[ident_key]['reply_number'] += 1
            self.stats[ident_key]['total_reply_time'] += dt
            self.stats[ident_key]['total_reply_time2'] += dt*dt
            minr = self.stats[ident_key]['min_reply_time']
            maxr = self.stats[ident_key]['max_reply_time']
            self.stats[ident_key]['min_reply_time'] = min(dt, minr)
            self.stats[ident_key]['max_reply_time'] = max(dt, maxr)

            # Special case: reply is None means: exit the loop and shut down this client.
            if reply is None:
                # Send acknowledgement to client
                _send_all(client, b'OK' + self.EOL)
                break

            # Send reply to client
            try:
                _send_all(client, reply)
            except BrokenPipeError:
                self.logger.warning(f'Client {ident} disconnected (dead?).')
                break

        # Out of the loop: we are done with this client
        client.close()

        # Thread cleans itself up
        if self.admin == ident:
            self.admin = None
        self.threads.pop(ident)

    def process_command(self, cmd):
        """
        Process a raw command sent by a client and prepare the reply.
        """
        # Check for escape
        if cmd.startswith(ESCAPE_STRING):
            cmd = cmd.strip(ESCAPE_STRING).strip(self.EOL)
            reply = self.parse_escaped(cmd)
        else:
            # Pass (or parse) command for device
            reply = self.device_cmd(cmd)
        return reply

    def device_cmd(self, cmd):
        """
        Pass the command to the device.
        """
        raise NotImplementedError

    def parse_escaped(self, cmd):
        """
        Parse escaped command and return reply.
        """
        if cmd == b'ADMIN':
            ident = threading.get_ident()
            if self.admin is None:
                self.admin = ident
                return b'OK' + self.EOL
            if self.admin == ident:
                return b'Already admin' + self.EOL
            else:
                return b'Admin rights claimed by other client' + self.EOL

        if cmd == b'AMIADMIN':
            ident = threading.get_ident()
            if self.admin == ident:
                return b'True' + self.EOL
            else:
                return b'False' + self.EOL

        if cmd == b'NOADMIN':
            ident = threading.get_ident()
            if self.admin != ident:
                return b'Admin rights were not granted. Nothing to do.' + self.EOL
            else:
                self.admin = None
                return b'Admin rights rescinded' + self.EOL

        if cmd == b'DISCONNECT':
            # Understood by the thread loop as a thread shutdown signal
            return None

        if cmd == b'STATS':
            # Return some stats.
            # This will fail if self.EOL appears in the stats, but
            # that seems unlikely.
            return json.dumps(self.stats).encode() + self.EOL

        return f'Error: unknown command {cmd}'.encode() + self.EOL

    def driver_status(self):
        """
        Some info about the current state of the driver.
        """
        return b'Not implemented' + self.EOL

    def shutdown(self):
        """
        Clean shutdown of the driver.
        """
        # Tell the polling thread to abort. This will ensure that all the rest is wrapped up
        self.shutdown_requested = True
        self.logger.info('Shutting down.')


class SocketDeviceServerBase(DeviceServerBase):
    """
    Base class for all serving connections to a socket device.
    """

    DEVICE_TIMEOUT = None        # Device socket timeout
    KEEPALIVE_INTERVAL = 10.    # Default Polling (keep-alive) interval

    def __init__(self, serving_address, device_address):
        """
        Initialization.
        """
        # Prepare serving side
        super().__init__(serving_address=serving_address)

        # Store device address
        self.device_address = device_address
        self.device_sock = None

        self.logger.debug(f'Daemon  {self.name} will connect to {self.device_address[0]}:{self.device_address[1]}')

        # Attributes initialized (or re-initialized) in self.connect_device
        # Buffer in which incoming data will be stored
        self.recv_buffer = None
        # Flag to inform other threads that data has arrived
        self.recv_flag = None
        # Listening/receiving thread
        self.recv_thread = None

        # Connect to device
        self.connected = False
        self.connect_device()

        # Initialize the device
        self.initialized = False
        self.init_device()

        # Start polling
        # number of skipped answers in polling thread (not sure that's useful)
        self.device_N_noreply = 0
        # "keep alive" thread
        self.polling_thread = threading.Thread(target=self._keep_alive)
        self.polling_thread.daemon = True
        self.polling_thread.start()

    def listen(self):
        super().listen()
        self.close_device()

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
        self.recv_thread = threading.Thread(target=self._listen_recv)
        self.recv_thread.daemon = True
        self.recv_thread.start()

        self.connected = True
        self.logger.info(f'Daemon {self.name} connected to {self.device_address[0]}:{self.device_address[1]}')

    def init_device(self):
        """
        Device initalization.
        """
        self.initialized = True
        raise NotImplementedError

    def _listen_recv(self):
        """
        This threads receives all data in real time and stores it
        in a local buffer. For devices that send data only after
        receiving a command, the buffer is read and emptied immediately.
        """
        while True:
            rlist, _, elist = select([self.device_sock], [], [self.device_sock], None)
            if elist:
                self.logger.critical('Exceptional event with device socket.')
                break
            if rlist:
                # Incoming data
                with self._lock:
                    d = _recv_all(rlist[0], EOL=self.EOL)
                    self.recv_buffer += d
                    self.recv_flag.set()

    def _keep_alive(self):
        """
        Infinite loop on a separate thread that pings the device periodically to keep the connection alive.

        TODO: figure out what to do if device dies.
        """
        while True:
            if not (self.connected and self.initialized):
                time.sleep(self.KEEPALIVE_INTERVAL)
                continue
            try:
                self.wait_call()
                self.device_N_noreply = 0
            except socket.timeout:
                self.device_N_noreply += 1
            except DeviceException:
                self.logger.critical('Device disconnected.')
                self.close_device()
            time.sleep(self.KEEPALIVE_INTERVAL)

    def wait_call(self):
        """
        Keep-alive call to the device
        If possible, the implementation should raise a
        DeviceDisconnectException if the device disconnects.
        """
        raise NotImplementedError

    def device_cmd(self, cmd):
        """
        Pass the command to the device, NOT adding EOL.

        By default, the command is simply forwarded.
        """
        if not self.connected:
            return b'Device not connected.' + self.EOL
        if not self.initialized:
            return b'Device not initialized.' + self.EOL

        with self._lock:
            # Clear the "new data" flag so we can wait on the reply.
            self.recv_flag.clear()

            # Pass command to device
            _send_all(self.device_sock, cmd)

        # Wait for reply
        self.recv_flag.wait()

        # Just to be super safe: take the lock again
        with self._lock:
            # Reply is in the local buffer
            reply = self.recv_buffer

            # Clear the local buffer
            self.recv_buffer = b''

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

        if cmd == b'STOP':
            if not self.connected:
                return b'Device not connected'
            try:
                self.close_device()
                return b'OK'
            except BaseException as error:
                return str(error).encode()

        if cmd == b'START':
            if self.connected:
                return b'Device already connected'
            try:
                self.connect_device()
                self.init_device()
                return b'OK'
            except BaseException as error:
                return str(error).encode()

        if cmd == b'RESTART':
            if not self.connected:
                return b'Device not connected'
            try:
                self.close_device()
                self.connect_device()
                self.init_device()
                return b'OK'
            except BaseException as error:
                return str(error).encode()

        return super().parse_escaped(cmd)


class DriverBase:
    """
    Base for all drivers
    """

    TIMEOUT = 15
    NUM_CONNECTION_RETRY = 10
    ESCAPE_STRING = b'^'
    EOL = b'\n'
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
        if not hasattr(self, 'name'):
            self.name = self.__class__.__name__

        self.logger.debug(f'Driver {self.name} will connect to {self.address[0]}:{self.address[1]}')

        self.admin = None
        self.sock = None
        self.connected = False

        # Connect
        self.connect()

        # Request admin rights if needed
        if admin:
            self.ask_admin(True)

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
            self.logger.critical("Cannot connect to daemon.")
            raise DaemonException("Cannot connect to daemon.")

        self.connected = True
        self.logger.info(f'Driver {self.name} connected to {self.address[0]}:{self.address[1]}')

    def shutdown(self):
        """
        Clean shutdown of the driver.
        """
        try:
            self.sock.close()
        except:
            pass
        self.logger.debug(f'Driver {self.name}: connection to {self.address[0]}:{self.address[1]} closed.')

    def send(self, msg):
        """
        Send message (byte string) to socket.
        """
        try:
            _send_all(self.sock, msg)
        except socket.timeout:
            raise RuntimeError('Communication timed out')

    def recv(self):
        """
        Read message from socket.
        """
        r = _recv_all(self.sock, EOL=self.EOL)
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
        Send message to socket and return reply message, stripped from spaces and return carriages.
        (can be overloaded by subclass)
        """
        return self._send_recv(msg).strip(self.EOL)

    def ask_admin(self, ask=None):
        """
        Ask admin rights.
        Without and argument, returns whether we are admin.
        With True or False, request/rescind admin rights.
        """

        if ask is None:
            reply = self.send_recv(ESCAPE_STRING + b'AMIADMIN' + self.EOL)
            self.admin = (reply.strip(self.EOL) == b'True')
        elif ask is True:
            if self.ask_admin():
                self.logger.info('Already admin.')
                self.admin = True
            else:
                reply = self.send_recv(ESCAPE_STRING + b'ADMIN' + self.EOL)
                self.admin = True
                if reply.strip(self.EOL) != b'OK':
                    self.logger.warning(f'Could not request admin rights: {reply}')
                    self.admin = False
        elif ask is False:
            if not self.ask_admin():
                self.logger.info('Already not admin.')
                self.admin = False
            else:
                reply = self.send_recv(ESCAPE_STRING + b'NOADMIN' + self.EOL)
                self.admin = False
                if reply.strip(self.EOL) != b'OK':
                    self.logger.warning(f'Could not rescind admin rights: {reply}')

        return self.admin

    def get_stats(self):
        """
        Obtain stats from the daemon.
        """
        reply = self.send_recv(ESCAPE_STRING + b'STATS' + self.EOL)
        stats = json.loads(reply.decode())
        return stats

    def __del__(self):
        self.shutdown()


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