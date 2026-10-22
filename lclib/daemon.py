"""
Minimalist daemon utility to start drivers programmatically, also from a remote host. 

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import subprocess
import sys
import logging
import os
import re
import json
import time
import threading
import uuid

from . import proxydevice, proxycall, ProxyDeviceError, DAEMON_PORT
from . import logs

logger = logging.getLogger(__name__)

__all__ = ['daemon_server', 'daemon_client', 'setup_daemon_logging', 'run_dir']

# Incremented when the daemon API changes, so that clients can detect old daemons
API_VERSION = 2

# Number of runs (output and ready files) kept for each driver
KEEP_RUNS = 10

_valid_name = re.compile(r'^[A-Za-z0-9_.-]+$')

def setup_daemon_logging(level=logging.INFO):
    """
    Configure logging for the daemon process: log to ~/.lclib/lclib-daemon.log
    (and to the console, through the lclib logger).

    This is called only by the daemon process: other processes importing this module
    do not write to the daemon log.
    """
    log_path = os.path.expanduser('~/.lclib/')
    os.makedirs(log_path, exist_ok=True)
    logs.log_to_file(os.path.join(log_path, 'lclib-daemon.log'), logobj=logger,
                     max_bytes=5 * 1024 * 1024, backup_count=5)
    logger.setLevel(level)

def run_dir():
    """
    Directory where the daemon stores the driver run files. Defaults to ~/.lclib/run,
    can be overridden with the environment variable LCLIB_RUN_DIR.
    """
    return os.environ.get('LCLIB_RUN_DIR') or os.path.join(os.path.expanduser('~/.lclib'), 'run')

def write_json_atomic(path, data):
    """
    Write data as JSON, such that readers never see a partially written file.
    """
    tmp = f'{path}.{uuid.uuid4().hex}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)

    # On Windows, replacing fails while another handle is open on the target
    # (a reader, an antivirus scan): retry a few times.
    retries = 10
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            retries -= 1
            if retries == 0:
                os.remove(tmp)
                raise
            time.sleep(.05)

def read_json(path):
    """
    Read a JSON file. Return None if it does not exist or cannot be parsed.
    """
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def tail_file(path, n=50, max_bytes=1024 * 1024):
    """
    Return the last n lines of a text file (all lines if n is None), reading at most
    max_bytes from its end. Return an empty list if the file cannot be read.
    """
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read(max_bytes)
    except OSError:
        return []
    lines = data.decode('utf-8', errors='replace').splitlines()
    if size > max_bytes:
        # The first line is most likely truncated
        lines = lines[1:]
    return lines[-n:] if n else lines

def _check_name(name):
    """
    Lab and driver names are used to build file paths: allow only safe characters.
    """
    if not isinstance(name, str) or not _valid_name.match(name):
        raise ValueError(f'Invalid name: {name!r}')
    return name

def _popen(command, **kwargs):
    """
    Start a driver process, detached from the daemon.
    """
    if sys.platform == 'win32':
        # Hidden console of its own, and no Ctrl-C propagation
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(command, creationflags=flags, **kwargs)

    # New session: signals sent to the daemon's process group do not reach the driver
    return subprocess.Popen(command, start_new_session=True, **kwargs)

def _prune_runs(driver_dir, keep):
    """
    Remove the output and ready files of all but the last `keep` runs.
    Files still in use (on Windows) are left alone.
    """
    try:
        files = os.listdir(driver_dir)
    except OSError:
        return
    start_ids = sorted(f[:-len('.out')] for f in files if f.endswith('.out'))
    for start_id in start_ids[:-keep]:
        for f in (f'{start_id}.out', f'ready-{start_id}.json'):
            try:
                os.remove(os.path.join(driver_dir, f))
            except OSError:
                pass


class ManagedProcess:
    """
    A driver process started by the daemon, with its run record (the content of spawn.json).
    """

    def __init__(self, record, popen):
        self.record = record
        self.popen = popen

    @property
    def pid(self):
        return self.record['pid']

    @property
    def returncode(self):
        """
        Exit code of the process (None if it is running).
        """
        return self.popen.poll()

    def alive(self):
        """
        True if the process is running.
        """
        return self.popen.poll() is None

def daemon_server():
    """
    Create ProcessPool daemon server.
    """
    return ProcessPool.Server(address=('localhost', DAEMON_PORT))

def daemon_client(address=None, **kwargs):
    """
    Connect to the daemon and return a client.
    
    Args:
        address (tuple): The address of the daemon (ip, port).
        
    Returns:
        client: A client connected to the daemon (or None if failed).
    """
    if address is None:
        # Default to localhost
        address = ('localhost', DAEMON_PORT)
    try:
        d = ProcessPool.Client(address=address, **kwargs)
    except ProxyDeviceError as e:
        logger.error(f"Failed to connect to daemon at {address}: {e}")
        return None
    return d

@proxydevice()
class ProcessPool:
    """
    A process pool to manage driver instantiations.
    """

    def __init__(self):
        self.processes = {}
        self._lock = threading.Lock()
        logger.info(f'Daemon process pool initialized (run directory: {run_dir()}).')

    @staticmethod
    def _name(lab, driver):
        return f'{_check_name(lab)}_{_check_name(driver)}'

    @staticmethod
    def _spawn_file(name):
        return os.path.join(run_dir(), name, 'spawn.json')

    @proxycall()
    def api_version(self):
        """
        Version of the daemon API.
        """
        return API_VERSION

    @proxycall()
    def start(self, lab, driver, loglevel=None, loglevel_global=None):
        """
        Start a local driver. Returns immediately: use `status` to follow the startup.

        Args:
            lab (str): The name of the lab package.
            driver (str): The name of the driver.
            loglevel (str): Log level of the driver (None: lstart default).
            loglevel_global (str): Log level of all components (None: lstart default).

        Returns:
            dict: the status of the driver (see `status`).
        """
        name = self._name(lab, driver)
        with self._lock:
            mp = self.processes.get(name)
            if mp is not None and mp.alive():
                raise RuntimeError(f"Driver '{driver}' is already running.")
            mp = self._spawn(lab, driver, loglevel, loglevel_global)
            self.processes[name] = mp
        logger.info(f"Started process {mp.pid} for driver {driver} in lab {lab} (output in {mp.record['out_file']}).")
        return self._status(name, mp)

    def _spawn(self, lab, driver, loglevel, loglevel_global):
        """
        Start the driver process, with its output redirected to a file.
        The daemon never reads the output, so the driver can never block on it.
        """
        driver_dir = os.path.join(run_dir(), f'{lab}_{driver}')
        os.makedirs(driver_dir, exist_ok=True)

        # Unique ID for this run. The timestamp makes runs sort chronologically.
        start_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        out_file = os.path.join(driver_dir, f'{start_id}.out')
        ready_file = os.path.join(driver_dir, f'ready-{start_id}.json')

        command = [sys.executable, '-m', 'lclib', lab, 'lstart', driver,
                   '--ready-file', ready_file, '--console-level', 'WARNING']
        if loglevel is not None:
            command += ['-l', str(loglevel)]
        if loglevel_global is not None:
            command += ['-L', str(loglevel_global)]

        # Unbuffered output (nothing lost on a crash), encoding independent of the platform,
        # and traceback dump on fatal errors (e.g. segfault in a vendor library).
        env = dict(os.environ,
                   PYTHONUNBUFFERED='1',
                   PYTHONIOENCODING='utf-8:backslashreplace',
                   PYTHONFAULTHANDLER='1')

        # The child inherits the output file, so the daemon can close it right away.
        with open(out_file, 'ab') as out:
            popen = _popen(command,
                           stdin=subprocess.DEVNULL,
                           stdout=out,
                           stderr=subprocess.STDOUT,
                           cwd=os.path.expanduser('~'),
                           env=env)

        record = {'lab': lab,
                  'driver': driver,
                  'start_id': start_id,
                  'pid': popen.pid,
                  'command': command,
                  'started': time.time(),
                  'out_file': out_file,
                  'ready_file': ready_file,
                  'stop_requested': False,
                  'returncode': None,
                  'ended': None}
        write_json_atomic(os.path.join(driver_dir, 'spawn.json'), record)
        _prune_runs(driver_dir, keep=KEEP_RUNS)
        return ManagedProcess(record, popen)

    def _save_record(self, name, record):
        """
        Update spawn.json.
        """
        try:
            write_json_atomic(self._spawn_file(name), record)
        except OSError as e:
            logger.warning(f'Could not save the run record of {name}: {e!r}')

    def _status(self, name, mp):
        """
        Status of a managed process.
        """
        returncode = mp.returncode
        if returncode is not None:
            state = 'exited'
        elif read_json(mp.record['ready_file']) is not None:
            state = 'running'
        else:
            state = 'starting'
        return self._status_dict(name, mp.record, state, returncode)

    @staticmethod
    def _status_dict(name, record, state, returncode):
        """
        Build the status dictionary sent to clients (builtin types only).
        """
        ready = read_json(record['ready_file'])
        try:
            out_size = os.path.getsize(record['out_file'])
        except OSError:
            out_size = None

        status = {'name': name,
                  'state': state,
                  'pid': record['pid'],
                  'started': record['started'],
                  'uptime': (record.get('ended') or time.time()) - record['started'],
                  'address': ready.get('address') if ready else None,
                  'log_file': ready.get('log_file') if ready else None,
                  'out_file': record['out_file'],
                  'out_size': out_size,
                  'returncode': returncode,
                  'failed': None,
                  'error_tail': None}

        if state == 'exited':
            if record.get('stop_requested'):
                status['failed'] = False
            elif ready is None:
                # Never became ready
                status['failed'] = True
            elif returncode is not None:
                status['failed'] = (returncode != 0)
            status['error_tail'] = tail_file(record['out_file'], 30)
        return status

    @proxycall()
    def status(self, lab, driver):
        """
        Get the status of a driver started by this daemon.

        Args:
            lab (str): The name of the lab package.
            driver (str): The name of the driver.

        Returns:
            dict with keys:
              state: 'starting', 'running', 'exited', or 'unknown' (not started by this daemon)
              failed: for exited drivers, True if the driver failed to start or crashed
              error_tail: for exited drivers, the last lines of the process output
              pid, started, uptime, address, log_file, out_file, out_size, returncode
        """
        name = self._name(lab, driver)
        with self._lock:
            mp = self.processes.get(name)
        if mp is None:
            return {'name': name, 'state': 'unknown'}
        return self._status(name, mp)

    @proxycall()
    def status_all(self):
        """
        Status of all drivers managed by this daemon, as a dict {'<lab>_<driver>': status}.
        """
        with self._lock:
            items = list(self.processes.items())
        return {name: self._status(name, mp) for name, mp in items}

    @proxycall()
    def kill_process(self, lab, driver):
        """
        Kill the driver process.
        """
        # Fetch the process
        name = self._name(lab, driver)
        with self._lock:
            mp = self.processes.get(name)

        # Raise error if the process doesn't exist or has already returned
        if mp is None or not mp.alive():
            raise RuntimeError(f'Driver {driver} (lab {lab}) is not running (or not managed by this daemon)')

        # Terminate
        mp.record['stop_requested'] = True
        self._save_record(name, mp.record)
        proc = mp.popen
        proc.terminate()
        try:
            proc.wait(timeout=5)
            logger.info(f"Process {proc.pid} for driver {driver} terminated.")
        except subprocess.TimeoutExpired:
            logger.warning(f"Process {proc.pid} for driver {driver} did not terminate, killing it.")
            proc.kill()

    @proxycall()
    def running(self):
        """
        Get a list of running processes (including the ones still starting).
        """
        with self._lock:
            items = list(self.processes.items())
        return [name for name, mp in items if mp.alive()]