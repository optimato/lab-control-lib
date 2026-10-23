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
import signal
import time
import threading
import uuid

import psutil
import rpyc

from . import proxydevice, proxycall, ProxyDeviceError, DAEMON_PORT
from . import logs

logger = logging.getLogger(__name__)

__all__ = ['daemon_server', 'daemon_client', 'setup_daemon_logging', 'run_dir']

# Incremented when the daemon API changes, so that clients can detect old daemons
API_VERSION = 3

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

def _describe_returncode(returncode):
    """
    Human-readable description of a process return code.
    """
    if returncode is None:
        return 'unknown exit code'
    if returncode < 0:
        # POSIX: killed by a signal
        try:
            return f'signal {signal.Signals(-returncode).name}'
        except ValueError:
            return f'signal {-returncode}'
    return f'exit code {returncode}'

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

        # Used to find the child processes (e.g. started by a vendor library)
        try:
            self.proc = psutil.Process(popen.pid)
        except psutil.Error:
            self.proc = None

        # Set when the daemon has been asked to stop the process
        self.stopping = False

        # Set once the exit has been recorded by the daemon watcher
        self.exit_handled = False

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

    def wait(self, timeout):
        """
        Wait for the process to exit. Return True if it did.
        """
        try:
            self.popen.wait(timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def terminate_tree(self, timeout=5.):
        """
        Terminate the process and its descendants, and kill those that do not exit in time.
        Descendants go first: on Windows, the process might be a venv launcher running the
        actual interpreter.
        """
        try:
            children = self.proc.children(recursive=True) if self.proc is not None else []
        except psutil.Error:
            children = []

        for child in children:
            try:
                child.terminate()
            except psutil.Error:
                pass
        try:
            self.popen.terminate()
        except OSError:
            pass

        _, still_alive = psutil.wait_procs(children, timeout=timeout)
        for child in still_alive:
            try:
                child.kill()
            except psutil.Error:
                pass
        if not self.wait(timeout):
            self.popen.kill()
            self.wait(timeout)

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

    WATCH_INTERVAL = 1.     # Interval (in seconds) between checks for exited processes
    STOP_GRACE_TIME = 10.   # Time (in seconds) given to a driver to shut down before terminating it

    def __init__(self):
        self.processes = {}
        self._lock = threading.Lock()

        # Thread recording the exit of driver processes
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()

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
        elif mp.stopping:
            state = 'stopping'
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
              state: 'starting', 'running', 'stopping', 'exited', or 'unknown' (not started
                     by this daemon)
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
    def tail(self, lab, driver, n=200, source=None):
        """
        Get the last lines of a driver's log. This also works for drivers that are not
        running anymore, including the ones started by a previous daemon.

        Args:
            lab (str): The name of the lab package.
            driver (str): The name of the driver.
            n (int): The number of lines.
            source (str): 'log' for the driver log file, 'out' for the process output
                          (stdout and stderr). Default: 'log' if known, 'out' otherwise.

        Returns:
            dict: {'source': source, 'path': file path, 'lines': list of lines}
        """
        name = self._name(lab, driver)
        with self._lock:
            mp = self.processes.get(name)
        record = mp.record if mp is not None else read_json(self._spawn_file(name))
        if record is None:
            raise RuntimeError(f'Driver {driver} (lab {lab}) was never started by the daemon on this host.')

        # Only paths found in the run files are read, never paths provided by the client
        ready = read_json(record['ready_file'])
        log_file = ready.get('log_file') if ready else None
        if source is None:
            source = 'log' if log_file else 'out'
        if source == 'log':
            if not log_file:
                raise RuntimeError(f'The log file of driver {driver} is unknown (it never became ready): '
                                   f'use its output instead.')
            path = log_file
        elif source == 'out':
            path = record['out_file']
        else:
            raise ValueError(f"Unknown source {source!r} (should be 'log' or 'out').")
        return {'source': source, 'path': path, 'lines': tail_file(path, n)}

    @proxycall()
    def kill_process(self, lab, driver):
        """
        Stop the driver process. The driver is first asked to shut down through its server,
        and terminated if it is still running after a grace period. Returns immediately:
        use `status` to follow the shutdown.

        Returns:
            dict: the status of the driver (see `status`).
        """
        # Fetch the process
        name = self._name(lab, driver)
        with self._lock:
            mp = self.processes.get(name)

        # Raise error if the process doesn't exist or has already returned
        if mp is None or not mp.alive():
            raise RuntimeError(f'Driver {driver} (lab {lab}) is not running (or not managed by this daemon)')

        if not mp.stopping:
            mp.stopping = True
            mp.record['stop_requested'] = True
            self._save_record(name, mp.record)
            logger.info(f'Stopping driver {name} (pid {mp.pid}).')
            threading.Thread(target=self._stop_process, args=(name, mp), daemon=True).start()
        return self._status(name, mp)

    def _stop_process(self, name, mp):
        """
        Shut down a driver: through its server if possible, by terminating the process
        otherwise. Runs on its own thread.
        """
        try:
            if self._ask_shutdown(name, mp):
                if mp.wait(self.STOP_GRACE_TIME):
                    return
                logger.warning(f'Driver {name} (pid {mp.pid}) did not shut down within '
                               f'{self.STOP_GRACE_TIME:g} s: terminating it.')
            mp.terminate_tree()
        except Exception:
            logger.exception(f'Error while stopping driver {name}.')

    def _ask_shutdown(self, name, mp):
        """
        Ask the driver server to shut down (as `lc kill` does), so that the driver can
        release its device. Return True if the request was sent.
        """
        ready = read_json(mp.record['ready_file'])
        if ready is None:
            # Still starting: there is no server to ask yet
            return False
        host, port = ready['address']
        try:
            conn = rpyc.connect(host, port, config={'sync_request_timeout': self.STOP_GRACE_TIME})
            try:
                conn.root.kill()
            finally:
                conn.close()
        except EOFError:
            # Normal: the server closes the connection when shutting down
            pass
        except Exception as e:
            logger.warning(f'Could not ask driver {name} to shut down: {e!r}')
            return False
        return True

    @proxycall()
    def running(self):
        """
        Get a list of running processes (including the ones still starting).
        """
        with self._lock:
            items = list(self.processes.items())
        return [name for name, mp in items if mp.alive()]

    def _watch(self):
        """
        Record the exit of the managed processes. Runs on its own thread.
        """
        while True:
            time.sleep(self.WATCH_INTERVAL)
            try:
                with self._lock:
                    items = list(self.processes.items())
                for name, mp in items:
                    if not mp.exit_handled and not mp.alive():
                        mp.exit_handled = True
                        self._process_exited(name, mp)
            except Exception:
                logger.exception('Error in the process watcher.')

    def _process_exited(self, name, mp):
        """
        Save the exit code in spawn.json, and log the exit (with the end of the process
        output if the exit was not requested).
        """
        record = mp.record
        record['returncode'] = mp.returncode
        record['ended'] = time.time()
        self._save_record(name, record)

        msg = f"Driver {name} (pid {mp.pid}) exited with {_describe_returncode(record['returncode'])}"
        if record['stop_requested'] or record['returncode'] == 0:
            logger.info(msg + '.')
        else:
            tail = '\n'.join(tail_file(record['out_file'], 20))
            logger.warning(f'{msg}. Last output:\n{tail}')