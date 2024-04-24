"""
FrameConsumer: passing frames to a thread for I/O and other operations.
See remote for a version that runs also on a separate process.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import os
import os.path
import numpy as np
import copy
from queue import SimpleQueue, Empty

from .. import FramePublisher
from .. import Future
from . import logger as rootlogger
from .. import h5write

__all__ = ['FrameWriter', 'FrameStreamer']


class FrameWorker:

    QUEUE_MAX_WAIT = 1.
    logger = rootlogger.getChild('FrameWorker')

    def __init__(self, *args, **kwargs):

        self.queue = SimpleQueue()
        self._terminate = False

        # Start loop
        self.future = Future(self._loop)

    def _loop(self):
        """
        Run on a thread, wait for new frame to process
        """
        self.logger.debug("Entered worker loop")
        stop = False
        while not stop:
            if self._terminate:
                # Termination requested. We look one last time for a new frame and then we shut down.
                self.logger.debug("Termination requested")
                stop = True
            while True:
                try:
                    self.logger.debug("Fetching item in queue")
                    item = self.queue.get(timeout=self.QUEUE_MAX_WAIT)
                except Empty:
                    self.logger.debug("No item in queue")
                    break
                self.logger.debug("Found one item in queue")
                try:
                    self._process_data(item)
                except:
                    self.logger.error("Error in worker loop!")
                    break
        self.logger.debug("Exited worker loop")
        self._finalize()

    def done(self):
        return self.future.done()

    def _process_data(self, item):
        """
        Process newly arrived data.
        Args:
            item: the data
        """
        pass

    def _finalize(self):
        """
        Wrap up.
        """
        pass

    def new_data(self, data):
        """
        Add data to queue.
        Args:
            data: New data to process
        """
        self.queue.put(data)

    def close(self):
        if self.future.done():
            raise RuntimeError('Worker was already closed.')
        self._terminate = True

    def __del__(self):
        try:
            self.close()
        except RuntimeError:
            pass


class HDF5Worker(FrameWorker):
    """
    A worker that accumulates frames and stores to hdf5 file upon completion.
    """
    logger = rootlogger.getChild('HDF5Worker')

    def __init__(self, filename):

        # Prepare path on the main thread to catch errors.
        b, f = os.path.split(filename)
        os.makedirs(b, exist_ok=True)

        self.filename = filename
        self.frames = []
        self.meta = []

        # Start worker
        super().__init__()

    def _process_data(self, item):
        """
        Add frame and metadata to internal list
        Args:
            item: (data, meta)
        """
        data, meta = item
        self.frames.append(data)
        self.meta.append(meta)

    def _finalize(self):
        """
        Store to file
        """
        data = np.array(self.frames)
        h5write(filename=self.filename, meta=self.meta, data=data)
        self.logger.debug(f"{len(self.frames)} frames saved to {self.filename}")


class StreamWorker(FrameWorker):
    """
    A worker that streams frames.
    """
    logger = rootlogger.getChild('StreamWorker')

    def __init__(self, broadcast_port):

        self.broadcast_port = broadcast_port
        self.broadcaster = FramePublisher(port=self.broadcast_port)

        # Start worker
        super().__init__()

    def _process_data(self, item):
        """
        Add frame and metadata to internal list
        Args:
            item: (data, meta)
        """
        data, meta = item
        self.logger.debug('Publishing new frame')
        self.broadcaster.pub(data, meta)
        self.logger.debug('Done publishing new frame')

    def _finalize(self):
        """
        Stop broadcasting
        """
        try:
            self.broadcaster.close()
        except:
            pass


class FrameConsumer:
    """
    Managing file consumption on a separate thread.
    """
    WORKER = FrameWorker

    def __init__(self):
        """
        The point of this FrameConsumer class is to avoid as much as possible the execution lags that can
        be caused by I/O operations. For instance, when a sequence of large files are saved rapidly, it is
        essential to avoid blocking image acquisition because of slow writing on disk. The solution here
        is to have workers working on individual threads. There is ever only one active worker at a time (or none)
        but a worker that takes time closing (i.e. saving files) can do so in the background.

        An earlier version of this FrameConsumer used a frame queue to avoid latency. Using workers is a bit
        cleaner and reduces (eliminates?) the risk of storing a frame in the wrong file.
        """
        self.logger = rootlogger.getChild(self.__class__.__name__)
        self.workers = []
        self.active_worker = None

    def start_worker(self, *args, **kwargs):
        """
        Initiate a new FrameWorker and add it to the worker list
        `args` and `kwargs` are passed directly do the worker.
        """
        self.active_worker = self.WORKER(*args, **kwargs)
        self.workers.append(self.active_worker)

        # Warn if workers are accumulating, so to say
        N = len(self.workers)
        if N > 2:
            self.logger.warning(f'{N} elements in worker list!')

    def store(self, data, meta=None):
        """
        Request data to be stored.

        Args:
            data: a numpy frame
            meta: a dictionary of metadata

        Returns:
            Nothing
        """
        if meta is None:
            meta = {}
        else:
            meta = copy.deepcopy(meta)

        self.logger.debug('Passing data and metadata to active worker')
        self.active_worker.new_data((data, meta))

    def close_worker(self):
        """
        Close first worker in the workers list. Note: the worker to be closed might not be the active worker,
        as a new worker might have been spawned before this call.
        """
        if self.workers:
            # FIFO
            worker_to_close = self.workers.pop(0)
            if worker_to_close.done():
                raise RuntimeError('Attempt to close a worker that has already been closed!')
            worker_to_close.close()
        else:
            raise RuntimeError('Attempting to close a worker when non is present in the list.')

    def set_log_level(self, level):
        """
        Set log level for frame consumer object and all workers.
        """
        self.logger.setLevel(level)
        self.WORKER.logger.setLevel(level)


class FrameWriter(FrameConsumer):
    WORKER = HDF5Worker

    def __init__(self):
        super().__init__()

    def open(self, filename):
        """
        Start new worker
        Args:
            filename: the file to save to
        """
        self.start_worker(filename=filename)

    def close(self):
        """
        Store data on file.
        """
        self.close_worker()


class FrameStreamer(FrameConsumer):
    """
    Frame consumer class to stream frames
    """
    WORKER = StreamWorker

    def __init__(self, broadcast_port):
        """
        Frame publisher.
        """
        super().__init__()
        self.broadcast_port = broadcast_port

    def on(self):
        """
        Start broadcasting.
        """
        try:
            self.close_worker()
        except RuntimeError:
            pass
        self.start_worker(broadcast_port=self.broadcast_port)

    def off(self):
        """
        Stop broadcasting
        """
        self.close_worker()
