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
    *  exposure_mode (g/s)
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
    *  _get_exposure_mode(self)
    *  _set_exposure_mode(self, value)
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

from . import experiment, aggregate
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
    PIXEL_SIZE = (0, 0)            # Pixel size in mm
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

        self.acq_future = None        # Will be replaced with a future when starting to acquire.
        self.store_future = None      # Will be replaced with a future when starting to store.

        # Used for file naming when acquiring sequences
        self.counter = 0

        # Prepare metadata collection
        aggregate.connect()

        # Broadcasting
        self.broadcaster = None
        if self.config['do_broadcast']:
            self.live_on()

    #
    # INTERNAL METHODS
    #

    def acquire(self, *args, **kwargs):
        """
        Acquisition wrapper, taking care of metadata collection and
        of frame broadcasting.

        args and kwargs are most likely to remain empty, but can be used to
        pass additional parameters to self.grab_frame

        NOTE: This is always non-blocking!

        Note: metadata collection is initiated *just before* acquisition.
        """
        if self.acquiring:
            raise RuntimeError('Currently acquiring')
        self.acq_future = Future(self._acquire_task, args=args, kwargs=kwargs)
        self.logger.debug('Acquisition started')

    def _acquire_task(self, *args, **kwargs):
        """
        Threaded acquisition task.
        """
        # Start collecting metadata *before* acquisition
        metadata = aggregate.get_all_meta()

        localmeta = {'acquisition_start': now(),
                     'psize': self.psize,
                     'epsize': self.epsize}

        frame, meta = self.grab_frame(*args, **kwargs)

        localmeta['acquisition_end'] = now()
        localmeta.update(meta)

        # Update metadata with detector metadata
        metadata[self.name] = localmeta

        # Broadcast and store
        if self.broadcaster:
            self.broadcaster.pub(frame, metadata)

        self.store(frame, metadata)

    def store(self, frame, metadata):
        """
        Store (if requested) frame and metadata
        """
        if not self.config['do_save']:
            # Nothing to do. At this point the data is discarded!
            self.logger.debug('Discarding frame because do_save=False')
            return

        # Build file name and call corresponding saving function
        filename = self.build_filename()

        if filename.endswith('h5'):
            self.save_h5(filename, frame, metadata)
        elif filename.endswith('tif'):
            self.save_tif(filename, frame, metadata)
        self.logger.info(f'Saved {filename}')

    def build_filename(self) -> str:
        """
        Build the full file name to save to.
        """

        # Try to replace counter of prefix is a format string.
        file_prefix = self.file_prefix
        try:
            file_prefix = file_prefix.format(self.counter)
        except NameError:
            pass

        full_file_prefix = os.path.join(self.BASE_PATH, self.save_path, file_prefix)

        # Add extension based on file format
        if self.file_format == 'hdf5':
            filename = full_file_prefix + '.h5'
        elif self.file_format == 'tiff':
            filename = full_file_prefix + '.tif'
        else:
            raise RuntimeError(f'Unknown file format: {self.file_format}.')
        return filename

    def save_h5(self, filename, frame, metadata):
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

    def save_tif(self, filename, frame, metadata):
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
        if experiment.SCAN:
            old_file_prefix = self.file_prefix
            old_save_path = self.save_path
            try:
                self.save_path = experiment.SCAN.path
                self.file_prefix = experiment.SCAN.scan_name
                self.acquire()
                experiment.SCAN.counter += 1
            finally:
                self.file_prefix = old_file_prefix
                self.save_path = old_save_path
        else:
            self.acquire()
            self.counter += 1


    @proxycall(admin=True, block=False)
    def roll(self, switch=None):
        """
        Start endless sequence acquisition for live mode.

        If switch is None: toggle rolling state, otherwise turn on (True) or off (False)
        """
        raise NotImplementedError

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
                    'exposure_mode': self.exposure_mode,
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

    def _get_exposure_mode(self):
        """
        Return exposure mode
        """
        raise NotImplementedError

    def _set_exposure_mode(self, value):
        """
        Set exposure mode
        """
        raise NotImplementedError

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

    @proxycall(admin=True)
    @property
    def exposure_mode(self):
        """
        Set exposure mode.
        """
        return self._get_exposure_mode()

    @exposure_mode.setter
    def exposure_mode(self, value):
        self._set_exposure_mode(value)

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

    @proxycall()
    @property
    def psize(self):
        """
        Pixel size in mm (taking into account binning)
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
        return self.magnification * self.psize

    @epsize.setter
    def epsize(self, new_eps):
        """
        Set the *effective* pixel size. This effectively changes the magnification
        """
        self.magnification = new_eps / self.psize

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
