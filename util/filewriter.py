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
import h5py

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

    def __init__(self, array_name='data_buffer', args_name='args_buffer'):
        """
        Prepare a Worker process to save data on disk. Shared memory is
        allocated at construction, see BUFFERSIZE.
        """
        super().__init__()

        self.array_name = array_name
        self.args_name = args_name

        self.logger = rootlogger.getChild(self.__class__.__name__)


        # Allocate buffers if needed
        try:
            self.data_buffer = shared_memory.SharedMemory(name=array_name,
                                                          create=True,
                                                          size=BUFFERSIZE)
            self.args_buffer = shared_memory.SharedMemory(name=args_name,
                                                          create=True,
                                                          size=10000)

            self.logger.debug(f'Created shared memory ({BUFFERSIZE * 1e-6:3.1f} MB)')

        except FileExistsError:
            self.data_buffer = shared_memory.SharedMemory(name=array_name)
            self.args_buffer = shared_memory.SharedMemory(name=args_name)

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
            args = self.args
            print(args)
            
            # That's a hack to control the remote process
            if method:=args.get('method', None):
                # Execute command! (the reply format is bogus for now)
                try:
                    method = getattr(self, method)
                    result = method(*args['args'], **args['kwargs'])
                    reply = {'status': 'ok', 'result': result}
                except:
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
            else:
                # Store arrival time
                self.times['received'].append(time.time())

                # Copy data from buffer
                data = self.get_array(shape=args['shape'],
                                  dtype=args['dtype']).copy()

                # Put everything in the queue
                self.queue.put((args['filename'], data, args['meta']))
                reply = {'in_queue': self.queue.qsize()}

            # Send information back to main process.
            self.args = reply
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
        self.args = args
        self.write_flag.set()

        # Get reply through same buffer
        if not self.reply_flag.wait(2):
            raise RuntimeError('Remote process id not responding.')
        reply = self.args
        self.reply_flag.clear()
        return reply

    @property
    def args(self):
        """
        (json-seralizable) object represented by args buffer.
        """
        return json.loads(self.args_buffer.buf.tobytes().strip(b'\0 ').decode('utf8').strip())

    @args.setter
    def args(self, obj):
        # Wipe buffer
        self.args_buffer.buf[:] = self.args_buffer.size * b' '
        s = json.dumps(obj).encode()
        self.args_buffer.buf[:len(s)] = s

    def exec(self, method, args=(), kwargs=None):
        """
        A crude way to send commands to the process
        """
        kwargs = kwargs or {}
        self.args = {'method': method, 'args': args, 'kwargs': kwargs}
        self.write_flag.set()
        # Get reply through same buffer
        if not self.reply_flag.wait(20):
            raise RuntimeError('Remote process id not responding.')
        reply = self.args
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

    def __init__(self, in_ram=True):
        """
        When receiving data (with FileWriter.store method), there
        are two possibilities: 1) frames are accumulated in RAM
        (default) and saved to disc when self.close is called. 2) frames
        are appended to disc as they arrive.
        """
        super().__init__()
        self.ready_to_close = multiprocessing.Event()
        self.in_ram = in_ram
        self._filename = None
        self._meta = []
        self._frames = []

    def _open(self, filename):
        """
        (process side) prepare to store in a new file.
        """
        self.logger.debug(f'Data will be saved in file {filename}')
        self._filename = filename
        if self.in_ram:
            self._frames = []
            self._meta = []
        else:
            # Open new file
            self._fd = h5py.File(filename, 'w')

            # Add these attributes to make the format compatible with h5rw
            self._fd.attrs['h5rw_version'] = '0.1'
            ctime = time.asctime()
            self._fd.attrs['ctime'] = ctime
            self._fd.attrs['mtime'] = ctime

            # Empty dataset
            self._dset = None

    def _close(self):
        """
        (process side) closing of the file saving.
        """
        if self.in_ram:
            self.logger.debug(f'Creating numpy dataset')
            data = np.array(self._frames)
            self.logger.debug(f'Saving with h5write')
            self.h5write(filename=self._filename, meta=self._meta, data=data)
            self.logger.debug(f'Done')
        else:
            # Nothing to do!
            self.logger.debug(f'Closing hdf5 file')
            self.ready_to_close.wait()
            self._fd.close()
            self.logger.debug(f'Done')

        # Reset everything for next time
        self._frames = []
        self._meta = []
        self._fd = None
        self._dset = None

        return

    def open(self, filename):
        """
        Prepare to store in a new file.
        """
        return self.exec('_open', args=(), kwargs={'filename': filename})

    def close(self):
        """
        Close file.
        """
        return self.exec('_close')

    def process_init(self):
        """
        Import is needed only here.
        """
        from optimatools.io import h5write, h5append
        self.h5append = h5append
        self.h5write = h5write

    def write(self, filename, meta, data):
        """
        This is called by store each time a frame arrives.
        For now: use h5write, but could be done with h5py directly e.g. to follow some NEXUS
        standards, or to add more advanced features (e.g. appending to existing files).
        """
        self._meta.append(meta)
        if self.in_ram:
            # Accumulate frame in ram. We'll save everything at the end.
            self.logger.debug(f'Appending frame in RAM')
            self._frames.append(np.squeeze(data))
        else:
            # Add frame to the open hdf5 file.
            self.ready_to_close.clear()

            shape = data.shape
            if len(shape)==2:
                shape = (1,) + shape

            # If dataset has not been created do it now
            if not self._dset:
                self.logger.debug(f'Creating dataset')
                dtype = str(data.dtype)
                self._dset = self._fd.create_dataset(name="data",
                                                     shape=(0,) + shape[-2:],
                                                     maxshape=(None,) + shape[-2:],
                                                     dtype=dtype)
                # Adding this attribute makes the file compatible with h5write
                self._dset.attrs['type'] = 'array'
                self.logger.debug(f'Done creating dataset')

            # Size of the current dataset
            N = self._dset.shape[0]

            # Resize adding the size of the new data
            self.logger.debug(f'Resizing dataset')
            self._dset.resize(size=shape[0] + N, axis=0)

            # Store the data
            self.logger.debug(f'Storing data')
            self._dset[-shape[0]:] = data

            # Store metadata
            self.logger.debug(f'Storing metadata')
            self.h5append(self._fd, meta=self._meta)
            self.logger.debug(f'Done')
            self.ready_to_close.set()
