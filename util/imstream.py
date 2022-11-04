"""
Transport numpy arrays or byte buffers via ZMQ for real-time visualization.

Code adapted from https://github.com/jeffbass/imagezmq
"""

import zmq
import numpy as np
import json
import logging
import threading


class FramePublisher:
    """Opens a zmq socket and send data using PUB.

    This object is meant to be short-lived: created when staring to publish, destroyed
    as soon as we're done.

    Argument:
      port: the port number on which to publish (the address will be tcp://*:port)
      frames: if True, send numpy array. If false, raw byte strings.
    """

    def __init__(self, port=5555, frames=True):
        """
        Initializes zmq socket for publishing data.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.port = port
        self.address = f'tcp://*:{port}'
        self.logger.info(f'Publishing on {self.address}')

        socketType = zmq.PUB
        self.zmq_context = SerializingContext()
        self.zmq_socket = self.zmq_context.socket(socketType)
        self.zmq_socket.bind(self.address)

        self.logger.info(f'Broadcasting on {self.address}')

        if frames:
            self.pub = self._pub_array
        else:
            self.pub = self._pub_buffer

    def _pub_array(self, data, metadata=None):
        """Publish numpy array and metadata.

        Arguments:
          data: numpy array
          metadata: any json-serializable object (probably dictionary).
        """
        msg = json.dumps(metadata)

        if not data.flags['C_CONTIGUOUS']:
            data = np.ascontiguousarray(data)
        self.zmq_socket.send_array(data, msg, copy=False)

    def _pub_buffer(self, buffer, metadata):
        """Publish byte string and metadata

        Arguments:
          buffer: byte string
          metadata: any json-serializable object (probably dictionary).
        """
        msg = json.dumps(metadata)
        self.zmq_socket.send_buffer(buffer, msg, copy=False)

    def close(self):
        """Closes the ZMQ socket and the ZMQ context.
        """
        self.logger.info('Shutting down broadcast')
        self.zmq_socket.close()
        self.zmq_context.term()

    def __enter__(self):
        """Enables use of ImageSender in with statement.

        Returns:
          self.
        """

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Enables use of ImageSender in with statement.
        """

        self.close()


class FrameSubscriber:
    """
    Open a subscription zmq socket and receive data.

    Argument:
        address: the address of the publisher, of the form (ip, port)
        frames: if True, receive numpy array. If false receive raw byte strings.
    """

    def __init__(self, address=('localhost', 5555), frames=True):
        """Initializes zmq socket to receive images and text.

        Expects an appropriate ZMQ socket at the senders tcp:port address:
        If REQ_REP is True (the default), then a REP socket is created. It
        must connect to a matching REQ socket on the ImageSender().

        If REQ_REP = False, then a SUB socket is created. It must connect to
        a matching PUB socket on the ImageSender().

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        ip, port = address
        self.address = f'tcp://{ip}:{port}'
        self.logger.info(f'Connecting to {self.address}')

        # Stats to evaluate the rate of dropped frames
        self.num_frames = 0
        self.num_frames_dropped = 0
        self.num_frames_dropped_sequence = 0

        socketType = zmq.SUB
        self.zmq_context = SerializingContext()
        self.zmq_socket = self.zmq_context.socket(socketType)
        self.zmq_socket.setsockopt(zmq.SUBSCRIBE, b'')
        self.zmq_socket.connect(self.address)

        if frames:
            self._recv = self._recv_array
        else:
            self._recv = self._recv_buffer

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
            if (self.zmq_socket.poll(500.) & zmq.POLLIN) == 0:
                continue
            self._data = self._recv()
            self.num_frames += 1
            if self._data_ready.isSet():
                self.num_frames_dropped += 1
                self.num_frames_dropped_sequence += 1
            else:
                if self.num_frames_dropped_sequence > 0:
                    self.logger.debug(f'{self.num_frames_dropped_sequence} frames dropped.')
                self.num_frames_dropped_sequence = 0
            self._data_ready.set()

    def _recv_array(self, copy=False):
        """
        Receive numpy array and metadata.

        Arguments:
          copy: (optional) zmq copy flag.

        Returns:
          frame: the numpy array
          metadata: the metadata
        """

        frame, msg = self.zmq_socket.recv_array(copy=copy)
        metadata = json.loads(msg)
        return frame, metadata

    def _recv_buffer(self, copy=False):
        """
        Receive byte buffer and metadata.

        Arguments:
          copy: (optional) zmq copy flag
        Returns:
          buffer: the byte string
          metadata: the metadata
        """

        buffer, msg = self.zmq_socket.recv_buffer(copy=copy)
        metadata = json.loads(msg)
        return buffer, metadata

    def receive(self, timeout=15.):
        """
        Receive frame
        """
        flag = self._data_ready.wait(timeout=timeout)
        if not flag:
            raise TimeoutError(
                f"Timeout while reading from subscriber {self.address}")
        self._data_ready.clear()
        return self._data

    def close(self):
        """Closes the ZMQ socket and the ZMQ context.
        """
        self.logger.info(f'Shutting down subscriber to {self.address}')
        self._stop = True
        self._thread.join()
        self.zmq_socket.close()
        self.zmq_context.term()

    def __enter__(self):
        """Enables use of ImageHub in with statement.

        Returns:
          self.
        """

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Enables use of ImageHub in with statement.
        """

        self.close()


class SerializingSocket(zmq.Socket):
    """Numpy array serialization methods.

    Modelled on PyZMQ serialization examples.

    Used for sending / receiving OpenCV images, which are Numpy arrays.
    Also used for sending / receiving jpg compressed OpenCV images.
    """

    def send_array(self, A, msg='NoName', flags=0, copy=True, track=False):
        """
        Send a numpy array a text message.

        Arguments:
          A: numpy array
          msg: text message.
          flags: (optional) zmq flags.
          copy: (optional) zmq copy flag.
          track: (optional) zmq track flag.
        """

        md = dict(
            msg=msg,
            dtype=str(A.dtype),
            shape=A.shape,
        )
        self.send_json(md, flags | zmq.SNDMORE)
        return self.send(A, flags, copy=copy, track=track)

    def send_buffer(self,
                 buffer=b'00',
                 msg='NoName',
                 flags=0,
                 copy=True,
                 track=False):
        """Send a buffer with a text message.

        Arguments:
          msg: image name or text message.
          jpg_buffer: jpg buffer of compressed image to be sent.
          flags: (optional) zmq flags.
          copy: (optional) zmq copy flag.
          track: (optional) zmq track flag.
        """

        md = dict(msg=msg, )
        self.send_json(md, flags | zmq.SNDMORE)
        return self.send(buffer, flags, copy=copy, track=track)

    def recv_array(self, flags=0, copy=True, track=False):
        """Receives a numpy array with metadata and text message.

        Receives a numpy array with the metadata necessary
        for reconstructing the array (dtype,shape).
        Returns the array and a text msg, often the array or image name.

        Arguments:
          flags: (optional) zmq flags.
          copy: (optional) zmq copy flag.
          track: (optional) zmq track flag.

        Returns:
          frame: numpy array
          msg: text message
        """

        md = self.recv_json(flags=flags)
        msg = self.recv(flags=flags, copy=copy, track=track)
        A = np.frombuffer(msg, dtype=md['dtype'])
        return A.reshape(md['shape']), md['msg']

    def recv_buffer(self, flags=0, copy=True, track=False):
        """
        Receive buffer and a text msg.

        Arguments:
          flags: (optional) zmq flags.
          copy: (optional) zmq copy flag.
          track: (optional) zmq track flag.

        Returns:
          buffer: bytestring
          msg: text message
        """

        md = self.recv_json(flags=flags)  # metadata text
        buffer = self.recv(flags=flags, copy=copy, track=track)
        return buffer, md['msg']


class SerializingContext(zmq.Context):
    _socket_class = SerializingSocket
