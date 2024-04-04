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
import threading

from .. import FramePublisher
from .. import Future
from . import logger as rootlogger
from .. import h5write

__all__ = ['FrameWriter', 'FrameStreamer']


class FrameWorker:
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
        while True:
            try:
                item = self.queue.get(timeout=.5)
            except Empty:
                if self._terminate:
                    break
                continue
            try:
                self._process_data(item)
            except:
                self.logger.error("Error in worker loop!")
                break
        self.logger.debug("Exited worker loop")
        self._finalize()

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
        self._terminate = True

    def __del__(self):
        self.close()


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
        Prepare queue
        """
        self.logger = rootlogger.getChild(self.__class__.__name__)
        self.workers = []
        self._store_lock = threading.Lock()

    def start_worker(self, *args, **kwargs):
        """
        Initiate a new FrameWorker and add it to the worker list
        """
        self.workers.append(self.WORKER(*args, **kwargs))
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
        with self._store_lock:
            if meta is None:
                meta = {}
            else:
                meta = copy.deepcopy(meta)

            # The active worker is the last one
            self.workers[-1].new_data((data, meta))

    def close_worker(self):
        with self._store_lock:
            if self.workers:
                # FIFO
                self.workers.pop(0).close()

    def stop(self):
        pass

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
        self.start_worker(broadcast_port = self.broadcast_port)

    def off(self):
        self.close_worker()
