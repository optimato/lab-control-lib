"""
FrameConsumer worker (and subclasses): Passing frames to a separate process using shared memory
to reduce I/O and processing overheads.

This implementation uses multiprocessing and the "spawn" start method for Windows compatibility.

Example

h5w = H5FileWriter.start_process()   # This starts the process and returns the class that can be used to interact
h5w.store(filename, data, meta) # This copies the data to shared memory and flags the process to save it.

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import multiprocessing
import os.path
import threading
import atexit
try:
    multiprocessing.set_start_method('spawn')
except RuntimeError:
    pass

# This is a way to make the code compatible with python 3.7 using the backport (pip install shared-memory38)
try:
    from multiprocessing import shared_memory
except ImportError:
    import shared_memory

from queue import SimpleQueue, Empty
import numpy as np
import time
import traceback

from .future import Future
from .logs import logger as rootlogger

import os

#from inspect import currentframe, getframeinfo
"""
DUMPFILE = open(f'DUMP_{os.getpid():06d}.txt', 'wt')
ALLSTRINGS = {}
COUNTER = 0
with open(f'KEYS_{os.getpid():06d}.txt', 'wt') as f:
    f.write('keys = {\n')

def _p(s):
    global COUNTER
    cf = currentframe()
    filename = getframeinfo(cf).filename
    full_s = f'[{os.getpid()}] {filename}:{cf.f_back.f_lineno} {s}'
    n = ALLSTRINGS.get(full_s)
    if not n:
        n = COUNTER+0
        ALLSTRINGS[full_s] = n
        with open(f'KEYS_{os.getpid():06d}.txt', 'at') as f:
            f.write(f'{n}: "{full_s}",\n')
        COUNTER += 1
    DUMPFILE.write(f'{time.perf_counter():3.4f}\t{n}\n')
    DUMPFILE.flush()
    #print(f'{time.perf_counter():3.4f}[{os.getpid()}] {filename}:{cf.f_back.f_lineno} {s}', flush=True)
"""

def _p(s):
    pass
#    cf = currentframe()
#    filename = getframeinfo(cf).filename
#    print(f'{time.perf_counter():3.4f}[{os.getpid()}] {filename}:{cf.f_back.f_lineno} {s}', flush=True)


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

        atexit.register(self.stop)

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
        # The items in the queue are tuples (data, meta, time)
        self.queue = SimpleQueue()

        # Additional preparation step
        self._process_init()

        # Main loop: wait for data from main process, announced through the p_main/p_sub pipes
        while True:
            if not self.p_sub.poll(timeout=1.):
                _p('main pipe poll wait')
                if self.stop_flag.is_set():
                    _p('out of main pipe poll wait: stop_flag')
                    break
                else:
                    continue

            # Message from main process
            msg = self.p_sub.recv()

            # Check if the msg is a method to execute
            method_name =  msg.get('method', None)
            if method_name:
                # Execute command! (the reply format is bogus for now)
                _p(f'pipe is method {method_name}')
                try:
                    method = getattr(self, method_name)
                    reply = {'status': 'ok'}
                    # Send reply to main process before execution
                    _p(f'Sending reply')
                    self.p_sub.send(reply)
                    _p(f'Calling method {method_name}')
                    result = method(*msg['args'], **msg['kwargs'])
                    _p(f'Done calling method {method_name}')
                except:
                    _p(f'Error calling method {method_name}')
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
                    self.p_sub.send(reply)

            else:
                # New data has been pushed.
                _p(f'New data in main loop')

                # Get arrival time for statistics
                received_time = time.time()

                # Copy data from buffer
                data = self.get_array(shape=msg['shape'],
                                  dtype=msg['dtype']).copy()

                _p(f'Copied data from shared buffer. Putting in queue')

                # Put the data and the accompanying metadata in the frame queue
                self.queue.put((data, msg['meta'], received_time))

                _p(f'Data now in queue')

                # Send information back to main process.
                reply = {'in_queue': self.queue.qsize()}

                _p(f'Sending reply')
                self.p_sub.send(reply)
                _p(f'Done sending reply')

            # Flip the flag saying that a message arrived.
            _p(f'Setting msg_flag')
            self.msg_flag.set()

        _p(f'Out of main loop. Process will shut down')
        self.logger.debug('Main loop ended.')
        try:
            self.data_buffer.unlink()
        except FileNotFoundError:
            pass
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

        _p(f'Store acquiring comm lock')
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

            _p(f'data is shape={shape}, dtype={dtype}. Sending args through pipe.')

            # Encode arguments in shared buffer
            self.p_main.send(args)
            _p(f'Done sending args through pipe.')

            # Get reply through same buffer
            _p(f'Waiting for reply through pipe')
            if not self.p_main.poll(20.):
                raise RuntimeError('Remote process is not responding.')
            reply = self.p_main.recv()
            _p(f'Reply received')

        _p(f'Store releasing comm lock')
        return reply

    def exec(self, method, args=(), kwargs=None):
        """
        A crude way to send commands to the process
        """
        kwargs = kwargs or {}

        _p(f'Exec acquiring comm lock')
        with self.comm_lock:
            _p(f'Sending method {method} and arguments through pipe.')
            self.p_main.send({'method': method, 'args': args, 'kwargs': kwargs})
            _p(f'Done sending method.')

            # Get reply through same buffer
            _p(f'Waiting for reply')
            if not self.p_main.poll(20.):
                raise RuntimeError('Remote process is not responding.')
            reply = self.p_main.recv()
            _p(f'Reply received.')

        _p(f'Exec releasing comm lock')
        return reply

    def stop(self):
        self.stop_flag.set()

    def __del__(self):
        _p(f'in __del__')
        self.stop_flag.set()
        if self.msg_flag is None:
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
        self.worker_flag = threading.Event()
        self.worker_flag.set()

        # List of future objects created by self._open()
        self.futures = {}
        self.save_results = {}

    def _open(self, filename):
        """
        [subprocess]
        This command starts the thread that captures the frames.
        """
        # Start new frame accumulation worker, put it in a dictionary with the filename as its key.
        _p(f'_open : waiting for worker flag')
        self.worker_flag.wait()
        self.worker_flag.clear()
        _p(f'_open : starting worker thread')
        self.futures[filename] = Future(self._worker, kwargs={'filename': filename})
        _p(f'_open : worker thread started')

        # If needed do some cleanup of previous completed futures.
        for fname, future in list(self.futures.items()):
            # Do nothing if the future is still running
            if not future.done():
                continue
            # Otherwise get the result and delete the future.
            self.save_results[fname] = future.result()
            del self.futures[fname]
        _p(f'_open : exiting')

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
        _p(f'_worker : starting (filename={filename})')
        self.logger.debug(f'Data will be saved in file {filename}')

        frames = []
        metadata = []
        store_times = []

        # self.msg_flag is set but the "_open" call, so we need to ignore this first flip.
        _p(f'_worker: first wait for msg_flag')
        if not self.msg_flag.wait(5):
            print('Something went wrong')
            return {'status': 'error', 'msg': 'Something went wrong when starting _worker'}
        _p(f'_worker: clearing msg_flag')
        self.msg_flag.clear()

        while True:
            # Wait for commands from main process.
            if not self.msg_flag.wait(.5):
                _p(f'_worker: waiting on msg_flag')
                if self.stop_flag.is_set():
                    _p(f'_worker: stop_flag is set.')
                    # TODO: decide what to do if stop_flag is set while accumulating frames here.
                    break
                continue

            _p(f'_worker: clearing msg_flag.')
            self.msg_flag.clear()

            # If there is no frame in the queue, ignore this flag (can result from a exec call)
            try:
                _p(f'_worker: getting item in queue')
                item = self.queue.get(timeout=.01)
            except Empty:
                _p(f'_worker: queue is empty')
                continue

            #if self.queue.qsize() != 0:
            #    # This happens if the acquisition is faster than the processing.
            #    self.logger.error('Queue is not empty - maybe acquisition is faster than storing?')
            #    return {'status': 'error', 'msg': 'more than one item in queue'}

            data, meta, receive_time = item

            if data is None:
                # Sanity check:
                if meta != filename:
                    self.logger.error(f'Was closed called on the wrong file? ({meta} != {filename})')
                _p(f'_worker: data is None -> breaking out of the loop.')
                self.logger.debug('No more frames.')
                break

            self.logger.debug('Appending a new frame.')

            _p(f'_worker: appending new data and metadata')
            frames.append(data)
            metadata.append(meta)
            store_times.append(receive_time)

        # We broke out of the loop: time to save
        _p(f'_worker: out of the loop. Converting data and saving')
        # Allow for another worker to be created
        self.worker_flag.set()
        data = np.array(frames)
        self.logger.debug(f'Saving with h5write')
        self.h5write(filename=filename, meta=metadata, data=data)
        _p(f'_worker: Saved to {filename}.')

        return {'status': 'ok', 'store_times': store_times, 'complete_time':time.time()}

    def _close(self, filename):
        """
        [subprocess]
        End frame accumulation and save.
        """
        _p(f'_close: Enqueuing (None, None, None).')
        self.queue.put((None, filename, None))
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

    def close(self, filename):
        """
        [main process]
        Close file.
        """
        return self.exec('_close', args=(), kwargs={'filename': filename})

    def get_save_results(self):
        """
        [main process]
        Get save results of closed workers
        """
        return self.exec('_get_save_results')

