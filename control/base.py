"""
Base classes.

For now: Motors

TODO: store/load dial and user positions and limits on file to get more permanence.

User and dial positions are different and controlled by self.offset and self.scalar
Dial = (User*scalar)-offset
"""
import threading
import json
import logging
import os
import errno
import fcntl
import time
import atexit

from . import __DAEMON__, config, conf_path
from ..util.mqttlib import MQTTLostServerException, MQTTNoServerException, MQTTSendRelay


class MotorLimitsException(Exception):
    pass


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


class DriverBase(object):
    """
    Base class for all drivers. Implements polling and MQTT functionality.
    """

    logger = None

    def __init__(self, poll_interval=None):
        """
        Base class initialisation.
        Take care of logging, locking, and polling.
        """
        # Get logger if not set in subclass
        if self.logger is None:
            self.logger = logging.getLogger(self.__class__.__name__)

        # register exit functions
        atexit.register(self.shutdown)

        self.poll_abort = False
        if poll_interval is None:
            self.poll_interval = config['driver_poll_interval']
        else:
            self.poll_interval = poll_interval
            config['driver_poll_interval'] = poll_interval

        # Prepare thread lock
        self._lock = threading.Lock()

        # Prepare file lock
        # This will be the file descriptor when it is open
        self._fd = None

        # Set default name here. Can be overriden by subclass, for instance to allow multiple instances to run
        # concurrently
        self.name = self.__class__.__name__

    def start_thread(self):
        """
        Start thread, possibly waiting for initialisation to be complete
        """
        # Create file to be locked
        lockdir = os.path.join(conf_path, 'drivers', self.name)
        self.lockfile = os.path.join(lockdir, "lockfile")

        try:
            os.makedirs(lockdir)
        except OSError:
            pass
        if not os.path.exists(self.lockfile):
            open(self.lockfile, 'w').close()

        # Create a thread lock if this is not a daemon to make sure that initialization
        # completes before handing back control to user.
        if not __DAEMON__:
            self._init_lock = threading.Event()
        else:
            self._init_lock = None

        # Create and start thread
        self.logger.debug('Starting initialisation thread.')
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()

        # Wait for completion if in interactive mode
        if not __DAEMON__:
            self._init_lock.wait()
        return

    def _run(self):
        """
        Thread target. Initialise first, then enter the polling loop.
        """
        # Check if we can continue as daemon
        if __DAEMON__ and not self._check_lock():
            # Main waiting loop for daemons
            self.logger.info('Daemon could not acquire lock for initialisation. Waiting.')
            while not self._check_lock():
                time.sleep(.1)
        elif not __DAEMON__ and not self._get_lock():
            # This would happen with more than one interactive session
            # TODO: raise and error?
            self.logger.error('Could not acquire lock.')
            self._init_lock.set()
            return

        # Create mqtt communicator
        self.mqtt_relay = None
        try:
            self.mqtt_relay = MQTTSendRelay(name=self.name, qos=0)
        except (MQTTLostServerException, MQTTNoServerException):
            self.logger.warning("MQTT disconnected or unable to connect.")

        # Initialise
        self.logger.info('Initialising')
        self._init()

        # Tell main thread to unblock now that initialisation is complete
        if self._init_lock is not None:
            self._init_lock.set()

        # Start polling
        self._poll_with_mqtt()

        # We are now done.
        self._finish()

        # Release file lock if needed
        self._release_lock()

    def _init(self):
        """
        Driver initialisation. To be implemented by subclass.
        """
        pass

    def _finish(self):
        """
        Driver clean up on shutdown.
        """
        pass

    def _poll(self):
        """
        None MQTT polling tasks. To be implemented by subclass.
        """
        pass

    def mqtt_payload(self):
        """
        Generate MQTT payload as a dictionary {topic: payload}.
        """
        return {}

    def mqtt_pub(self, payload=None):
        """
        Publish on mqtt now. By default, push the payload generated by self.mqtt_payload.
        """
        if self.mqtt_relay:
            if payload is None:
                payload = self.mqtt_payload()
            self.mqtt_relay.publish(payload)

    def _poll_with_mqtt(self):
        """
        Do MQTT polling and user-defined polling.
        """
        self.logger.info('Entering polling loop')

        last_poll = 0

        while True:
            # Abort loop
            if self.poll_abort or not self._check_lock():
                # Clean up
                if self.mqtt_relay: self.mqtt_relay.client.disconnect()
                self.logger.info('User abort. Finishing polling.')
                return

            # Poll for abort faster than for the rest
            time.sleep(0.1)
            if time.time() < (last_poll + self.poll_interval):
                continue
            last_poll = time.time()

            # Send MQTT payloads
            self.mqtt_pub()

            # User-definer polling
            self._poll()


    def _check_lock(self):
        """
        Verify that lock has not been acquired. (to be run in daemon mode).
        """
        if self._fd is not None and not self._fd.closed:
            # That's the case where we have the lock
            return True
        with open(self.lockfile, 'r') as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
                return True
            except IOError as ex:
                if ex.errno != errno.EAGAIN:
                    raise
                return False

    def _get_lock(self):
        """
        Get and hold lock.
        """
        if self._fd is not None and not self._fd.closed:
            # We already have the lock
            return True
        self.logger.info('Acquiring lock.')
        # Open lock file
        fd = open(self.lockfile, 'r')
        # Acquire exclusive lock
        try:
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            self._fd = fd
            self.logger.info('Lock acquired.')
            return True
        except IOError as ex:
            if ex.errno != errno.EAGAIN:
                raise
            self._fd = None
            fd.close()
            self.logger.warn('Failed to acquire lock.')
            return False

    def _release_lock(self):
        if self._fd is not None and not self._fd.closed:
            self._fd.close()
            self._fd = None

    def shutdown(self):
        """
        Clean shutdown of the driver.
        """
        # Tell the polling thread to abort. This will ensure that all the rest is wrapped up
        self.logger.info('Shutting down.')
        self.poll_abort = True
        if self._thread and self._thread.is_alive():
            self.logger.info('Joining polling thread...')
            self._thread.join()
            self.logger.info('Done')


class MotorBase(object):
    """
    Representation of a motor (any object that has one translation / rotation axis).
    """
    def __init__(self, name, driver):
        # Store motor name and driver instance
        self.name = name
        self.driver = driver

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

    def _user_to_dial(self,user):
        """
        Converts user position to a dial position
        """
        return (user * self.scalar) - self.offset

    def _dial_to_user(self,dial):
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
            self.logger.warn('Could not find config file "%s". Continuing with default values.' % self.config_file)
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


class PseudoMotor(MotorBase):
    """
    Representation of a pseudomotor (combination of two or more motors)
    """
    def __init__(self, name, realmotors, logger, **kwargs):
        super(PseudoMotor, self).__init__(name=name, driver=None, logger=logger)
        self.realmotors = realmotors
        self.pseudotest = None  # test to see if inheritance is working

        # realmotors is a dictionary of motor objects?:
        # { 'rot': aerotech, 'sx': smaractx } etc.


