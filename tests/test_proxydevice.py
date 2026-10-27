"""
Testing the rpyc implementation of proxydevice.

The tests run a proxy server for class A and a client in this process.

To play with a server and a client in two processes:
    python tests/test_proxydevice.py server
then, from ipython:
    %run tests/test_proxydevice.py interactive
"""

from lclib import proxycall, proxydevice, ProxyDeviceError, logs

import atexit
import logging
import socket
import threading
import time

import pytest
import rpyc


@proxydevice(address=("127.0.0.1", 5055))
class A:
    def __init__(self, x=1):
        self.x = x
        self.a = "abc"
        self.stop = False
        print('Class A is initialized.')

    # A non-exposed call
    def do_something(self, y):
        self.x += y

    # An exposed call
    @proxycall()
    def get_multiple(self, y):
        print('Called get_multiple')
        return self.x * y

    # An exposed call that produces an error
    @proxycall()
    def wrong_call(self):
        print('Called wrong_call')
        raise RuntimeError('oops')

    # A long blocking call (holds the instance lock)
    @proxycall()
    def slow(self, t):
        time.sleep(t)

    # An exposed input
    @proxycall()
    def interact(self):
        print('Called interact')
        self.z = input('What is z?')

    # An exposed call allowed only for the client with admin rights
    @proxycall(admin=True)
    def set_a(self, a):
        print('Called set_a')
        self.a = a

    # A long task. Must be made non-blocking otherwise the sever will wait for return value
    @proxycall(admin=True, block=False)
    def long_task(self):
        print('Called long_task')
        for i in range(10):
            print(chr(i + 65))
            time.sleep(1)
            if self.stop:
                self.stop = False
                break
        return 1

    # An long task that produces an error
    @proxycall(block=False)
    def long_task_err(self):
        print('Called long_task_err')
        time.sleep(1)
        raise RuntimeError('oops')

    # Declaring the abort call, to be sent when ctrl-C is hit during a long call.
    @proxycall(interrupt=True)
    def abort(self):
        print("Aborting the long call!")
        self.stop = True

    # An exposed property
    @proxycall()
    @property
    def x_value(self):
        return self.x

    @x_value.setter
    def x_value(self, v):
        self.x = v


def _free_port():
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


class _ListHandler(logging.Handler):
    """
    Keep log records in a list.
    """

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture(scope='module')
def server():
    """
    Proxy server for class A, running in this process on a free port.
    """
    s = A.Server(address=('127.0.0.1', _free_port()))
    yield s
    s.stop()
    # Already stopped: no need to stop again at exit, when pytest output capture is closed
    atexit.unregister(s.stop)

@pytest.fixture(scope='module')
def client(server):
    """
    A client connected to the server (admin by default).
    """
    c = A.Client(address=server.ADDRESS)
    yield c
    c.disconnect()
    # Let the client thread finish (it logs on exit) before pytest closes its output capture
    c.serving_thread.join(5)


def test_admin_rights(client):
    # The client is admin by default
    assert client.ask_admin()
    client.set_a(1)

    # Without admin rights, admin calls are refused
    client.ask_admin(False)
    try:
        with pytest.raises(ProxyDeviceError):
            client.set_a(2)
    finally:
        client.ask_admin(True)
    assert client.ask_admin()

def test_exposed_method(client):
    client.x_value = 2
    assert client.get_multiple(3) == 6

def test_property(client):
    client.x_value = 'abc'
    assert client.x_value == 'abc'

def test_errors_in_calls(client):
    with pytest.raises(RuntimeError, match='oops'):
        client.wrong_call()
    with pytest.raises(TypeError):
        client.get_multiple({})

def test_errors_are_logged_by_server(server, client):
    handler = _ListHandler()
    server.logger.addHandler(handler)
    try:
        with pytest.raises(RuntimeError):
            client.wrong_call()
        client.ask_admin(False)
        try:
            with pytest.raises(ProxyDeviceError):
                client.set_a(2)
        finally:
            client.ask_admin(True)
    finally:
        server.logger.removeHandler(handler)

    messages = [(r.levelname, r.getMessage()) for r in handler.records]
    assert ('ERROR', "Call to wrong_call failed: RuntimeError('oops')") in messages
    assert ('WARNING', 'Call to set_a refused: Non-admin clients cannot run method set_a.') in messages

    # The error is logged with its traceback
    error = next(r for r in handler.records if r.levelname == 'ERROR')
    assert error.exc_info is not None

def test_logger_names(server, client):
    # The proxy server and the clients log as children of the driver logger ('lclib.a')
    assert server.logger.name == 'lclib.a.proxy'
    assert client.logger.name == 'lclib.a.client'

    # Shown without the 'lclib.' prefix
    record = server.logger.makeRecord(server.logger.name, logging.INFO, __file__, 0, 'hello', None, None)
    for formatter in (logs.dual_formatter, logs.extended_formatter):
        line = formatter.format(record)
        assert '[a.proxy]' in line and 'lclib.' not in line

def test_proxy_level_independent_of_driver(server):
    # The proxy has its own level (the global level when created)...
    assert server.logger.level != logging.NOTSET
    proxy_level = server.logger.getEffectiveLevel()

    # ... so a driver set to DEBUG does not make the proxy verbose
    driver_logger = logging.getLogger('lclib.a')
    level = driver_logger.level
    driver_logger.setLevel(logging.DEBUG)
    try:
        assert server.logger.getEffectiveLevel() == proxy_level
    finally:
        driver_logger.setLevel(level)

def test_log_level(server, client):
    driver_logger = logging.getLogger('lclib.a')
    driver_level, proxy_level = driver_logger.level, server.logger.level
    try:
        # The driver level by default, given by name (any case) or number
        assert client.set_log_level('debug') == 'DEBUG'
        assert driver_logger.level == logging.DEBUG
        assert client.get_log_level() == 'DEBUG'
        assert server.logger.level == proxy_level

        # The proxy level, separately
        assert client.set_log_level(30, part='proxy') == 'WARNING'
        assert client.get_log_level('proxy') == 'WARNING'
        assert client.get_log_level() == 'DEBUG'

        with pytest.raises(ValueError, match='Unknown log level'):
            client.set_log_level('loud')
        with pytest.raises(ValueError, match='Unknown part'):
            client.set_log_level('INFO', part='everything')
        # A has no configuration to save the level in
        with pytest.raises(ValueError, match='can be saved'):
            client.set_log_level('INFO', save=True)
    finally:
        driver_logger.setLevel(driver_level)
        server.logger.setLevel(proxy_level)

def test_log_level_while_busy(server, client):
    # A long call holds the instance lock (other proxycalls wait for it)...
    busy = threading.Thread(target=client.slow, args=(3,))
    busy.start()
    time.sleep(.5)

    # ... but the log level can be changed anyway (from another connection)
    other = A.Client(admin=False, address=server.ADDRESS)
    level = other.get_log_level()
    try:
        t0 = time.time()
        assert other.set_log_level('DEBUG') == 'DEBUG'
        assert time.time() - t0 < 1
    finally:
        other.set_log_level(level)
        other.disconnect()
        other.serving_thread.join(5)
        busy.join()

def test_routine_proxy_messages_are_debug(server):
    handler = _ListHandler()
    server.logger.addHandler(handler)
    level = server.logger.level
    server.logger.setLevel(logging.DEBUG)
    try:
        c = A.Client(admin=False, address=server.ADDRESS)
        c.disconnect()
        c.serving_thread.join(5)
        # The server notices the disconnection on its own thread
        t0 = time.time()
        while not any('disconnected' in r.getMessage() for r in handler.records) and time.time() - t0 < 5:
            time.sleep(.05)
    finally:
        server.logger.removeHandler(handler)
        server.logger.setLevel(level)

    disconnected = [r for r in handler.records if 'disconnected' in r.getMessage()]
    assert disconnected
    assert all(r.levelno == logging.DEBUG for r in disconnected)

def test_non_blocking_call_with_abort(client):
    # long_task takes 10 s unless aborted: abort it from another thread after 1.5 s
    timer = threading.Timer(1.5, client.abort)
    timer.start()
    t0 = time.time()
    assert client.long_task() == 1
    assert time.time() - t0 < 5
    timer.join()

def test_non_blocking_call_error(client):
    with pytest.raises(RuntimeError, match='oops'):
        client.long_task_err()

def test_non_blocking_call_in_background(client):
    # With clean=False, a non-blocking call returns immediately
    client.clean = False
    try:
        assert client.long_task() == {'result': None}
        client.abort()
        t0 = time.time()
        while client.awaited_result is None and time.time() - t0 < 5:
            time.sleep(.1)
    finally:
        client.clean = True
    assert client.awaited_result == {'result': 1, 'error': None}

def test_connection_error_gives_reason():
    port = _free_port()
    with pytest.raises(ProxyDeviceError, match=f'127.0.0.1:{port} failed') as info:
        A.Client(address=('127.0.0.1', port))
    assert 'refused' in str(info.value).lower()
    assert isinstance(info.value.__cause__, ConnectionRefusedError)

def test_client_retries_after_connection_timeout(server, monkeypatch):
    # Behind a firewall (typically on Windows), connecting to a port without server times out
    # instead of being refused. The client must keep trying.
    real_connect = rpyc.connect
    attempts = []

    def connect_timing_out_once(*args, **kwargs):
        attempts.append(time.time())
        if len(attempts) == 1:
            raise TimeoutError('timed out')
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(rpyc, 'connect', connect_timing_out_once)
    monkeypatch.setattr(A.Client, 'RECONNECT_INTERVAL', .1)
    c = A.Client(admin=False, address=server.ADDRESS, reconnect='always')
    try:
        t0 = time.time()
        while not c.connected and time.time() - t0 < 5:
            time.sleep(.05)
        assert c.connected
        assert len(attempts) == 2
    finally:
        c.disconnect()
        c.serving_thread.join(5)

def test_input_is_asked_to_admin_client(server, client, monkeypatch):
    # input() on the server side is answered by the admin client (here, in this process)
    monkeypatch.setattr('builtins.input', lambda prompt=None: 'typed on the client')
    client.interact()
    assert server.instance.z == 'typed on the client'


if __name__ == "__main__":
    """
    Calling from the command line with the option 'server' starts the server and instantiate
    the test class A.

    Otherwise, it is possible to "%run ... interactive" from ipython and play with the client.
    """
    import sys
    print(sys.argv)
    if sys.argv[1] == 'server':
        s = A.Server()
        s.wait()
        sys.exit(0)
    elif sys.argv[1] == 'interactive':
        c = A.Client()
