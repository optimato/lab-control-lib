"""
Dummy controller for testing purposes.

* On one computer run dummy_device (that's the controller)
* On another computer create an instance of DummyDeamon and run with DummyDaemon.listen()
* On a third computer (or the same as Daemon) create an instance of Dummy, which connects upon construction.
"""

import time
import atexit
import socket
import multiprocessing

from .base import MotorBase, DriverBase, SocketDeviceServerBase, admin_only, emergency_stop, _recv_all
from . import motors
from .ui_utils import ask_yes_no

__all__ = ['DummyDeamon', 'Dummy', 'Motor']

DUMMY_DAEMON_ADDRESS = "127.0.0.1"
DUMMY_DAEMON_PORT = 15000
DUMMY_DEVICE_ADDRESS = "127.0.0.1"
DUMMY_DEVICE_PORT = 8000


class DummyDeamon(SocketDeviceServerBase):
    """
    Dummy Daemon
    """
    DEFAULT_SERVING_ADDRESS = (DUMMY_DAEMON_ADDRESS, DUMMY_DAEMON_PORT)
    DEFAULT_DEVICE_ADDRESS = (DUMMY_DEVICE_ADDRESS, DUMMY_DEVICE_PORT)

    def __init__(self, serving_address=None, device_address=None):
        if serving_address is None:
            serving_address = self.DEFAULT_SERVING_ADDRESS
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS
        super().__init__(serving_address=serving_address, device_address=device_address)

    def init_device(self):
        """
        Device initialization.
        """
        # try reading something back
        self.initialized = True
        hello = self.device_cmd('HELLO\n')
        self.logger.debug('Reply was %s.' % hello.strip())
        return

    def wait_call(self):
        self.device_cmd('STATUS\n')


class Dummy(DriverBase):
    """
    Driver for the Aerotech rotation stage.
    """

    # temporization for rapid status checks during moves.
    POLL_INTERVAL = 0.01

    def __init__(self, admin=True):
        """
        Connect to daemon.
        """
        super().__init__(address=(DUMMY_DAEMON_ADDRESS, DUMMY_DAEMON_PORT), admin=admin)

        reply = self.do_init()
        self.logger.info('Do init replied %s' % reply.strip())

        # Create motor
        self.motor = {'dummy': Motor('dummy', self)}
        motors['dummy'] = self.motor['dummy']

        self.logger.info("Dummy initialization complete.")
        self.initialized = True

    def do_init(self):
        """
        Call with command "DO_INIT"
        """

        # ---------------------------------------------------------------------------
        # query status
        return self.send_recv('DO_INIT\n')

    @admin_only
    def status(self):
        """
        Dummy driver status.
        """
        return self.send_recv('STATUS\n').strip()

    def abort(self):
        """
        Emergency stop.
        """
        self.logger.info("ABORTING DUMMY!")
        reply = self.send_recv('ABORT\n')
        return

    def get_pos(self, to_stdout=False):
        """
        Dummy position
        """
        pos = self.send_recv('GET_POSITION\n')
        return float(pos.strip())

    @admin_only
    def set_pos(self, value):
        """
        Dummy set position
        """
        self.send_recv('SET_POSITION %f\n' % value)
        self.check_done()
        return self.get_pos()

    def check_done(self):
        """
        Poll until movement is complete.
        """
        with emergency_stop(self.abort):
            while True:
                # query axis status
                status = self.status()
                if status == b'IDLE':
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        self.logger.info("Finished moving dummy stage.")

    def _finish(self):
        """
        Disconnect socket.
        """
        self.logger.info("Exiting.")
        self.sock.close()


class Motor(MotorBase):
    def __init__(self, name, driver):
        super(Motor, self).__init__(name, driver)

    def _get_pos(self):
        """
        Return position in degrees
        """
        return self.driver.get_pos()

    def _set_abs_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.set_pos(x)


def dummy_device(timeout=5., latency=0.):
    """
    Bare-bones fake socket device acceptiing a single connection and processing a few commands.
    """
    client_sock = socket.socket(
        socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
    client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_sock.settimeout(1)
    client_sock.bind((DUMMY_DEVICE_ADDRESS, DUMMY_DEVICE_PORT))
    client_sock.listen(5)
    client = None
    delay = 10.
    print('Accepting connections.')
    while True:
        try:
            client, address = client_sock.accept()
            print('Client connected')
            client.settimeout(timeout)
            t0 = 0
            pos0 = 0.
            dx = 0.
            while True:
                # Read data
                try:
                    data = _recv_all(client).strip().decode('ascii')
                except socket.timeout:
                    continue
                print(f'Received: {data} | ', end=' ')
                dt = time.time() - t0
                if dt < delay:
                    pos = pos0 + dx*dt/10.
                else:
                    pos = pos0 + dx
                    pos0 = pos
                    dx = 0.
                    t0 = 0.
                if data == 'DO_INIT':
                    reply = 'INIT_OK'
                elif data == 'STATUS':
                    if dt < delay:
                        reply = 'MOVING'
                    else:
                        reply = 'IDLE'
                elif data == 'ABORT':
                    if dt < delay:
                        pos0 = pos
                        t0 = 0.
                        dx = 0.
                        reply = 'OK_ABORTED'
                    else:
                        reply = 'NOTHING_TO_ABORT'
                elif data == 'GET_POSITION':
                    reply = '%f' % pos
                elif data.startswith('SET_POSITION'):
                    if dt < delay:
                        reply = 'ERROR_STILL_MOVING'
                    else:
                        dx = float(data.strip('SET_POSITION')) - pos0
                        reply = 'OK'
                        t0 = time.time()
                else:
                    reply = 'UNKNOWN_COMMAND'
                # Return to client
                time.sleep(latency)
                print(f'Sent: {reply}')
                client.sendall((reply+'\n').encode())
        except socket.timeout:
            continue
