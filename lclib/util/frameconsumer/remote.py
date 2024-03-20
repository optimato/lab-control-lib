"""
FrameConsumer worker (and subclasses): Passing frames to a separate process using shared memory
to reduce I/O and processing overheads.

This implementation uses rpyc and shared_memory with the unchecked presumption
that shared_memory is faster than passing the data through a socket.

Example

fw = FrameWriterProcess()   # This starts the process and returns the class that can be used to interact
fw.open(filename)           # Prepare to save a new file
fw.store(data, meta)        # Pass data through shared memory
fw.close()                  # Store data to file.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import rpyc
import numpy as np
import subprocess
import signal
import pickle
import os

from .frameconsumer import FrameWriter, FrameStreamer

# This is a way to make the code compatible with python 3.7 using the backport (pip install shared-memory38)
try:
    from multiprocessing import shared_memory
except ImportError:
    import shared_memory

from . import logger as rootlogger

# 100 varex full frames
BUFFERSIZE = 100 * 2 * 1536 * 1944

shared_buffers = {}

def create_shared_buffer(array_name, buffersize=BUFFERSIZE):
    try:
        data_buffer = shared_memory.SharedMemory(name=array_name,
                                                 create=True,
                                                 size=buffersize)
        #logger.debug(f'Created shared memory ({buffersize * 1e-6:3.1f} MB)')

    except FileExistsError:
        data_buffer = shared_memory.SharedMemory(name=array_name)
    shared_buffers[array_name] = data_buffer
    return data_buffer


def get_array(array_name, shape=None, dtype=None):
    """
    Return an array whose underlying buffer is the shared buffer.
    """
    return np.ndarray(shape=shape, dtype=dtype, buffer=shared_buffers[array_name].buf)


def _m(obj):
    """
    Marshaller to avoid rpyc netrefs.
    """
    return pickle.dumps(obj)


def _um(s):
    """
    Unmarshaller.
    """
    return pickle.loads(s)


class FrameConsumerProcess:
    """
    Connect to remote FrameConsumer service
    """
    PORT = 18459

    def __init__(self):
        self.logger = rootlogger.getChild(self.__class__.__name__)
        self.data_buffer = create_shared_buffer(self.__class__.__name__)
        self.conn = None
        self.proc = None
        self._start_server()

    def store(self, data, meta):
        """
        Send data and metadata
        """
        shape = data.shape
        dtype = str(data.dtype)
        get_array(self.__class__.__name__, shape=shape, dtype=dtype)[:] = data[:]
        self.conn.root.new_data(shape, dtype, _m(meta))

    def _start_server(self):
        """
        Start remote process
        """
        if self.proc is not None:
            if self.proc.poll() is None:
                raise RuntimeError('Process already running')
            else:
                raise RuntimeError('Process exited.')
        self.logger.info(f'Spawning {self.__class__.__name__} server.')
        self.proc = subprocess.Popen(['python', '-m', __name__, self.__class__.__name__])

    def _stop_server(self):
        """
        Stop remote process
        """
        if self.proc is None:
            raise RuntimeError('Server not running')
        if self.proc.poll() is not None:
            raise RuntimeError('Server stopped already')

        # Send an interrupt to let process wrap up and terminate gracefully
        self.proc.send_signal(signal.SIGINT)

    def stop(self):
        try:
            self.data_buffer.unlink()
        except FileNotFoundError:
            pass
        self._stop_server()

    def __del__(self):
        self.stop()


class FrameWriterProcess(FrameConsumerProcess):
    """
    Connect to remote FrameWriter service
    """
    PORT = 18460

    def __init__(self):
        super().__init__()

    def open(self, filename):
        """
        Connect to remote service
        Args:
            filename: where to save data
        """
        self.conn = rpyc.connect(host="localhost", port=self.PORT)

        # Prepare path on the main process to catch errors.
        b, f = os.path.split(filename)
        os.makedirs(b, exist_ok=True)

        self.conn.root.open(filename)

    def close(self):
        """
        Close current request.
        """
        self.conn.root.close()


class FrameStreamerProcess(FrameConsumerProcess):
    """
    Connect to remote FrameStreamer service
    """
    PORT = 18461

    def __init__(self, broadcast_port):
        self.broadcast_port = broadcast_port
        super().__init__()

    def on(self):
        """
        Connect to remote service
        Args:
            broadcast_port: the port for frame publishing
        """
        self.conn = rpyc.connect(host="localhost", port=self.PORT)

        self.conn.root.on(self.broadcast_port)

    def off(self):
        """
        Close current request.
        """
        self.conn.root.off()


class FrameConsumerRemoteService(rpyc.Service):
    cname = None

    def on_connect(self, conn):
        self.conn = conn
        super().on_connect(conn)

    def exposed_new_data(self, shape, dtype, meta):
        """
        Receive metadata and info to retrieve shared memory
        """
        data = get_array(self.cname, shape=shape, dtype=dtype).copy()
        meta = _um(meta)
        self.process_frame(data=data, meta=meta)

    def process_frame(self, data, meta):
        pass

class FrameWriterRemoteService(FrameConsumerRemoteService):
    cname = 'FrameWriterProcess'
    def on_connect(self, conn):
        super().on_connect(conn)
        self.frame_writer = FrameWriter()

    def exposed_open(self, filename):
        """
        Open frame writer
        """
        self.frame_writer.open(filename=filename)

    def process_frame(self, data, meta):
        """
        Do something with data and metadata
        """
        self.frame_writer.store(data=data, meta=meta)

    def exposed_close(self):
        """
        Save data
        """
        self.frame_writer.close()


class FrameStreamerRemoteService(FrameConsumerRemoteService):
    cname = 'FrameStreamerProcess'
    def on_connect(self, conn):
        super().on_connect(conn)

    def exposed_on(self, broadcast_port):
        """
        Open frame writer
        """
        self.frame_streamer = FrameStreamer(broadcast_port=broadcast_port)
        self.frame_streamer.on()

    def process_frame(self, data, meta):
        """
        Broadcast data
        """
        self.frame_streamer.store(data=data, meta=meta)

    def exposed_close(self):
        """
        Save data
        """
        self.frame_streamer.off()


if __name__ == "__main__":
    # Entry point for the process spawned by FrameConsumerProcess._start_server()
    import sys

    cname = sys.argv[1]

    # Serve the service. There might be a more elegant way to treat the different cases...
    if cname == 'FrameWriterProcess':
        t = rpyc.ThreadedServer(
            service=FrameWriterRemoteService,
            port=FrameWriterProcess.PORT,
            protocol_config={
                "allow_all_attrs": True,
                "allow_setattr": True,
                "allow_delattr": True,
            },
        )
    elif cname == 'FrameStreamerProcess':
        t = rpyc.ThreadedServer(
            service=FrameStreamerRemoteService,
            port=FrameStreamerProcess.PORT,
            protocol_config={
                "allow_all_attrs": True,
                "allow_setattr": True,
                "allow_delattr": True,
            },
        )
    else:
        raise(f'Unknown process name "{sys.argv[1]}"')

    # Create of access the shared memory buffer
    data_buffer = create_shared_buffer(cname)

    # Start serving
    try:
        t.start()
    except KeyboardInterrupt:
        # sigint is sent from main process to terminate
        pass

    # Unlink shared memory
    try:
        data_buffer.unlink()
    except FileNotFoundError:
        pass

