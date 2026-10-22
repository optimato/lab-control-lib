"""
Tests of the driver daemon (lclib/daemon.py) and of the driver startup (lstart).

A real daemon runs in its own process on a free port, with HOME pointing to a temporary
directory, and starts the drivers of the minimal lab in tests/fakelab.

Run with:
    pytest tests/test_daemon.py
"""
import logging
import os
import socket
import subprocess
import sys
import time

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)

# Test this working tree, not an installed copy of lclib
sys.path.insert(0, REPO_DIR)

from lclib import daemon as dd
from lclib import logs

LAB = 'fakelab'


def _free_port():
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _free_ports(n):
    """
    Return a port p such that the ports p to p + n - 1 are free.
    """
    while True:
        base = _free_port()
        try:
            for port in range(base, base + n):
                with socket.socket() as s:
                    s.bind(('', port))
            return base
        except (OSError, OverflowError):
            continue


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    """
    Environment of the daemon and of the command line calls.
    """
    home = tmp_path_factory.mktemp('home')
    python_path = [TESTS_DIR, REPO_DIR, os.environ.get('PYTHONPATH')]
    return dict(os.environ,
                HOME=str(home),
                USERPROFILE=str(home),
                LCLIB_DAEMON_PORT=str(_free_port()),
                FAKELAB_PORT=str(_free_ports(3)),
                FAKELAB_SLOW_INIT='5',
                PYTHONPATH=os.pathsep.join(p for p in python_path if p))

@pytest.fixture(scope='module')
def fakelab(env):
    """
    The fake lab package, imported in this process with the test environment.
    """
    with pytest.MonkeyPatch.context() as mp:
        for key in ('HOME', 'USERPROFILE', 'FAKELAB_PORT'):
            mp.setenv(key, env[key])
        mp.syspath_prepend(TESTS_DIR)
        import fakelab
        yield fakelab

@pytest.fixture(scope='module')
def daemon(env):
    """
    A daemon running in its own process. Yields a client connected to it.
    """
    address = ('localhost', int(env['LCLIB_DAEMON_PORT']))
    with open(os.path.join(env['HOME'], 'daemon.console'), 'wb') as console:
        proc = subprocess.Popen([sys.executable, '-m', 'lclib', '-d'], env=env,
                                stdout=console, stderr=subprocess.STDOUT)
    client = None
    t0 = time.time()
    while client is None:
        assert proc.poll() is None, 'The daemon exited at startup'
        assert time.time() - t0 < 30, 'The daemon did not start in time'
        time.sleep(.5)
        with logs.logging_muted():
            client = dd.daemon_client(address=address)

    yield client

    # Stop the drivers still running, then the daemon
    for name in client.running():
        client.kill_process(lab=LAB, driver=name[len(LAB) + 1:])
    client.disconnect()
    # Let the client thread finish (it logs on exit) before pytest closes its output capture
    client.serving_thread.join(5)
    proc.terminate()
    proc.wait(10)


def _status(client, driver):
    return client.status(lab=LAB, driver=driver)

def _wait_started(client, driver, timeout=60):
    """
    Wait until the driver is no longer starting, and return its status.
    """
    t0 = time.time()
    status = _status(client, driver)
    while status['state'] == 'starting' and time.time() - t0 < timeout:
        time.sleep(.2)
        status = _status(client, driver)
    return status

def _wait_exited(client, driver, timeout=15):
    """
    Wait until the driver process has exited, and return its status.
    """
    t0 = time.time()
    status = _status(client, driver)
    while status['state'] in ('starting', 'running') and time.time() - t0 < timeout:
        time.sleep(.2)
        status = _status(client, driver)
    return status

def _ensure_running(client, driver):
    """
    Start the driver unless it is already running. Return its status.
    """
    if _status(client, driver)['state'] not in ('starting', 'running'):
        client.start(lab=LAB, driver=driver)
    status = _wait_started(client, driver)
    assert status['state'] == 'running', status
    return status

def _ensure_stopped(client, driver):
    """
    Stop the driver if it is running.
    """
    if _status(client, driver)['state'] in ('starting', 'running'):
        client.kill_process(lab=LAB, driver=driver)
    assert _wait_exited(client, driver)['state'] in ('exited', 'unknown')

def _lc(env, *args):
    """
    Run the command line interface for the fake lab.
    """
    return subprocess.run([sys.executable, '-m', 'lclib', LAB, *args], env=env,
                          capture_output=True, text=True, timeout=120)


#
# Unit tests
#

def test_tail_file(tmp_path):
    path = tmp_path / 'big.txt'
    with open(path, 'wb') as f:
        for i in range(100000):
            f.write(f'line {i:06d}\n'.encode())
        f.write(b'invalid utf-8 \xff\xfe\n')

    assert dd.tail_file(str(path), 2) == ['line 099999', 'invalid utf-8 ��']

    # Only the end of the file is read: the truncated first line is dropped
    expected = [f'line {i:06d}' for i in range(99994, 100000)] + ['invalid utf-8 ��']
    assert dd.tail_file(str(path), None, max_bytes=100) == expected

    assert dd.tail_file(str(tmp_path / 'missing.txt')) == []

def test_json_files(tmp_path):
    path = str(tmp_path / 'record.json')
    dd.write_json_atomic(path, {'pid': 1, 'address': ['localhost', 5000]})
    assert dd.read_json(path) == {'pid': 1, 'address': ['localhost', 5000]}
    assert os.listdir(tmp_path) == ['record.json']   # no temporary file left behind

    assert dd.read_json(str(tmp_path / 'missing.json')) is None
    (tmp_path / 'bad.json').write_text('{not json')
    assert dd.read_json(str(tmp_path / 'bad.json')) is None

@pytest.mark.parametrize('name', ['../etc', 'a b', '', None])
def test_invalid_names_rejected(name):
    with pytest.raises(ValueError):
        dd._check_name(name)

def test_memory_log_handler_accepts_any_message():
    logger = logging.getLogger('lclib.test_memory_log')
    logger.setLevel(logging.INFO)
    logs.log_to_mem(logger)
    try:
        # A non-string message used to raise TypeError in the code calling the logger
        logger.error(ValueError('not a string'))
        logger.info({'unserializable': object()})
        try:
            1 / 0
        except ZeroDivisionError:
            logger.exception('with traceback')
        records = logger.in_memory_handler.get_logs()
    finally:
        logger.removeHandler(logger.in_memory_handler)

    assert records[0]['message'] == 'not a string'
    assert records[1]['message'].startswith("{'unserializable'")
    assert records[2]['message'] == 'with traceback'
    assert 'ZeroDivisionError' in records[2]['exc_text']


#
# Tests with a running daemon
#

def test_chatty_driver_does_not_freeze(daemon, fakelab):
    # The daemon used to read the driver output through pipes, and stopped reading once the
    # driver was running: the driver then blocked as soon as ~64 KB of output filled a pipe.
    _ensure_running(daemon, 'chatty')
    client = fakelab.Chatty.Client(admin=False)
    try:
        assert client.chat(20000) == 20000   # about 4 MB of output
        assert client.chat(10) == 10         # still responsive
    finally:
        client.disconnect()
    assert _status(daemon, 'chatty')['out_size'] > 1e6

def test_driver_failure_is_reported(daemon):
    daemon.start(lab=LAB, driver='broken')
    status = _wait_started(daemon, 'broken')
    assert status['state'] == 'exited'
    assert status['failed'] is True
    assert status['returncode'] == 1

    tail = '\n'.join(status['error_tail'])
    assert 'RuntimeError: broken on purpose' in tail
    # Logged once, not a second time as an uncaught exception
    assert tail.count('Traceback') == 1

def test_daemon_responsive_during_slow_start(daemon):
    # The slow driver needs 5 s to start: the daemon must not wait for it
    t0 = time.time()
    status = daemon.start(lab=LAB, driver='slow')
    assert status['state'] == 'starting'
    assert 'fakelab_slow' in daemon.running()
    assert time.time() - t0 < 2

    assert _wait_started(daemon, 'slow')['state'] == 'running'
    _ensure_stopped(daemon, 'slow')

def test_start_twice_refused(daemon):
    _ensure_running(daemon, 'chatty')
    with pytest.raises(RuntimeError, match='already running'):
        daemon.start(lab=LAB, driver='chatty')

def test_kill_process(daemon):
    _ensure_running(daemon, 'chatty')
    daemon.kill_process(lab=LAB, driver='chatty')
    status = _wait_exited(daemon, 'chatty')
    assert status['state'] == 'exited'
    assert status['failed'] is False

def test_unknown_driver_status(daemon):
    assert _status(daemon, 'nosuchdriver')['state'] == 'unknown'


#
# Command line tests
#

def test_cli_start(env, daemon):
    _ensure_stopped(daemon, 'chatty')
    result = _lc(env, 'start', 'chatty')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'RUNNING' in result.stdout and 'ALREADY' not in result.stdout

    result = _lc(env, 'start', 'chatty')
    assert 'ALREADY RUNNING' in result.stdout

def test_cli_start_failure(env, daemon):
    result = _lc(env, 'start', 'broken')
    assert result.returncode == 1
    assert 'FAILED' in result.stdout
    assert 'RuntimeError: broken on purpose' in result.stdout

def test_lstart_already_running(env, daemon):
    _ensure_running(daemon, 'chatty')
    result = _lc(env, 'lstart', 'chatty')
    assert result.returncode == 3
    assert 'ALREADY RUNNING' in result.stdout

def test_cli_without_daemon(env):
    result = _lc(dict(env, LCLIB_DAEMON_PORT=str(_free_port())), 'start', 'chatty')
    assert result.returncode == 2
    assert 'Daemon is not running' in result.stderr

def test_missing_dependency_reported(env):
    result = _lc(dict(env, FAKELAB_MISSING_DEP='1'), 'list')
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "No module named 'not_a_real_sdk'" in output
    assert 'Package fakelab not found' not in output
