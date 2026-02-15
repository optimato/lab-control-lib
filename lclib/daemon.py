"""
Minimalist daemon utility to start drivers programmatically, also from a remote host. 

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import subprocess
import sys
import logging
import os

from . import proxydevice, proxycall, ProxyDeviceError, DAEMON_PORT
from . import logs

logger = logging.getLogger(__name__)
log_path = os.path.expanduser(f"~/.lclib/")
os.makedirs(log_path, exist_ok=True)
log_file = os.path.join(log_path, 'lclib-daemon.log')
logs.log_to_file(log_file, logobj=logger)

__all__ = ['start_daemon', 'daemon_server', 'daemon_client']

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
        logger.info('Daemon process pool initialized.')

    @proxycall()
    def start(self, lab, driver, loglevel='INFO', loglevel_global='INFO'):
        """
        Start the a local driver.
        
        Args:
            lab (str): The name of the lab package.
            driver (str): The name of the driver.
        """
        name = f'{lab}_{driver}'
        if name in self.processes:
            if self.processes[name].poll() is None:
                raise ValueError(f"Driver '{driver}' is already running.")
            else:
                # Remove the old process if it has completed
                del self.processes[name]

        command = [sys.executable, "-m", "lclib", lab, "lstart", driver, '-l', loglevel, '-L', loglevel_global]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            shell=False
        )

        # Monitor startup
        try:
            while True:
                line = process.stdout.readline()
                if not line:
                    # Process might have exited
                    retcode = process.poll()
                    if retcode is not None:
                        stderr_output = process.stderr.read()
                        logger.error(f"Driver {driver} initialization failed.")
                        logger.error(f"[stderr] {stderr_output.strip()}")    
                        return False, stderr_output
                    continue

                logger.debug(f"[stdout] {line.strip()}")
                if "RUNNING" in line:
                    break
        except Exception as e:
            process.kill()
            logger.error(f"Driver {driver} initialization failed.")
            logger.error(f"[stderr] {str(e)}")    
            return False, str(e)

        self.processes[name] = process
        logger.info(f"Started process {process.pid} for driver {driver} in lab {lab}.")
        return True, None

    def check_completed(self):
        """
        Return a dict of processes with their return codes.
        """
        completed = {}
        for n, p in self.processes.items():
            ret = p.poll()
            completed[n] = ret
        return completed

    @proxycall()
    def kill_process(self, lab, driver):
        """
        Kill the driver process.
        """
        # Fetch the process
        name = f'{lab}_{driver}'
        proc = self.processes.get(name)

        # Raise error if the process doesn't exist or has already returned
        if proc is None or proc.poll() is not None:
            raise RuntimeError(f'Driver {driver} (lab {lab}) is not running (or not managed but this daemon)')

        # Terminate
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
        Get a list of running processes.
        """
        return [name for name, p in self.processes.items() if p.poll() is None]