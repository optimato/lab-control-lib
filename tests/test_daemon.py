"""
Tests of the driver daemon (lclib/daemon.py) and of the driver startup (lstart).

A real daemon runs in its own process on a free port, with HOME pointing to a temporary
directory, and starts the drivers of the minimal lab in tests/fakelab.

Run with:
    pytest tests/test_daemon.py
"""
import logging
import os
import signal
import socket
import subprocess
import sys
import time

import psutil
import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)

from lclib import daemon as dd
from lclib import logs, ProxyDeviceError

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
                FAKELAB_PORT=str(_free_ports(4)),
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
        try:
            client.kill_process(lab=LAB, driver=name[len(LAB) + 1:])
        except RuntimeError:
            # Exited in the meantime
            pass
    t0 = time.time()
    while client.running() and time.time() - t0 < 30:
        time.sleep(.2)
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

def _wait_exited(client, driver, timeout=30):
    """
    Wait until the driver process has exited, and return its status.
    """
    t0 = time.time()
    status = _status(client, driver)
    while status['state'] in ('starting', 'running', 'stopping') and time.time() - t0 < timeout:
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

def _process_gone(pid, timeout=5):
    """
    Wait until the process has exited (a zombie only waits to be reaped). Return True if it has.
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(.2)
    return False

def _log_line(path, text, timeout=10):
    """
    Wait for a line containing text in a log file, and return the last such line.
    """
    t0 = time.time()
    while True:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f if text in line]
        if lines or time.time() - t0 > timeout:
            break
        time.sleep(.2)
    assert lines, f'{text!r} not found in {path}'
    return lines[-1]

def _daemon_log_line(env, text, timeout=10):
    """
    Wait for a line containing text in the daemon log, and return the last such line.
    """
    return _log_line(os.path.join(env['HOME'], '.lclib', 'lclib-daemon.log'), text, timeout)

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

def test_kill_process_is_graceful(daemon):
    _ensure_running(daemon, 'chatty')
    t0 = time.time()
    status = daemon.kill_process(lab=LAB, driver='chatty')
    assert time.time() - t0 < 1
    assert status['state'] in ('stopping', 'exited')

    status = _wait_exited(daemon, 'chatty')
    assert status['state'] == 'exited'
    assert status['failed'] is False
    # Shut down through its server (not terminated), so its shutdown() ran
    assert status['returncode'] == 0
    with open(status['out_file'], encoding='utf-8') as f:
        assert 'chatty shutdown' in f.read()

def test_kill_process_terminates_stubborn_driver(daemon, fakelab, env):
    _ensure_running(daemon, 'stubborn')
    client = fakelab.Stubborn.Client(admin=False)
    child_pid = client.child_pid()
    client.disconnect()

    t0 = time.time()
    daemon.kill_process(lab=LAB, driver='stubborn')
    status = _wait_exited(daemon, 'stubborn')
    elapsed = time.time() - t0
    assert status['state'] == 'exited'
    assert status['failed'] is False
    # Its shutdown started, but never finished: terminated after the grace period
    assert dd.ProcessPool.STOP_GRACE_TIME <= elapsed < dd.ProcessPool.STOP_GRACE_TIME + 10
    with open(status['out_file'], encoding='utf-8') as f:
        assert 'stubborn shutdown started' in f.read()
    assert 'did not shut down' in _daemon_log_line(env, f"(pid {status['pid']}) did not shut down")

    # Its child process was terminated too
    assert _process_gone(child_pid), 'The child process of the driver is still running'

def test_kill_while_starting(daemon):
    _ensure_stopped(daemon, 'slow')
    daemon.start(lab=LAB, driver='slow')
    t0 = time.time()
    daemon.kill_process(lab=LAB, driver='slow')
    status = _wait_exited(daemon, 'slow')
    assert status['state'] == 'exited'
    assert status['failed'] is False
    # No server to ask yet, so no grace period
    assert time.time() - t0 < 5

def test_unexpected_exit_is_recorded(daemon, env):
    status = _ensure_running(daemon, 'chatty')
    pid = status['pid']
    spawn_file = os.path.join(os.path.dirname(status['out_file']), 'spawn.json')

    # Kill the driver behind the daemon's back
    os.kill(pid, getattr(signal, 'SIGKILL', signal.SIGTERM))

    line = _daemon_log_line(env, f'(pid {pid}) exited with')
    assert '[WARNING]' in line and line.endswith('Last output:')
    if hasattr(signal, 'SIGKILL'):
        assert 'signal SIGKILL' in line

    record = dd.read_json(spawn_file)
    assert record['ended'] is not None
    assert record['returncode'] != 0
    assert _status(daemon, 'chatty')['failed'] is True

def test_requested_stop_is_logged(daemon, env):
    pid = _ensure_running(daemon, 'chatty')['pid']
    daemon.kill_process(lab=LAB, driver='chatty')

    line = _daemon_log_line(env, f'(pid {pid}) exited with')
    assert '[INFO]' in line and 'Last output' not in line

#
# Errors in remote calls
#

def test_remote_call_errors_are_logged(daemon, fakelab):
    log_file = _ensure_running(daemon, 'chatty')['log_file']
    client = fakelab.Chatty.Client(admin=False)
    try:
        # The client gets the exception as before...
        with pytest.raises(ValueError, match='failing on purpose'):
            client.fail()
        # ... and a refused call raises a real ProxyDeviceError
        with pytest.raises(ProxyDeviceError):
            client.admin_only()
        client.fail_in_thread()
    finally:
        client.disconnect()

    # The driver log has the error with its traceback
    line = _log_line(log_file, "Call to fail failed: ValueError('failing on purpose')")
    assert '[ERROR]' in line
    with open(log_file, encoding='utf-8') as f:
        assert f.read().split(line, 1)[1].lstrip().startswith('Traceback')

    # A refused call is a warning, without traceback
    assert '[WARNING]' in _log_line(log_file, 'Call to admin_only refused')

    # An exception in a thread (e.g. a periodic call) is logged too
    _log_line(log_file, 'Uncaught exception in thread')
    _log_line(log_file, 'ValueError: failing in a thread')

def test_unpicklable_error_does_not_jam_driver(daemon, fakelab):
    _ensure_running(daemon, 'chatty')
    client = fakelab.Chatty.Client(admin=False)
    try:
        with pytest.raises(RuntimeError, match='could not be sent'):
            client.fail_unpicklable()
        # This used to fail with "Current of past non-blocking call still pending."
        assert client.wait_a_bit() == 'done'
    finally:
        client.disconnect()

#
# Log access
#

def test_tail_log_and_output(daemon, fakelab):
    status = _ensure_running(daemon, 'chatty')
    client = fakelab.Chatty.Client(admin=False)
    try:
        client.chat(5)
    finally:
        client.disconnect()

    # By default: the driver log file
    result = daemon.tail(lab=LAB, driver='chatty', n=10)
    assert result['source'] == 'log'
    assert result['path'] == status['log_file']
    assert len(result['lines']) == 10
    assert any('chatter 00000004' in line for line in result['lines'])

    # The process output (stdout and stderr)
    result = daemon.tail(lab=LAB, driver='chatty', n=10, source='out')
    assert result['source'] == 'out'
    assert result['path'] == status['out_file']
    assert 'stdout chatter 00000004' in result['lines']

def test_tail_failed_driver(daemon):
    daemon.start(lab=LAB, driver='broken')
    _wait_started(daemon, 'broken')

    # It never became ready: its log file is unknown, so the default is its output
    result = daemon.tail(lab=LAB, driver='broken')
    assert result['source'] == 'out'
    assert 'RuntimeError: broken on purpose' in result['lines']
    with pytest.raises(RuntimeError, match='never became ready'):
        daemon.tail(lab=LAB, driver='broken', source='log')

def test_tail_errors(daemon):
    with pytest.raises(RuntimeError, match='never started'):
        daemon.tail(lab=LAB, driver='nosuchdriver')
    _ensure_running(daemon, 'chatty')
    with pytest.raises(ValueError, match='Unknown source'):
        daemon.tail(lab=LAB, driver='chatty', source='nosuchsource')

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

def test_cli_forcekill(env, daemon):
    _ensure_running(daemon, 'chatty')
    result = _lc(env, 'forcekill', 'chatty')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'STOPPED' in result.stdout

    result = _lc(env, 'forcekill', 'chatty')
    assert result.returncode == 1
    assert 'is not running' in result.stderr

def test_cli_status(env, daemon):
    _ensure_running(daemon, 'chatty')
    daemon.start(lab=LAB, driver='broken')
    _wait_started(daemon, 'broken')

    result = _lc(env, 'status')
    assert result.returncode == 0, result.stdout + result.stderr

    # One row per driver: name, host, state[, uptime, pid]
    drivers = {'chatty', 'broken', 'slow', 'stubborn'}
    rows = {words[0]: words[1:] for words in map(str.split, result.stdout.splitlines())
            if words and words[0] in drivers}
    assert set(rows) == drivers
    assert rows['chatty'][:2] == ['control', 'RUNNING']
    assert rows['chatty'][3] == str(_status(daemon, 'chatty')['pid'])
    assert rows['broken'] == ['control', 'FAILED']

def test_cli_status_without_daemon(env):
    result = _lc(dict(env, LCLIB_DAEMON_PORT=str(_free_port())), 'status')
    assert result.returncode == 0
    assert 'UNKNOWN' in result.stdout
    assert 'Cannot reach the daemon on host control' in result.stdout
    assert 'refused' in result.stdout.lower()

def test_cli_log(env, daemon, fakelab):
    _ensure_running(daemon, 'chatty')
    client = fakelab.Chatty.Client(admin=False)
    try:
        client.chat(3)
    finally:
        client.disconnect()

    result = _lc(env, 'log', 'chatty', '-n', '20')
    assert result.returncode == 0, result.stdout + result.stderr
    assert '--- chatty log file:' in result.stdout
    assert 'chatter 00000002' in result.stdout

    result = _lc(env, 'log', 'chatty', '--out')
    assert '--- chatty process output:' in result.stdout
    assert 'stdout chatter 00000002' in result.stdout

    # A driver that never became ready: its output, with the error
    daemon.start(lab=LAB, driver='broken')
    _wait_started(daemon, 'broken')
    result = _lc(env, 'log', 'broken')
    assert '--- broken process output:' in result.stdout
    assert 'RuntimeError: broken on purpose' in result.stdout

def test_cli_log_unknown_driver(env):
    result = _lc(env, 'log', 'nosuchdriver')
    assert result.returncode == 2
    assert 'Unknown driver nosuchdriver' in result.stderr

def test_lstart_already_running(env, daemon):
    _ensure_running(daemon, 'chatty')
    result = _lc(env, 'lstart', 'chatty')
    assert result.returncode == 3
    assert 'ALREADY RUNNING' in result.stdout

def test_cli_without_daemon(env):
    result = _lc(dict(env, LCLIB_DAEMON_PORT=str(_free_port())), 'start', 'chatty')
    assert result.returncode == 2
    assert 'Cannot reach the daemon on host control' in result.stderr
    assert 'refused' in result.stderr.lower()

def test_missing_dependency_reported(env):
    result = _lc(dict(env, FAKELAB_MISSING_DEP='1'), 'list')
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "No module named 'not_a_real_sdk'" in output
    assert 'Package fakelab not found' not in output
