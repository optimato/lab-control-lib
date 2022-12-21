"""
Base Camera for all detectors.

Highlights: The CameraBase class wraps detector operations in a uniform API.

** Main methods:
    *  snap(self, exp_time=None, exp_num=None)
    *  roll(self, switch)
    *  live_on(self)
    *  live_off(self)

** Properties:
    *  file_format (g/s)
    *  file_prefix (g/s)
    *  save_path (g/s)
    *  exposure_time (g/s)
    *  operation_mode (g/s)
    *  exposure_number (g/s)
    *  binning (g/s)
    *  psize (g)
    *  shape (g)
    *  magnification (g/s)
    *  epsize (g/s)
    *  live_fps (g/s)
    *  acquiring (g)
    *  storing (g)
    *  is_live (g)
    *  save (g/s)

The following methods have to be implemented

 * grab_frame(self, *args, **kwargs):
  The actual operation of grabbing one or multiple frames with currently stored parameters.

 * roll(self, switch=None):
  If available: start/stop endless continuous acquisition, e.g. for live view.
  ! NOT READY

 * getters and setters
    *  _get_exposure_time(self):
    *  _set_exposure_time(self, value)
    *  _get_exposure_number(self)
    *  _set_exposure_number(self, value)
    *  _get_operation_mode(self)
    *  _set_operation_mode(self, value)
    *  _get_binning(self)
    *  _set_binning(self, value)
    *  _get_psize(self)
    *  _get_shape(self) -> tuple

** File saving

File saving is enabled/disabled with CaneraBase.save = True/False
File naming uses the following recipe:

 filename = CameraBase.BASE_PATH + CameraBase.save_path + file_prefix + [extension]

 where:
  file_prefix is either CameraBase.file_prefix or CameraBase.file_prefix.format(self.counter)
  extension depends on CameraBase.file_format

** Within a SCAN (see experiment.Scan object)



"""
import os
import json

from optimatools.io.h5rw import h5write

from . import workflow, aggregate
from .base import DriverBase
from .util import now, FramePublisher
from .util.proxydevice import proxydevice, proxycall
from .util.future import Future

DEFAULT_FILE_FORMAT = 'hdf5'
DEFAULT_BROADCAST_PORT = 5555


# No @proxydriver because this class is not meant to be instantiated
class CameraBase(DriverBase):
    """
    Base class for camera drivers, giving a uniform interface between detectors.
    """

    DEFAULT_BROADCAST_PORT = DEFAULT_BROADCAST_PORT  # Default port for frame broadcasting
    BASE_PATH = ""
    PIXEL_SIZE = (0, 0)            # Pixel size in um
    SHAPE = (0, 0)            # Native array dimensions (before binning)
    DATATYPE = 'uint16'            # Expected datatype

    def __init__(self, broadcast_port=None):
        super().__init__()
        if broadcast_port is None:
            self.broadcast_port = self.DEFAULT_BROADCAST_PORT
        else:
            self.broadcast_port = broadcast_port

        # Set defaults if they are not set
        if 'do_save' not in self.config:
            self.save = True
        if 'file_format' not in self.config:
            self.file_format = DEFAULT_FILE_FORMAT
        if 'do_broadcast' not in self.config:
            self.config['do_broadcast'] = True
        if 'magnification' not in self.config:
            self.magnification = 1.
        if 'counter' not in self.config:
            self.counter = 0

        self.acq_future = None        # Will be replaced with a future when starting to acquire.
        self.store_future = None      # Will be replaced with a future when starting to store.
        self.roll_future = None       # Will be replaced with a future when starting rolling acquisition
        self._stop_roll = False       # To interrupt rolling

        # Used for file naming when acquiring sequences

        # Prepare metadata collection
        aggregate.connect()

        # Broadcasting
        self.broadcaster = None
        if self.config['do_broadcast']:
            self.live_on()

    #
    # INTERNAL METHODS
    #

    def acquire(self, **kwargs):
        """
        Acquisition wrapper, taking care of metadata collection and
        of frame broadcasting.

        kwargs are most likely to remain empty, but can be used to
        pass additional parameters to self.grab_frame

        NOTE: This is always non-blocking!

        Note: metadata collection is initiated *just before* acquisition.
        """
        if self.acquiring:
            raise RuntimeError('Currently acquiring')
        self.acq_future = Future(self._acquire_task, kwargs=kwargs)
        self.logger.debug('Acquisition started')

    def get_local_meta(self):
        """
        Return camera-specifiv metadata
        """
        meta = {'detector': self.name,
                'scan_name': workflow.getExperiment().scan_name,
                'psize': self.psize,
                'epsize': self.epsize,
                'exposure_time': self.exposure_time,
                'operation_mode': self.operation_mode}
        return meta

    def _acquire_task(self, **kwargs):
        """
        Threaded acquisition task.
        """
        # Start collecting metadata *before* acquisition
        metadata = aggregate.get_all_meta()

        # Extract filename if present
        filename = kwargs.pop('filename', None)

        # Collect local metadata
        localmeta = self.get_local_meta()
        localmeta['acquisition_start'] = now()

        # Grab frame
        frame, meta = self.grab_frame(**kwargs)

        localmeta['acquisition_end'] = now()
        localmeta.update(meta)

        # Update metadata with detector metadata
        metadata[self.name] = localmeta

        # Broadcast and store
        if self.broadcaster:
            self.broadcaster.pub(frame, metadata)

        self._store(frame, metadata, filename=filename)

    def _store(self, frame, metadata, filename=None):
        """
        Store (if requested) frame and metadata
        """
        if not self.config['do_save']:
            # Nothing to do. At this point the data is discarded!
            self.logger.debug('Discarding frame because do_save=False')
            return

        # Build file name and call corresponding saving function
        filename = filename or self._build_filename(prefix=self.file_prefix, path=self.save_path)

        if filename.endswith('h5'):
            self._save_h5(filename, frame, metadata)
        elif filename.endswith('tif'):
            self._save_tif(filename, frame, metadata)
        self.logger.info(f'Saved {filename}')

    def _build_filename(self, prefix, path) -> str:
        """
        Build the full file name to save to.
        """

        # Try to replace counter of prefix is a format string.
        try:
            prefix = prefix.format(self.counter)
        except NameError:
            pass

        full_file_prefix = os.path.join(self.BASE_PATH, path, prefix)

        # Add extension based on file format
        if self.file_format == 'hdf5':
            filename = full_file_prefix + '.h5'
        elif self.file_format == 'tiff':
            filename = full_file_prefix + '.tif'
        else:
            raise RuntimeError(f'Unknown file format: {self.file_format}.')
        return filename

    def _save_h5(self, filename, frame, metadata):
        """
        Save given frame and metadata to filename in h5 format.
        """
        self.store_future = Future(self._save_h5_task, (filename, frame, metadata))

    @staticmethod
    def _save_h5_task(filename, frame, metadata):
        """
        Threaded call
        """
        metadata['save_time'] = now()
        # At this point we store metadata, which might not have been completely populated
        # by the threads running concurrently. This will be visible as empty entries for the
        # corresponding drivers.
        h5write(filename, data=frame, meta=metadata)
        return

    def _save_tif(self, filename, frame, metadata):
        """
        Save given frame and metadata to filename in tiff format.
        """
        raise RuntimeError('Not implemented')

    #
    # ACQUISITION
    #

    @proxycall(admin=True, block=False)
    def snap(self, exp_time=None, exp_num=None):
        """
        Capture one or multiple images

        exp_time and exp_num are optional values
        that change self.exposure_time and self.exposure_number
        before proceeding with the acquisition. NOTE: the previous
        values of these parameters are not reset aftwerwards.
        """
        if exp_time is not None:
            if exp_time != self.exposure_time:
                self.logger.info(f'Exposure time: {self.exposure_time} -> {exp_time}')
                self.exposure_time = exp_time
        if exp_num is not None:
            if exp_num != self.exposure_number:
                self.logger.info(f'Exposure number: {self.exposure_number} -> {exp_num}')
                self.exposure_number = exp_num

        # Check if this is part of a scan
        experiment = workflow.getExperiment()
        scan_path = experiment.scan_path
        if scan_path:
            filename = self._build_filename(prefix=experiment.next_prefix(), path=scan_path)
            self.logger.info(f'Save path: {filename}')
            self.acquire(filename=filename)
        else:
            self.acquire()
            self.counter += 1

    @proxycall(admin=True, block=False)
    def roll(self, switch=None):
        """
        Start endless sequence acquisition for live mode.

        If switch is None: toggle rolling state, otherwise turn on (True) or off (False)
        """
        # If currently rolling
        if self.is_rolling:
            if switch:
                return
            self._stop_roll = True
            self.roll_future.join()
            self.roll_future = None
            return

        if switch == False:
            return

        # Start rolling
        if not self.is_live:
            self.live_on()
        self._stop_roll = False
        self.roll_future = Future(self._roll_task)

    @proxycall()
    @property
    def is_rolling(self):
        """
        Return True if the camera is currently in rolling mode.
        """
        return self.roll_future and not self.roll_future.done()

    def _roll_task(self):
        """
        Running on a thread
        """
        try:
            self.init_rolling(fps=self.config['live_fps'])
            while not self._stop_roll:
                # For now: do not grap all meta at every frame
                # metadata = aggregate.get_all_meta()
                metadata = {}

                # Collect local metadata
                localmeta = self.get_local_meta()
                localmeta['acquisition_start'] = now()

                # Grab frame
                frame, meta = self.grab_rolling_frame()

                localmeta['acquisition_end'] = now()
                localmeta.update(meta)

                # Update metadata with detector metadata
                metadata[self.name] = localmeta

                # Broadcast
                if self.broadcaster:
                    self.broadcaster.pub(frame, metadata)
        finally:
            self.stop_rolling()

    def init_rolling(self, fps):
        """
        Camera-specific preparation for rolling mode.
        """
        raise NotImplementedError

    def stop_rolling(self):
        """
        Camera-specific preparation when exiting rolling mode.
        """
        raise NotImplementedError

    def grab_rolling_frame(self):
        """
        Camera-specific frame grabbing during rolling mode
        """
        raise NotImplementedError

    @proxycall(admin=True)
    def reset_counter(self, value=0):
        """
        Reset internal counter to 0 (or to specified value)
        """
        self.counter = value

    def grab_frame(self, *args, **kwargs):
        """
        The device-specific acquisition procedure.
        """
        raise NotImplementedError

    @proxycall()
    def settings_json(self) -> str:
        """
        Return all current settings jsoned.
        """
        settings = {'exposure_time': self.exposure_time,
                    'exposure_number': self.exposure_number,
                    'operation_mode': self.operation_mode,
                    'file_format': self.file_format,
                    'file_prefix': self.file_prefix,
                    'save_path': self.save_path,
                    'magnification': self.magnification}
        return json.dumps(settings)

    #
    # GETTERS / SETTERS TO IMPLEMENT IN SUBCLASSES
    #

    def _get_exposure_time(self):
        """
        Return exposure time in seconds
        """
        raise NotImplementedError

    def _set_exposure_time(self, value):
        """
        Set exposure time
        """
        raise NotImplementedError

    def _get_exposure_number(self):
        """
        Return exposure number
        """
        raise NotImplementedError

    def _set_exposure_number(self, value):
        """
        Return exposure number
        """
        raise NotImplementedError

    def _get_operation_mode(self):
        """
        Return operation mode
        """
        raise NotImplementedError

    # Operation mode is a special case: 'value' is a dictionary
    # So it's convenient to have a real setter

    def set_operation_mode(self, **kwargs):
        """
        Set operation mode based on key pair arguments.
        """
        raise NotImplementedError

    def _set_operation_mode(self, value):
        """
        Set operation mode
        """
        value = value or {}
        self.set_operation_mode(**value)

    def _get_binning(self):
        """
        Return binning
        """
        raise NotImplementedError

    def _set_binning(self, value):
        """
        Set binning
        """
        raise NotImplementedError

    def _get_psize(self):
        """
        Return pixel size in mm, taking into account binning.
        """
        raise NotImplementedError

    def _get_shape(self) -> tuple:
        """
        Return array shape, taking into account ROI, binning etc.
        """
        raise NotImplementedError

    #
    # PROPERTIES
    #

    @proxycall(admin=True)
    @property
    def file_format(self):
        """
        File format
        """
        return self.config['file_format']

    @file_format.setter
    def file_format(self, value):
        if value.lower() in ['h5', 'hdf', 'hdf5']:
            self.config['file_format'] = 'hdf5'
        elif value.lower() in ['tif', 'tiff']:
            self.config['file_format'] = 'tiff'
        else:
            raise RuntimeError(f'Unknown file format: {value}')

    @proxycall(admin=True)
    @property
    def file_prefix(self):
        """
        File prefix
        """
        return self.config['file_prefix']

    @file_prefix.setter
    def file_prefix(self, value):
        self.config['file_prefix'] = value

    @proxycall(admin=True)
    @property
    def save_path(self):
        """
        Return save path
        """
        return self.config['save_path']

    @save_path.setter
    def save_path(self, value):
        """
        Set save path
        """
        self.config['save_path'] = value

    @proxycall(admin=True)
    @property
    def exposure_time(self):
        """
        Exposure time in seconds.
        """
        return self._get_exposure_time()

    @exposure_time.setter
    def exposure_time(self, value):
        self._set_exposure_time(value)
        self.config['settings']['exposure_time'] = value

    @proxycall(admin=True)
    @property
    def operation_mode(self):
        """
        Set exposure mode.
        """
        return self._get_operation_mode()

    @operation_mode.setter
    def operation_mode(self, value):
        self._set_operation_mode(value)

    @proxycall(admin=True)
    @property
    def exposure_number(self):
        """
        Number of exposures.
        """
        return self._get_exposure_number()

    @exposure_number.setter
    def exposure_number(self, value):
        self._set_exposure_number(value)
        self.config['settings']['exposure_number'] = value

    @proxycall(admin=True)
    @property
    def binning(self):
        """
        Exposure time in seconds.
        """
        return self._get_binning()

    @binning.setter
    def binning(self, value):
        self._set_binning(value)
        self.config['settings']['binning'] = value

    @proxycall()
    @property
    def psize(self):
        """
        Pixel size in um (taking into account binning)
        """
        return self._get_psize()

    @proxycall()
    @property
    def shape(self):
        """
        Array shape (taking into account binning)
        """
        return self._get_shape()

    @proxycall(admin=True)
    @property
    def magnification(self):
        """
        Geometric magnification
        """
        return self.config['magnification']

    @magnification.setter
    def magnification(self, value):
        self.config['magnification'] = float(value)

    @proxycall(admin=True)
    @property
    def epsize(self):
        """
        *Effective* pixel size (taking into account both binning and geometric magnification)
        """
        return self.psize / self.magnification

    @epsize.setter
    def epsize(self, new_eps):
        """
        Set the *effective* pixel size. This effectively changes the magnification
        """
        self.magnification = self.psize / new_eps

    @proxycall(admin=True)
    @property
    def live_fps(self):
        """
        Set FPS for live mode.
        """
        return self.config['live_fps']

    @live_fps.setter
    def live_fps(self, value):
        self.config['live_fps'] = int(value)

    @proxycall()
    @property
    def acquiring(self) -> bool:
        return not (self.acq_future is None or self.acq_future.done())

    @proxycall()
    @property
    def storing(self) -> bool:
        return not (self.store_future is None or self.store_future.done())

    @proxycall(admin=True)
    def live_on(self):
        """
        Start broadcaster.
        """
        if self.broadcaster:
            raise RuntimeError(f'ERROR already broadcasting on port {self.broadcast_port}')
        self.broadcaster = FramePublisher(port=self.broadcast_port)
        self.config['do_broadcast'] = True

    @proxycall(admin=True)
    def live_off(self):
        """
        Start broadcaster.
        """
        if not self.broadcaster:
            raise RuntimeError(f'ERROR: not currently broadcasting.')
        try:
            self.broadcaster.close()
        except BaseException:
            pass
        self.broadcaster = None
        # Remember as default
        self.config['do_broadcast'] = False

    @proxycall()
    @property
    def is_live(self):
        """
        Check if camera is live.
        """
        return self.broadcaster is not None

    @proxycall(admin=True)
    @property
    def save(self):
        """
        If False, frames are not saved on file.
        """
        return self.config['do_save']

    @save.setter
    def save(self, value: bool):
        self.config['do_save'] = bool(value)

    @property
    def counter(self):
        """
        Internal counter for file naming outside of scans
        """
        return self.config['counter']

    @counter.setter
    def counter(self, value: int):
        self.config['counter'] = value
