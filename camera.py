"""
Base behaviour for all detectors.
"""
import concurrent.futures
import os
import json

from optimatools.io.h5rw import h5write

from . import experiment, aggregate
from .base import DriverBase, DeviceServerBase
from .util import now, FramePublisher

DEFAULT_FILE_FORMAT = 'hdf5'


class CameraServerBase(DeviceServerBase):
    """
    Base class for camera daemons.
    """

    DEFAULT_BROADCAST_PORT = 5555  # Default port for frame broadcasting
    BASE_PATH = ""
    PIXEL_SIZE = (0, 0)            # Pixel size in mm
    SHAPE = (0, 0)            # Native array dimensions (before binning)
    DATATYPE = 'uint16'            # Expected datatype

    def __init__(self, serving_address, broadcast_port=None):
        super().__init__(serving_addres=serving_address)
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

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        self.acq_future = None        # Will be replaced with a concurrent future when starting to acquire.
        self.store_future = None      # Will be replaced with a conccurent future when starting to store.

        # Used for file naming when acquiring sequences
        self.counter = 0

        # Prepare metadata collection
        aggregate.connect()

        # Broadcasting
        self.broadcaster = None
        if self.config['do_broadcast']:
            self.start_broadcasting()

    def device_cmd(self, cmd) -> bytes:
        """
        Commands common to all detectors
        """
        cmds = cmd.strip(self.EOL).split()
        c = cmds.pop(0)
        if c == b'GET':
            c = cmds.pop(0)
            if c == b'EXPOSURE_TIME':
                return self.fr(self.get_exposure_time())
            elif c == b'EXPOSURE_MODE':
                return self.fr(self.get_exposure_mode())
            elif c == b'EXPOSURE_NUMBER':
                return self.fr(self.get_exposure_number())
            elif c == b'BINNING':
                return self.fr(self.get_binning())
            elif c == b'LIVE_FPS':
                return self.fr(self.get_live_fps())
            elif c == b'FILE_FORMAT':
                return self.fr(self.get_file_format())
            elif c == b'FILE_PREFIX':
                return self.fr(self.get_file_prefix())
            elif c == b'SAVE_PATH':
                return self.fr(self.get_save_path())
            elif c == b'MAGNIFICATION':
                return self.fr(self.get_magnification())
            elif c == b'ACQUIRING':
                return self.fr(self.acquiring)
            elif c == b'SETTINGS':
                return self.fr(self.settings_json())

        elif c == b'SET':
            c = cmds.pop(0)
            if c == b'EXPOSURE_TIME':
                return self.fr(self.set_exposure_time(*cmds))
            elif c == b'EXPOSURE_MODE':
                return self.fr(self.set_exposure_mode(*cmds))
            elif c == b'EXPOSURE_NUMBER':
                return self.fr(self.set_exposure_number(*cmds))
            elif c == b'BINNING':
                return self.fr(self.set_binning(*cmds))
            elif c == b'LIVE_FPS':
                return self.fr(self.set_live_fps(*cmds))
            elif c == b'FILE_FORMAT':
                return self.fr(self.set_file_format(*cmds))
            elif c == b'FILE_PREFIX':
                return self.fr(self.set_file_prefix(*cmds))
            elif c == b'SAVE_PATH':
                return self.fr(self.set_save_path(*cmds))
            elif c == b'MAGNIFICATION':
                return self.fr(self.set_magnification(*cmds))
        elif c == b'ACQUIRE':
            return self.fr(self.acquire(*cmds))
        elif c == b'GOLIVE':
            return self.fr(self.go_live(*cmds))
        elif c == b'STOPLIVE':
            return self.fr(self.stop_live(*cmds))
        elif c == b'ISLIVE':
            return self.fr(self.is_live(*cmds))
        else:
            return self.fr(f'Unknown command "{c}"')

    def acquire(self, *args) -> str:
        """
        Acquisition wrapper, taking care of metadata collection and
        of frame broadcasting.

        NOTE: This is always non-blocking!

        Note: metadata collection is initiated *just before* acquisition.
        """
        if self.acquiring:
            return b'Currently acquiring' + self.EOL
        self.acq_future = self.executor.submit(self._acquire_task)
        return 'Acquisition started'

    def _acquire_task(self) -> str:
        # Start collecting metadata *before* acquisition
        metadata = aggregate.get_all_meta()

        localmeta = {'acquisition_start': now(),
                     'psize': self.PIXEL_SIZE,
                     'epsize': self.PIXEL_SIZE * self.config['magnification']}

        frame, meta = self.grab_frame()

        localmeta['acquisition_end'] = now()
        localmeta.update(meta)

        # Update metadata with detector metadata
        metadata[self.name] = localmeta

        # Broadcast and store
        if self.broadcaster:
            self.broadcaster.pub(frame, metadata)

        return self.store(frame, metadata)

    def store(self, frame, metadata) -> str:
        """
        Store (if requested) frame and metadata
        """
        if not self.config['do_store']:
            # Nothing to do. At this point the data is discarded!
            return 'OK'

        # Build file name and call corresponding saving function
        filename = self.build_filename()

        if filename.endswith('h5'):
            self.save_h5(filename, frame, metadata)
        elif filename.endswith('tif'):
            self.save_tif(filename, frame, metadata)
        return f'Saved {filename}'

    def save_h5(self, filename, frame, metadata):
        """
        Save given frame and metadata to filename in h5 format.
        """
        self.store_future = self.executor.submit(self._save_h5_task, filename, frame, metadata)

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

    def go_live(self, *args) -> str:
        """
        Put camera in "live mode"
        """
        return 'Not implemented'

    def stop_live(self, *args) -> str:
        """
        Stop "live mode"
        """
        return 'Not implemented'

    def is_live(self, *args) -> str:
        """
        Check if in "live mode"
        """
        return 'Not implemented'

    def settings_json(self) -> str:
        """
        Return all current settings jsoned.
        """
        settings = {'exposure_time': self.get_exposure_time(),
                    'exposure_number': self.get_exposure_number(),
                    'exposure_mode': self.get_exposure_mode(),
                    'file_format': self.get_file_format(),
                    'file_prefix': self.get_file_prefix(),
                    'save_path': self.get_save_path(),
                    'magnification': self.get_magnification()}
        return json.dumps(settings)

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

    def get_exposure_time(self) -> str:
        """
        Return exposure time
        """
        return 'Not implemented'

    def get_exposure_number(self) -> str:
        """
        Return exposure number
        """
        return 'Not implemented'

    def get_exposure_mode(self) -> str:
        """
        Return exposure mode
        """
        return 'Not implemented'

    def get_binning(self) -> str:
        """
        Return binning
        """
        return 'Not implemented'

    def get_file_format(self) -> str:
        """
        Return file format
        """
        return self.config['file_format']

    def get_file_prefix(self) -> str:
        """
        Return file_prefix
        """
        return self.config['file_prefix']

    def get_save_path(self) -> str:
        """
        Return save path
        """
        return self.config['save_path']

    def get_magnification(self) -> float:
        """
        Return geometric magnification
        """
        return self.config['magnification']

    def set_exposure_time(self, value: str) -> str:
        """
        Set exposure time
        """
        return 'Not implemented'

    def set_exposure_number(self, value: str) -> str:
        """
        Return exposure number
        """
        return 'Not implemented'

    def set_exposure_mode(self, value: str) -> str:
        """
        Set exposure mode
        """
        return 'Not implemented'

    def set_binning(self, value: str) -> str:
        """
        Set binning
        """
        return 'Not implemented'

    def set_file_format(self, value: str) -> str:
        """
        Set file format
        """
        if value.lower() in ['h5', 'hdf', 'hdf5']:
            self.config['file_format'] = 'hdf5'
            return 'OK'
        elif value.lower() in ['tif', 'tiff']:
            self.config['file_format'] = 'tiff'
            return 'OK'
        else:
            return f'ERROR: unknown file format: {value}'

    def set_file_prefix(self, value: str) -> str:
        """
        Set file_prefix
        """
        self.config['file_prefix'] = value
        return 'OK'

    def set_save_path(self, value: str) -> str:
        """
        Set save path
        """
        self.config['save_path'] = value

    def set_distance_to_source(self, value: str) -> str:
        """
        Set distance_to_source
        """
        try:
            self.config['distance_to_source'] = float(value)
        except:
            return f'Unable to set distance to source with value {value}'
        return 'OK'

    def grab_frame(self):
        """
        The device-specific acquisition procedure.

        """
        raise NotImplementedError

    def parse_escaped(self, cmd) -> bytes:
        """
        Parse camera-specific escaped commands.

        """
        self.escape_help += """
        BROADCAST START start broadcasting
        BROADCAST STOP: stop broadcasting
        BROADCAST STATUS: current broadcasting status
        """
        cmds = cmd.split()
        c = cmds.pop(0)
        if c.startswith(b'BROADCAST'):
            c = cmds.pop(0)
            if c.startswith(b'START'):
                # Start broadcasting frames
                return self.start_broadcasting().encode()
            elif c.startswith(b'STOP'):
                # Stop broadcasting frames
                return self.stop_broadcasting().encode()
            elif c.startssith(b'STATUS'):
                if self.broadcaster:
                    return b'ON'
                else:
                    return b'OFF'

        # Continue parsing
        return super().parse_escaped(cmd)

    def fr(self, x):
        """
        Format response
        """
        if type(x) is bytes:
            if x.endswith(self.EOL):
                return x
            return x + self.EOL
        return str(x).encode() + self.EOL

    @property
    def acquiring(self) -> bool:
        return not (self.acq_future is None or self.acq_future.done())

    @property
    def storing(self) -> bool:
        return not (self.store_future is None or self.store_future.done())

    def start_broadcasting(self) -> str:
        """
        Start broadcaster.
        """
        if self.broadcaster:
            return 'ERROR already broadcasting'
        self.broadcaster = FramePublisher(port=self.broadcast_port)
        return 'OK'

    def stop_broadcasting(self) -> str:
        """
        Start broadcaster.
        """
        if self.broadcaster:
            try:
                self.broadcaster.close()
            except:
                pass
            self.broadcaster = None
            return 'OK'
        else:
            return 'ERROR already not broadcasting'


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
