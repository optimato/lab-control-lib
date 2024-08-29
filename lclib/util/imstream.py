"""
Transport numpy arrays or byte buffers via ZMQ for real-time visualization.

Code adapted from https://github.com/jeffbass/imagezmq

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import zmq
import numpy as np
import logging
import threading
import time
from . import Future

class FramePublisher:
    """
    Open a zmq socket and send data using PUB.

    This object is meant to be short-lived: created when staring to publish, destroyed
    as soon as we're done.

    Argument:
      port: the port number on which to publish (the address will be tcp://*:port)
      arrays: if True, send numpy array. If false, raw byte strings.
    """

    def __init__(self, port=5555, arrays=True):
        """
        Initializes zmq socket for publishing data.

        The broadcast address is localhost:port

        if arrays is True, publish numpy arrays. If false, publish raw byte buffers.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.port = port
        self.address = f'tcp://*:{port}'
        self.logger.info(f'Publishing on {self.address}')

        # XPUB model allows to receive subscription / unsubscription events
        socketType = zmq.XPUB
        self.zmq_context = SerializingContext()
        self.zmq_socket = self.zmq_context.socket(socketType)
        self.zmq_socket.bind(self.address)
        self.zmq_socket.setsockopt(zmq.XPUB_VERBOSE, True)

        self.logger.info(f'Broadcasting on {self.address}')
        self.arrays = arrays

        # Polling / heartbeat period
        self.poll_period = 3000 # milliseconds

        # Starting polling / heartbeat
        self._stop_poll = False
        self.poll_future = Future(self._poll)

        # This will hold the Future object created by self.pub
        self.pub_future = None

        # Cache of the latest published frame
        self.cache = None

    def pub(self, data, metadata=None):
        """
        Publish frame and metadata.
        Arguments:
          data: numpy array or buffer (or None)
          metadata: any json-serializable object (probably dictionary).
        """
        self.cache = (data, metadata)
        if not self.pub_future or self.pub_future.done():
            self.pub_future = Future(self._pub, args=(data, metadata))
        else:
            self.logger.warning('Previous publish is not complete. Dropping one frame!')
        return
    
    def _pub(self, data, metadata=None):
        """
        Do the actual publishing on a thread.
        """
        if not data.flags['C_CONTIGUOUS']:
            data = np.ascontiguousarray(data)
        self.zmq_socket.send_frame(data, metadata, copy=False)

    def _poll(self):
        """
        Poll for new subscriber. Publish None at a regular interval as a heartbeat.
        """
        while not self._stop_poll:
            # Poll for new subscription - this will almost always time out
            val = self.zmq_socket.poll(self.poll_period)
            if (val & zmq.POLLIN) == 0:
                # Time out. Send a heartbeat
                self.zmq_socket.send_frame(None, None)
                continue

            # Subscription / unsubscription event
            ev = self.zmq_socket.recv()
            if (ev[0] == 1) and (self.cache is not None):
                # New subscription - send cache
                # NOTE: this publishes the cache to all subscribers
                self.pub(*self.cache)

    def close(self):
        """
        Close the ZMQ socket and the ZMQ context.
        """
        self.logger.info('Shutting down broadcast')
        self._stop_poll = True
        self.zmq_socket.close()
        self.zmq_context.term()

    def __enter__(self):
        """
        To use in a with statement.

        Returns:
          self.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        To use in a with statement.
        """
        self.close()


class FrameSubscriber:
    """
    Open a subscription zmq socket and receive data.

    Argument:
        address: the address of the publisher, of the form (ip, port)
        arrays: if True, receive numpy array. If false receive raw byte strings.
    """

    def __init__(self, address=('localhost', 5555), arrays=True):
        """
        Initializes zmq socket to receive frames and metadata.
        """

        self.logger = logging.getLogger(self.__class__.__name__)
        ip, port = address
        self.address = f'tcp://{ip}:{port}'
        self.logger.info(f'Connecting to {self.address}')

        # Stats to evaluate the rate of dropped frames
        self.num_frames = 0
        self.num_frames_dropped = 0
        self.num_frames_dropped_sequence = 0

        # ZMQ Subscriber model
        self.zmq_context = SerializingContext()
        self.zmq_socket = self.zmq_context.socket(zmq.SUB)
        self.zmq_socket.setsockopt(zmq.SUBSCRIBE, b'')
        self.zmq_socket.connect(self.address)

        self.arrays = arrays

        # Threaded receive to drop frames and stay real-time
        self._stop = False
        self._data_ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=())
        self._thread.daemon = True
        self._thread.start()

    def _run(self):
        """
        Start receiving on a separate thread to avoid data backlogs
        """
        while not self._stop:
            # Poll every .5 second
            if (self.zmq_socket.poll(500.) & zmq.POLLIN) == 0:
                continue
            try:
                # New data has arrived
                self._data = self.zmq_socket.recv_frame()
            except ValueError:
                self.logger.warning('Something went wrong receiving frame data. Ignoring.')
                continue
            self.num_frames += 1
            if self._data_ready.is_set():
                # A frame was already cached and not consumed.
                self.num_frames_dropped += 1
                self.num_frames_dropped_sequence += 1
            else:
                if self.num_frames_dropped_sequence > 0:
                    self.logger.info(f'{self.num_frames_dropped_sequence} frames dropped.')
                self.num_frames_dropped_sequence = 0
            self._data_ready.set()

    def receive(self, timeout=15.):
        """
        Receive frame. Raise TimeoutError if no frame has been received after given timeout.
        """
        flag = self._data_ready.wait(timeout=timeout)
        if not flag:
            raise TimeoutError(
                f"Timeout while reading from subscriber {self.address}")

        # Clear the data flag and return the cached frame
        self._data_ready.clear()
        return self._data

    def close(self):
        """
        Close the ZMQ socket and the ZMQ context.
        """
        self.logger.info(f'Shutting down subscriber to {self.address}')
        self._stop = True
        self._thread.join()
        self.zmq_socket.close()
        self.zmq_context.term()

    def __enter__(self):
        """
        To use in a with statement.

        Returns:
          self.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        To use in a with statement.
        """
        self.close()


class SerializingSocket(zmq.Socket):
    """
    Serialization of numpy arrays or raw buffers
    """

    def send_frame(self, A, meta=None, flags=0, copy=True, track=False):
        """
        Send a buffer or numpy array along with metadata.

        Arguments:
          A: numpy array or buffer
          meta: the metadata
          flags: (optional) zmq flags.
          copy: (optional) zmq copy flag.
          track: (optional) zmq track flag.
        """

        md = {'meta': meta}
        if A is None:
            md['type'] = None
        elif type(A) == np.ndarray:
            md['type'] = 'ndarray'
            md['dtype'] = str(A.dtype)
            md['shape'] = A.shape
        else:
            md['type'] = 'bytes'

        if A is not None:
            self.send_json(md, flags | zmq.SNDMORE)
            return self.send(A, flags, copy=copy, track=track)
        else:
            return self.send_json(md, flags)

    def recv_frame(self, flags=0, copy=True, track=False):
        """
        Receive a buffer or numpy array with metadata.

        If the buffer is that of a numpy array, the metadata
        necessary for reconstructing the array is also present.

        Arguments:
          flags: (optional) zmq flags.
          copy: (optional) zmq copy flag.
          track: (optional) zmq track flag.

        Returns:
          frame: numpy array or buffer or None
          msg: metadata
        """

        md = self.recv_json(flags=flags)
        if md['type'] is None:
            return None, md['meta']

        A = self.recv(flags=flags, copy=copy, track=track)
        if md['type'] == 'ndarray':
            A = np.frombuffer(A, dtype=md['dtype']).reshape(md['shape'])
        return A, md['meta']


class SerializingContext(zmq.Context):
    _socket_class = SerializingSocket