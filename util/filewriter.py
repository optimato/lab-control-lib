"""
FileWriter worker (and subclasses): Saving files on a separate process using shared memory to transfer
data from the main process.

This implementation uses multiprocessing and the "spawn" start method for Windows compatibility.

Example

h5w = H5FileWriter.start_process()   # This starts the process and returns the class that can be used to interact
h5w.store(filename, data, meta) # This copies the data to shared memory and flags the process to save it.
"""

import multiprocessing
try:
    multiprocessing.set_start_method('spawn')
except RuntimeError:
    pass
from multiprocessing import shared_memory
from queue import SimpleQueue, Empty
from .future import Future
import numpy as np
import time
import json
import traceback

from .logs import logger as rootlogger

# 100 varex full frames
BUFFERSIZE = 100 * 2 * 1536 * 1944


class FileWriter(multiprocessing.Process):
    """
    A "hybrid" class. When executed with "start", spawn a process that captures
    and saves frames dumped in shared memory. The method "store" instead is
    meant to be used by the main process to call the worker process. Frames are
    accumulated in a queue in case store is called at a higher rate than the
    worker can write.
    """

    def __init__(self):
        """
        Prepare a Worker process to save data on disk. Shared memory is
        allocated at construction, see BUFFERSIZE.
        """
        super().__init__()

        self.logger = rootlogger.getChild(self.__class__.__name__)

        # Allocate buffers if needed
        try:
            self.data_buffer = shared_memory.SharedMemory(name='data_buffer',
                                                          create=True,
                                                          size=BUFFERSIZE)
            self.args_buffer = shared_memory.SharedMemory(name='args_buffer',
                                                          create=True,
                                                          size=10000)

            self.logger.debug(f'Created shared memory ({BUFFERSIZE * 1e-6:3.1f} MB)')

        except FileExistsError:
            self.data_buffer = shared_memory.SharedMemory(name='data_buffer')
            self.ares_buffer = shared_memory.SharedMemory(name='args_buffer')

        # Flag the arrival of a new dataset to save
        self.write_flag = multiprocessing.Event()
        self.reply_flag = multiprocessing.Event()

        # Flag the completion of the writing loop, after exhaustion of the queue
        self.stop_flag = multiprocessing.Event()
        self.end_flag = multiprocessing.Event()

        self._array = None

    def process_init(self):
        """
        Possibly additional code to run *only on the separate process*.
        """
        pass

    def run(self):
        """
        This is running on a new process.
        """
        # Create a frame queue
        self.queue = SimpleQueue()

        # Statistics
        self.times = {'received': [],
                      'processed': [],
                      'completed': []}

        # Start the enqueuing loop
        self._enqueue_future = Future(self._enqueue)

        # Additional preparation step if needed
        self.process_init()

        # Start the file saving loop
        self.logger.debug('Entering main loop.')
        while True:
            try:
                item = self.queue.get(timeout=1.)
            except Empty:
                if self.stop_flag.is_set():
                    break
                else:
                    continue

            # Store beginning of processing time
            self.times['processed'].append(time.time())

            filename, data, meta = item
            self.logger.debug(f'Saving data to {filename} ({self.queue.qsize()} remaining in queue)')
            self.write(filename=filename, meta=meta, data=data)

            # Store end of processing time
            n = len(self.times['completed'])
            self.times['completed'].append(time.time())
            wait_time = self.times['processed'][n] - self.times['received'][n]
            save_time = self.times['completed'][n] - self.times['processed'][n]

            self.logger.debug(f'Done. Time in queue: {wait_time:0.3f} s, Saving duration: {save_time:0.3f} s')


        self.logger.debug('Writing loop ended.')
        self.data_buffer.unlink()
        self.args_buffer.unlink()
        self.end_flag.set()

    def write(self, filename, meta, data):
        """
        Actual I/O saving executed by the worker process.
        """
        raise NotImplementedError

    def _enqueue(self):
        """
        A listening thread that queues the frames and metadata to be processed.
        """
        while True:
            if not self.write_flag.wait(1):
                if self.stop_flag.is_set():
                    break
                else:
                    continue
            self.write_flag.clear()

            # Extract arguments from shared buffer
            args = self._buf_to_obj()

            if cmd:=args.get('cmd', None):
                # Execute command!
                try:
                    exec(cmd, {}, {'self': self})
                    reply = {'status': 'ok'}
                except:
                    reply = {'error': traceback.format_exc()}
            else:
                # Store arrival time
                self.times['received'].append(time.time())

                shape = args['shape']
                data = np.ndarray(shape=shape,
                                  dtype=np.dtype(args['dtype']),
                                  buffer=self.data_buffer.buf).copy()

                self.queue.put((args['filename'], data, args['meta']))
                reply = {'in_queue': self.queue.qsize()}

            # Send information back to main process.
            self._obj_to_buf(reply)
            self.reply_flag.set()

    def get_array(self, shape=None, dtype=None):
        """
        Return an array whose underlying buffer is the shared buffer.
        """
        if (shape is not None) and (dtype is not None):
            self._array = np.ndarray(shape=shape, dtype=dtype, buffer=self.data_buffer.buf)
        return self._array

    def store(self, filename, meta, data=None):
        """
        This method is called by the main process to request data to be stored.

        data=None indicates that the data has already been transferred onto the
        buffer. The ndarray parameters are those of self._array
        """
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
        args = {'filename': filename,
                'shape': shape,
                'dtype': dtype,
                'meta': meta}

        # Encode arguments in shared buffer
        self._obj_to_buf(args)
        self.write_flag.set()

        # Get reply through same buffer
        if not self.reply_flag.wait(2):
            raise RuntimeError('Remote process id not responding.')
        reply = self._buf_to_obj()
        self.reply_flag.clear()
        return reply

    def _obj_to_buf(self, obj):
        """
        Utility function to write and send an object through the args_buffer
        """
        # Wipe buffer
        self.args_buffer.buf[:] = self.args_buffer.size * b' '
        s = json.dumps(obj).encode()
        self.args_buffer.buf[:len(s)] = s

    def _buf_to_obj(self):
        """
        Utility function to read args_buffer and unserialize the object.
        """
        # Wipe buffer
        return json.loads(self.args_buffer.buf.tobytes().strip(b'\0 ').decode('utf8').strip())

    def exec(self, cmd):
        """
        A crude way to send commands to the process
        """
        self._obj_to_buf({'cmd': cmd})
        self.write_flag.set()
        # Get reply through same buffer
        if not self.reply_flag.wait(2):
            raise RuntimeError('Remote process id not responding.')
        reply = self._buf_to_obj()
        self.reply_flag.clear()
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


class H5FileWriter(FileWriter):
    """
    A worker class to save HDF5 files.
    """

    def process_init(self):
        """
        import is needed only here.
        """
        from optimatools.io import h5write
        self.h5write = h5write

    def write(self, filename, meta, data):
        """
        For now: use h5write, but could be done with h5py directly e.g. to follow some NEXUS
        standards, or to add more advanced features (e.g. appending to existing files).
        """
        self.h5write(filename=filename, data=data, meta=meta)