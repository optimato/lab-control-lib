"""
Base behaviour for all detectors.
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

class CameraBase(DriverBase):
    """
    Base class for camera daemons.
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
        if 'do_store' not in self.config:
            self.config['do_store'] = True
        if 'file_format' not in self.config:
            self.config['file_format'] = 'h5'
        if 'do_broadcast' not in self.config:
            self.config['do_broadcast'] = True
        if 'magnification' not in self.config:
            self.config['magnification'] = 1.

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

    def acquire(self, *args):
        """
        Acquisition wrapper, taking care of metadata collection and
        of frame broadcasting.

        NOTE: This is always non-blocking!

        Note: metadata collection is initiated *just before* acquisition.
        """
        if self.acquiring:
            raise RuntimeError('Currently acquiring')
        self.acq_future = Future(self._acquire_task)
        self.logger.debug('Acquisition started')

    def _acquire_task(self):
        """
        Threaded acquisition task.
        """
        # Start collecting metadata *before* acquisition
        metadata = aggregate.get_all_meta()

        localmeta = {'acquisition_start': now(),
                     'psize': self.psize,
                     'epsize': self.epsize}

        frame, meta = self.grab_frame()

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
        if not self.config['do_store']:
            # Nothing to do. At this point the data is discarded!
            self.logger.debug('Discarding frame because do_store=False')
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
        file_prefix = self.config['file_prefix']
        try:
            file_prefix = file_prefix.format(self.counter)
        except NameError:
            pass

        full_file_prefix = os.path.join(self.BASE_PATH, self.config['save_path'], file_prefix)

        # Add extension based on file format
        file_format = self.config['file_format'].lower()
        if file_format in ['hdf', 'hdf5', 'h5']:
            filename = full_file_prefix + '.h5'
        elif file_format in ['tif', 'tiff']:
            filename = full_file_prefix + '.tif'
        else:
            raise RuntimeError(f'Unknown file format: {file_format}.')
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
    def snap(self):
        """
        Capture single frame.
        """
        ...

    @proxycall(admin=True, block=False)
    def capture(self):
        """
        Image capture within a scan. This will take care of file naming and
        metadata collection.
        """
        if experiment.SCAN is None:
            raise RuntimeError('capture is meant to be used only in a scan context.')

    @proxycall(admin=True, block=False)
    def sequence(self):
        """
        Capture a sequence within a scan. This will take care of file naming and
        metadata collection.
        """
        pass  # TODO

    def grab_frame(self):
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

    @proxycall()
    @property
    def is_live(self):
        """
        Check if camera is live.
        """
        return self.broadcaster is not None


class CameraDriverBase(DriverBase):
    """
    Driver Base for all pixel-array detectors.
    """

    def __init__(self, address, admin):
        """

        """
        super().__init__(address=address, admin=admin)

    def fr(self, x) -> bytes:
        """
        Format outgoing string to bytes + EOL
        """
        return str(x).encode() + self.EOL

    def ifr(self, x: bytes) -> str:
        """
        format byte string to str and remove EOL
        """

    def send_cmd(self, cmd) -> str:
        """
        Send text command and return reply
        """
        return self.ifr(self.send_recv(self.fr(cmd)))
    def settings(self):
        """
        Get all relevant settings for acquisition.
        """
        self.send_cmd()

    def snap(self):
        """
        Capture single frame.
        """
        return self.send_recv(b'SNAP' + self.EOL)

    def capture(self):
        """
        Image capture within a scan. This will take care of file naming and
        metadata collection.
        """
        if experiment.SCAN is None:
            raise RuntimeError('capture is meant to be used only in a scan context.')

    def sequence(self):
        """
        Capture a sequence within a scan. This will take care of file naming and
        metadata collection.
        """
        pass  # TODO

    def viewer(self):
        """
        Show interactive viewer
        """
        pass  # TODO

    def settings(self, **kwargs):
        """
        Set camera-specific settings
        """
        raise NotImplementedError

    def set_file_format(self, file_format):
        """
        Set the file format for file saving.
        For now: one of 'hdf' or 'tif'.
        """
        reply = self.send_recv({'cmd': 'set_file_format',
                                'value': file_format})
        pass  # TODO

    def live_on(self):
        """
        Turn on live mode if possible
        """
        reply = self.send_recv(self.ESCAPE_STRING + 'BROADCAST START' + self.EOL)
        return reply

    def live_off(self):
        """
        Turn off live mode
        """
        reply = self.send_recv(self.ESCAPE_STRING + 'BROADCAST STOP' + self.EOL)
        return reply

    def is_live(self):
        """
        Check if camera is live.
        """
        reply = self.send_recv(self.ESCAPE_STRING + 'BROADCAST STATUS' + self.EOL)
        return reply == b'ON'

    def live_options(self, fps, ROI, ):
        """
        Set options for live broa
        """

    # Methods that need to be implemented for the properties to work.
    def _set_exp_time(self, v):
        """
        Set exposure time
        """
        raise NotImplementedError

    def _get_exp_time(self):
        """
        Get exposure time
        """
        raise NotImplementedError

    def _get_shape(self):
        """
        Get current frame shape
        """
        raise NotImplementedError

    def _get_psize(self):
        """
        Get current pixel size (taking into account eventual binning)
        """
        raise NotImplementedError

    def _get_epsize(self):
        """
        Get current *effective* pixel size (taking into account both binning and geometric magnification)
        """
        return self.magnification * self.psize

    def _set_epsize(self, new_eps):
        """
        Set the *effective* pixel size. This effectively changes the magnification
        """
        self.magnification = new_eps / self.psize

    def _get_magnification(self):
        """
        Get user-provided magnification - used for the calculation of the effective pixel size.
        """
        return self._magnification

    def _set_magnification(self, m):
        """
        Set magnification.
        """
        self._magnification = m

    def _get_ROI(self):
        """
        Get current ROI parameters
        """
        raise NotImplementedError

    # Properties that can be set
    @property
    def exp_time(self):
        """
        Exposure time for a single frame.
        """
        return self._get_exp_time()

    @exp_time.setter
    def exp_time(self, v):
        """
        Set exposure time.
        """
        self._set_exp_time(v)

    @property
    def magnification(self):
        """
        Geometric magnification
        """
        return self._get_magnification()

    @magnification.setter
    def magnification(self, m):
        """
        Set exposure time.
        """
        self._set_magnification(m)

    @property
    def epsize(self):
        """
        Effective pixel size (including binning and geometric magnification
        """
        return self._get_epsize()

    @epsize.setter
    def epsize(self, p):
        """
        Set exposure time.
        """
        self._set_epsize(p)

    # Properties that can only be accessed
    @property
    def shape(self):
        """
        [READ ONLY] The dimensions of a frame taken with current parameters.
        (numpy style, so (vertical, horizontal)
        """
        return self._get_shape()

    @property
    def psize(self):
        """
        [READ ONLY] The physical pixel size of a frame taken with current parameters.
        """
        return self._get_psize()

    @property
    def ROI(self):
        """
        The current detector region of interest, returned as two slice objects (vertical, horizontal)
        """
        return self._get_ROI()
