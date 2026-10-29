"""
Minimal lab package used by the daemon tests (tests/test_daemon.py).

All drivers run on localhost. Their ports start at the value of the environment variable
FAKELAB_PORT, so that the tests never collide with a running lab.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import logging
import os
import subprocess
import sys
import threading
import time

import lclib
from lclib import register_driver, proxydevice, proxycall
from lclib.base import DriverBase
from lclib.util import Future

# To test how a missing dependency of a lab package (e.g. a vendor SDK) is reported
if os.environ.get('FAKELAB_MISSING_DEP'):
    import not_a_real_sdk

BASE_PORT = int(os.environ.get('FAKELAB_PORT', 15000))

# Hack: add 'localhost' as valid ip (as in examples/dummylab)
lclib.local_ip_list.append('localhost')

lclib.init(lab_name='FakeLab', host_ips={'control': 'localhost'})

# Loggers outside lclib: one of the lab package, one of another library
logger = logging.getLogger(__name__)
other_logger = logging.getLogger('otherlibrary')


class UnpicklableError(Exception):
    """
    An exception that cannot be sent to a client.
    """

    def __init__(self):
        super().__init__('cannot be pickled')
        self.lock = threading.Lock()


@register_driver
@proxydevice(address=('localhost', BASE_PORT))
class Chatty(DriverBase):
    """
    A driver that can produce a lot of output.
    """

    def __init__(self):
        super().__init__()
        # Metadata, part of the status (see DriverBase.status)
        self.metacalls.update({'temperature': lambda: 21.5,
                               'settings': lambda: {'speed': 2, 'mode': 'fast'}})
        self.initialized = True

    @proxycall()
    def chat(self, n):
        """
        Write n warnings to the log (and console) and n lines to stdout.
        """
        for i in range(n):
            self.logger.warning(f'chatter {i:08d} ' + 'x' * 100)
            sys.stdout.write(f'stdout chatter {i:08d}\n')
        return n

    @proxycall()
    def busy(self, t):
        """
        A long blocking call (holds the instance lock).
        """
        time.sleep(t)

    @proxycall()
    def say(self, text):
        self.logger.warning(text)

    @proxycall()
    def debug_message(self):
        self.logger.debug('driver debug message')

    @proxycall()
    def log_outside(self):
        """
        Log through loggers outside lclib.
        """
        logger.info('lab package info')
        other_logger.info('other library info')
        other_logger.warning('other library warning')

    @proxycall()
    def fail(self):
        raise ValueError('failing on purpose')

    @proxycall(admin=True)
    def admin_only(self):
        return True

    @proxycall(block=False)
    def fail_unpicklable(self):
        raise UnpicklableError()

    @proxycall(block=False)
    def wait_a_bit(self):
        time.sleep(.1)
        return 'done'

    @proxycall()
    def fail_in_thread(self):
        """
        Start a thread that fails (as a failing periodic call would).
        """
        Future(self._fail)

    def _fail(self):
        raise ValueError('failing in a thread')

    def shutdown(self):
        self.logger.warning('chatty shutdown')


@register_driver
@proxydevice(address=('localhost', BASE_PORT + 1))
class Broken(DriverBase):
    """
    A driver that fails during initialization.
    """

    def __init__(self):
        super().__init__()
        raise RuntimeError('broken on purpose')


@register_driver
@proxydevice(address=('localhost', BASE_PORT + 2))
class Slow(DriverBase):
    """
    A driver with a slow initialization (FAKELAB_SLOW_INIT seconds).
    """

    def __init__(self):
        super().__init__()
        time.sleep(float(os.environ.get('FAKELAB_SLOW_INIT', 5)))


@register_driver
@proxydevice(address=('localhost', BASE_PORT + 3))
class Stubborn(DriverBase):
    """
    A driver with a child process, whose shutdown never finishes.
    """

    def __init__(self):
        super().__init__()
        self.child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])

    @proxycall()
    def child_pid(self):
        return self.child.pid

    def shutdown(self):
        self.logger.warning('stubborn shutdown started')
        time.sleep(600)
