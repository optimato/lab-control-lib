"""
FrameConsumer worker (and subclasses): Passing frames to a separate process using shared memory
to reduce I/O and processing overheads.

This implementation uses multiprocessing and the "spawn" start method for Windows compatibility.

Example

h5w = H5FileWriter.start_process()   # This starts the process and returns the class that can be used to interact
h5w.store(filename, data, meta) # This copies the data to shared memory and flags the process to save it.
"""

import multiprocessing
import os.path
import threading
try:
    multiprocessing.set_start_method('spawn')
except RuntimeError:
    pass
from multiprocessing import shared_memory
from queue import SimpleQueue, Empty
import numpy as np
import time
import traceback

from .future import Future
from .logs import logger as rootlogger


# 100 varex full frames
BUFFERSIZE = 100 * 2 * 1536 * 1944


class FrameConsumerProcess(multiprocessing.Process):
    """
    A "hybrid" class. When executed with "start", spawn a process that captures
    and saves frames dumped in shared memory. The method "store" instead is
    meant to be used by the main process to call the worker process. Frames are
    accumulated in a queue in case store is called at a higher rate than the
    worker can write.
    """

    def __init__(self, array_name='data_buffer'):
        """
        Prepare a Worker process to save data on disk. Shared memory is
        allocated at construction, see BUFFERSIZE.
        """
        super().__init__()

        self.array_name = array_name

        self.logger = rootlogger.getChild(self.__class__.__name__)

        # Allocate buffer if needed
        try:
            self.data_buffer = shared_memory.SharedMemory(name=array_name,
                                                          create=True,
                                                          size=BUFFERSIZE)
            self.logger.debug(f'Created shared memory ({BUFFERSIZE * 1e-6:3.1f} MB)')

        except FileExistsError:
            self.data_buffer = shared_memory.SharedMemory(name=array_name)

        # Communication pipe
        self.p_main, self.p_sub = multiprocessing.Pipe()

        # Flag the completion of the writing loop, after exhaustion of the queue
        self.stop_flag = multiprocessing.Event()
        self.end_flag = multiprocessing.Event()

        self.comm_lock = multiprocessing.Lock()

        self._array = None

        # Defined in subprocess only:
        self.msg_flag = None

    def _process_init(self):
        """
        Possibly additional code to run *only on the separate process*.
        """
        # Message arrived flag (for other threads)
        self.msg_flag = threading.Event()

        self.process_init()

    def process_init(self):
        """
        Possibly additional code to run *only on the separate process*.
        """
        pass

    def run(self):
        """
        This is running on a new process.
        """
        # Create the frame queue
        self.queue = SimpleQueue()

        # Additional preparation step
        self._process_init()

        # Main loop: wait for data from main process, announced through the p_main/p_sub pipes
        while True:
            if not self.p_sub.poll(timeout=1.):
                if self.stop_flag.is_set():
                    break
                else:
                    continue

            # Message from main process
            msg = self.p_sub.recv()

            # Check if the msg is a method to execute
            if method := msg.get('method', None):
                # Execute command! (the reply format is bogus for now)
                try:
                    method = getattr(self, method)
                    reply = {'status': 'ok'}
                    # Send reply to main process before execution
                    self.p_sub.send(reply)
                    result = method(*msg['args'], **msg['kwargs'])
                except:
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
                    self.p_sub.send(reply)

            else:
                # New data has been pushed.

                # Get arrival time for statistics
                received_time = time.time()

                # Copy data from buffer
                data = self.get_array(shape=msg['shape'],
                                  dtype=msg['dtype']).copy()

                # Put the data and the accompanying metadata in the frame queue
                self.queue.put((data, msg['meta'], received_time))

                # Send information back to main process.
                reply = {'in_queue': self.queue.qsize()}
                self.p_sub.send(reply)

            # Flip the flag saying that a message arrived.
            self.msg_flag.set()

        self.logger.debug('Main loop ended.')
        self.data_buffer.unlink()
        self.end_flag.set()

    def _set_log_level(self, level):
        """
        Set the log level on the sub-process.
        """
        self.logger.setLevel(level)
        return

    def set_log_level(self, level):
        """
        Set the log level on the main and sub-process.
        """
        self.logger.setLevel(level)
        self.exec('_set_log_level', args=(level,))
        return

    def get_array(self, shape=None, dtype=None):
        """
        Return an array whose underlying buffer is the shared buffer.
        """
        if (shape is not None) and (dtype is not None):
            self._array = np.ndarray(shape=shape, dtype=dtype, buffer=self.data_buffer.buf)
        return self._array

    def store(self, data=None, meta=None):
        """
        This method is called by the main process to request data to be stored.

        data=None indicates that the data has already been transferred onto the
        buffer. The ndarray parameters are those of self._array
        """
        meta = meta or {}

        with self.comm_lock:
            if data is None:
                # Data is already in buffer
                shape = self._array.shape
                dtype = str(self._array.dtype)
            else:
                # Copy data onto shared memory
                shape = data.shape
                dtype = str(data.dtype)
                self.get_array(shape=shape, dtype=dtype)[:] = data[:]

            # Preparing arguments.
            args = {'shape': shape,
                    'dtype': dtype,
                    'meta': meta}

            # Encode arguments in shared buffer
            self.p_main.send(args)

        # Get reply through same buffer
        if not self.p_main.poll(20.):
            raise RuntimeError('Remote process is not responding.')
        reply = self.p_main.recv()
        return reply

    def exec(self, method, args=(), kwargs=None):
        """
        A crude way to send commands to the process
        """
        kwargs = kwargs or {}
        with self.comm_lock:
            self.p_main.send({'method': method, 'args': args, 'kwargs': kwargs})

        # Get reply through same buffer
        if not self.p_main.poll(20.):
            raise RuntimeError('Remote process is not responding.')
        reply = self.p_main.recv()
        return reply

    def stop(self):
        self.stop_flag.set()

    def __del__(self):
        self.stop_flag.set()
        self.end_flag.wait()

    @classmethod
    def start_process(cls, *args, **kwargs):
        """
        A factory method to spawn the process and return the class to the main process for interaction.
        """
        file_writer_instance = cls(*args, **kwargs)
        file_writer_instance.start()
        return file_writer_instance


class H5FileWriter(FrameConsumerProcess):
    """
    A worker class to save HDF5 files.
    """

    def __init__(self):
        """
        Start a thread that accumulates frames until notified to write to file and close.
        """
        super().__init__()

    def process_init(self):
        """
        [subprocess]
        A continuation of __init__ but running only on the sub-process.
        """
        from optimatools.io import h5write, h5append
        self.h5append = h5append
        self.h5write = h5write

        # Request to finish accumulating frames and save
        self.close_flag = threading.Event()

        # List of future objects created by self._open()
        self.futures = {}
        self.save_results = {}

    def _open(self, filename):
        """
        [subprocess]
        This command starts the thread that captures the frames.
        """
        # Start new frame accumulation worker, put it in a dictionary with the filename as its key.
        self.futures[filename] = Future(self._worker, kwargs={'filename': filename})

        # If needed do some cleanup of previous completed futures.
        for fname, future in list(self.futures.items()):
            # Do nothing if the future is still running
            if not future.done():
                continue
            # Otherwise get the result and delete the future.
            self.save_results[fname] = future.result()
            del self.futures[fname]

    def _get_save_results(self):
        """
        [subprocess]
        Returns the list of save statuses
        """
        r = self.save_results
        self.save_results = {}
        return r

    def _worker(self, filename):
        """
        [subprocess]
        Worker started by self._open and that accumulates frames until notified to save and closed.
        """
        self.logger.debug(f'Data will be saved in file {filename}')
        print(3)

        frames = []
        metadata = []
        store_times = []

        # self.msg_flag is set but the "_open" call, so we need to ignore this first flip.
        if not self.msg_flag.wait(5):
            print('Something went wrong')
            return {'status': 'error', 'msg': 'Something went wrong when starting _worker'}
        self.msg_flag.clear()

        while True:
            # Wait for commands from main process.
            if not self.msg_flag.wait(.5):
                if self.stop_flag.is_set():
                    # TODO: decide what to do if stop_flag is set while accumulating frames here.
                    break
                continue

            self.msg_flag.clear()

            # Do we need to wrap up?
            if self.close_flag.is_set():
                break

            # If there is no frame in the queue, ignore this flag (can result from a exec call)
            try:
                item = self.queue.get(timeout=.01)
            except Empty:
                continue

            if self.queue.qsize() != 0:
                # This happens if the acquisition is faster than the processing.
                self.logger.error('Queue is not empty - maybe acquisition is faster than storing?')
                return {'status':'error', 'msg': 'more than one item in queue'}

            self.logger.debug('Appending a new frame.')

            data, meta, receive_time = item
            frames.append(data)
            metadata.append(meta)
            store_times.append(receive_time)

        # We broke out of the loop: time to save
        data = np.array(frames)
        self.logger.debug(f'Saving with h5write')
        self.h5write(filename=filename, meta=metadata, data=data)

        return {'status': 'ok', 'store_times': store_times, 'complete_time':time.time()}

    def _close(self):
        """
        [subprocess]
        End frame accumulation and save.
        """
        self.close_flag.set()
        return

    def open(self, filename):
        """
        [main process]
        Prepare to store in a new file.
        """
        # Prepare path on the main process to catch errors.
        b, f = os.path.split(filename)
        os.makedirs(b, exist_ok=True)
        return self.exec('_open', args=(), kwargs={'filename': filename})

    def close(self):
        """
        [main process]
        Close file.
        """
        return self.exec('_close')

    def get_save_results(self):
        """
        [main process]
        Get save results of closed workers
        """
        return self.exec('_get_save_results')