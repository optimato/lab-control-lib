"""
Dummy motor driver

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import time

from lclib import register_driver, proxycall, proxydevice
from lclib.base import MotorBase, SocketDriverBase, emergency_stop

__all__ = ['Dummymotor', 'Motor', 'DummyControllerInterface']

ADDRESS = ('localhost', 5050)  # Address for the proxy driver
DEVICE_ADDRESS = ('localhost', 10000)  # Address of the (fake) controller. In reality that would be another device on the LAN

@register_driver
@proxydevice(address=ADDRESS)
class Dummymotor(SocketDriverBase):
    """
    Socket driver example for a dummy motor.
    """

    DEFAULT_DEVICE_ADDRESS = DEVICE_ADDRESS
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    EOL = b'\n'

    def __init__(self, device_address=None):
        """
        Initialize socket driver.
        """
        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS

        # Register periodic (heartbeat) calls to avoid disconnect
        self.periodic_calls = {'status': (self.status, 10.)}

        # Initialize driver
        super().__init__(device_address=device_address)

        # Declare the motor value as metadata call.
        self.metacalls.update({'position': self.get_pos})

    def init_device(self):
        """
        Device initialization.
        """
        reply = self.device_cmd(b'DO_INIT\n')
        self.logger.info('Do init replied %s' % reply.strip())

        self.logger.info("Dummy initialization complete.")
        self.initialized = True

    @proxycall()
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
    def get_pos(self):
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
    def pos(self):
        """
        Dummy position
        """
        pos = self.device_cmd(b'GET_POSITION\n')
        return float(pos.strip())


@Dummymotor.register_motor('dummy')
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

import socket
from lclib.base import _recv_all

class DummyControllerInterface:

    def __init__(self, timeout=5., latency=0.):
        """
        Bare-bones fake socket device accepting a single connection and processing a few commands.
        """
        self.timeout = timeout
        self.latency = latency

        self.client_sock = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM)  # TCP socket
        self.client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.client_sock.settimeout(1)
        self.client_sock.bind(DEVICE_ADDRESS)
        self.client_sock.listen(5)
        self.client = None
        print('Accepting connections.')

        # Initial internal state
        self.initialized = False
        self.pos = 0.
        self.in_error = False
        self.in_motion = False
        self.speed =  1.
        self.limits = (-20., 20.)

        self.listen()

    def listen(self):
        """
        Infinite loop waiting for a connection and serving the connected client.
        """
        while True:
            try:
                client, address = self.client_sock.accept()
                print('Client connected')
                client.settimeout(self.timeout)
                self.serve(client)
            except socket.timeout:
                continue

    def serve(self, client):
        """
        Serve the newly connected client
        """
        t_start = 0.
        t_end = 0.
        start_pos = self.pos
        end_pos = self.pos
        direction = 1
        while True:
            # Read data
            try:
                data = _recv_all(client).strip().decode('ascii')
            except socket.timeout:
                continue
            print(f'Received: {data} | ', end=' ')

            t = time.time()
            if self.in_motion:
                # Compute new position if the motor was last set in motion
                if t < t_end:
                    # Motion is not over
                    self.pos = start_pos + direction*self.speed*(t-t_start)
                    self.in_motion = True
                else:
                    # Motion is done
                    self.in_motion = False
                    self.pos = end_pos

            # Manage commands
            if data == 'DO_INIT':
                self.initialized = True
                reply = 'OK: INIT'
            if not self.initialized:
                reply = 'ERROR: NOT INITIALIZED'
            elif data == 'STATUS':
                if self.in_motion:
                    reply = 'MOVING'
                else:
                    reply = 'IDLE'
            elif data == 'ABORT':
                if self.in_motion:
                    self.in_motion = False
                    reply = 'OK: ABORTED'
                else:
                    reply = 'ERROR: NOTHING TO ABORT'
            elif data == 'GET_POSITION':
                reply = '%f' % self.pos
            elif data.startswith('SET_POSITION'):
                if self.in_motion:
                    reply = 'ERROR: STILL MOVING'
                else:
                    try:
                        end_pos = float(data.strip('SET_POSITION'))
                    except:
                        reply = 'ERROR: WRONG SYNTAX'
                    else:
                        if end_pos < self.limits[0]:
                            reply = 'ERROR: LOWER LIMIT'
                        elif end_pos > self.limits[1]:
                            reply = 'ERROR: UPPER LIMIT'
                        else:
                            # Motion is valid
                            start_pos = self.pos
                            t_start = t
                            t_end = t + abs(end_pos - start_pos)/self.speed
                            direction = 1 if end_pos > start_pos else -1
                            self.in_motion = True
                            reply = 'OK'
            else:
                reply = 'ERROR: UNKNOWN COMMAND'

            # Return to client
            time.sleep(self.latency)
            print(f'Sent: {reply}')
            client.sendall((reply+'\n').encode())

