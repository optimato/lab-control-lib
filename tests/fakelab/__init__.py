"""
Minimal lab package used by the daemon tests (tests/test_daemon.py).

All drivers run on localhost. Their ports start at the value of the environment variable
FAKELAB_PORT, so that the tests never collide with a running lab.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os
import sys
import time

import lclib
from lclib import register_driver, proxydevice, proxycall
from lclib.base import DriverBase

# To test how a missing dependency of a lab package (e.g. a vendor SDK) is reported
if os.environ.get('FAKELAB_MISSING_DEP'):
    import not_a_real_sdk

BASE_PORT = int(os.environ.get('FAKELAB_PORT', 15000))

# Hack: add 'localhost' as valid ip (as in examples/dummylab)
lclib.local_ip_list.append('localhost')

lclib.init(lab_name='FakeLab', host_ips={'control': 'localhost'})


@register_driver
@proxydevice(address=('localhost', BASE_PORT))
class Chatty(DriverBase):
    """
    A driver that can produce a lot of output.
    """

    @proxycall()
    def chat(self, n):
        """
        Write n warnings to the log (and console) and n lines to stdout.
        """
        for i in range(n):
            self.logger.warning(f'chatter {i:08d} ' + 'x' * 100)
            sys.stdout.write(f'stdout chatter {i:08d}\n')
        return n


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
