"""
Dummy controller for testing purposes.

* On one computer run dummy_device (that's the controller)
* On another computer create an instance of DummyDeamon and run with DummyDaemon.listen()
* On a third computer (or the same as Daemon) create an instance of Dummy, which connects upon construction.
"""

import time
import socket

from .base import MotorBase, SocketDriverBase, emergency_stop, _recv_all
from .network_conf import DUMMY as NET_INFO
from .datalogger import DataLogger
from .util.proxydevice import proxydevice, proxycall

__all__ = ['Dummy', 'Motor']


@proxydevice(address=NET_INFO['control'])
class Dummy(SocketDriverBase):
    """
    Dummy Daemon
    """
    DEFAULT_DEVICE_ADDRESS = NET_INFO['device']
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    # temporization for rapid status checks during moves.
    POLL_INTERVAL = 0.01

    data_logger = DataLogger()

    def __init__(self, device_address=None):
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS
        super().__init__(device_address=device_address)
        self.metacalls.update({'position': self.get_pos})
        self.data_logger.start(self)

    def init_device(self):
        """
        Device initialization.
        """
        self.initialized = True
        # try reading something back
        hello = self.device_cmd(b'HELLO\n')
        self.logger.debug('Reply was %s.' % hello.strip())

        reply = self.device_cmd(b'DO_INIT\n')
        self.logger.info('Do init replied %s' % reply.strip())

        """
        # Create motor
        self.motor = {'dum': Motor('dum', self)}
        motors['dum'] = self.motor['dum']
        """
        self.logger.info("Dummy initialization complete.")
        self.initialized = True

    def wait_call(self):
        self.device_cmd(b'STATUS\n')

    @proxycall(admin=True)
    def status(self):
        """
        Dummy driver status.
        """
        return self.device_cmd(b'STATUS\n').strip()

    @proxycall(interrupt=True)
    def abort(self):
        """
        Emergency stop.
        """
        self.logger.info("ABORTING DUMMY!")
        reply = self.device_cmd(b'ABORT\n')
        return

    @proxycall()
    @data_logger.meta(field_name="position", tags={'type': 'fake', 'units': 'meters'}, interval=10)
    def get_pos(self, to_stdout=False):
        """
        Dummy position
        """
        pos = self.device_cmd(b'GET_POSITION\n')
        return float(pos.strip())

    @proxycall(admin=True, block=False)
    def set_pos(self, value):
        """
        Dummy set position
        """
        self.device_cmd('SET_POSITION %f\n' % value)
        self.check_done()
        return self.get_pos()

    @proxycall()
    def check_done(self):
        """
        Poll until movement is complete.
        """
        if self.status() == b'IDLE':
            return
        with emergency_stop(self.abort):
            while True:
                # query axis status
                status = self.status()
                if status == b'IDLE':
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        self.logger.info("Finished moving dummy stage.")

    @proxycall()
    @property
    @data_logger.meta(field_name="position", tags={'type': 'fake', 'units': 'meters'}, interval=10)
    def pos(self):
        """
        Dummy position
        """
        pos = self.device_cmd(b'GET_POSITION\n')
        return float(pos.strip())


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
    client_sock.bind(NET_INFO['device'])
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
