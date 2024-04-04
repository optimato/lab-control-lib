"""
Base Camera for all detectors.

Highlights: The CameraBase class wraps detector operations in a uniform API.

** Main methods:
    *  snap(self, exp_time=None,
            exp_num=None)        : Acquire frames
    *  roll_on(self, fps=None)   : Start infinite acquisition loop (without saving) for viewer
    *  roll_off(self)            : Stop infinite acquisition loop
    *  live_on(self)             : Turn on broadcasting of images (for external viewer)
    *  live_off(self)            : Turn off broadcasting of images (for external viewer)

** Properties:
    *  file_format (get/set)  : currently only 'hdf5'
    *  file_prefix (get/set)  : prefix used by snap (out of scans)
    *  save_path (g/s)        : out of scans save path
    *  exposure_time (g/s)    : exposure time in seconds
    *  operation_mode (g/s)   : camera-specific operation mode
    *  exposure_number (g/s)  : number of frames to take at each trigger
    *  binning (g/s)          : binning mode if available
    *  psize (g)              : native pixel size in microns
    *  shape (g)              : frame shape (taking count of binning)
    *  magnification (g/s)    : geometric magnification factor
    *  epsize (g/s)           : effective pixel size (if set, changes magnification)
    *  counter (g)            : internal counter for the snap images (out of scan numbering)
    *  roll_fps (g/s)         : fps for rolling mode
    *  live_fps (g/s)         : fps for broadcasting
    *  is_live (g)            : True if currently broadcasting
    *  save (g/s)             : boolean: if False, do not save files

The following methods have to be implemented bu subclasses

 * _arm(self):
  Detector-specific preparation step before acquisition

 * _trigger(self):
  The actual frame acquisition step (see existing examples)

 * _disarm(self):
  Detector-specific shutdown of acquisition mode

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

File naming uses the following recipe:

 filename = CameraBase.BASE_PATH + CameraBase.save_path + file_prefix + [extension]

 where:
  file_prefix is either CameraBase.file_prefix or CameraBase.file_prefix.format(self.counter)
  extension depends on CameraBase.file_format

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os
import json
import threading
from queue import SimpleQueue, Empty
import time

from . import manager, proxycall
from .base import DriverBase
from .util import now, Future, frameconsumer

DEFAULT_FILE_FORMAT = 'hdf5'
DEFAULT_BROADCAST_ADDRESS = ('localhost', 5555)


# No @proxydriver because this class is not meant to be instantiated
class CameraBase(DriverBase):
    """
    Base class for camera drivers, giving a uniform interface between detectors.
    """

    DEFAULT_BROADCAST_ADDRESS = DEFAULT_BROADCAST_ADDRESS  # Default port for frame broadcasting
    BASE_PATH = ""
    PIXEL_SIZE = (0, 0)  # Pixel size in um
    SHAPE = (0, 0)  # Native array dimensions (before binning)
    DATATYPE = 'uint16'  # Expected datatype
    DEFAULT_FPS = 5.
    MAX_FPS = 5.

    LOCAL_DEFAULT_CONFIG = {'do_save': True,
                            'file_format': DEFAULT_FILE_FORMAT,
                            'file_prefix': "snap_{0:04d}",
                            'do_broadcast': True,
                            'magnification': 1.,
                            'counter': 0,
                            'save_mode': 'append',
                            'roll_fps': DEFAULT_FPS,
                            'save_path': None,
                            'operation_mode': None,
                            'exposure_time': 1.,
                            'exposure_number': 1}

    # python >3.9
    # DEFAULT_CONFIG = (DriverBase.DEFAULT_CONFIG | LOCAL_DEFAULT_CONFIG)

    # python <3.9
    DEFAULT_CONFIG = DriverBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(LOCAL_DEFAULT_CONFIG)

    def __init__(self, broadcast_address=None):
        super().__init__()

        # Broadcast from localhost on given port (see util.imstream)
        if broadcast_address is None:
            self.broadcast_address = self.DEFAULT_BROADCAST_ADDRESS
        else:
            self.broadcast_address = broadcast_address

        self.store_future = None      # Will be replaced with a future when starting to store.
        self._stop_roll = False       # To interrupt rolling

        # Other flags
        self.loop_future = None
        self.armed = False
        self.closing = False
        self.rolling = False
        self.auto_armed = False
        self.filename = None
        self.tags = None
        self.end_acquisition = False
        self._scan_path = None
        self.abort_flag = threading.Event()

        self.enqueue_lock = threading.Lock()

        self._exposure_time_before_roll = None
        self._exposure_number_before_roll = None

        # File writing process
        self.frame_writer = frameconsumer.FrameWriter()

        # Prepare metadata collection
        self.metadata = {}
        self.localmeta = {}
        self.grab_metadata = threading.Event()
        self.meta_future = Future(self.metadata_loop)

        self.do_acquire = threading.Event()
        self.acquire_done = threading.Event()
        self.frame_queue_empty_flag = threading.Event()
        self.end_of_exposure_flag = threading.Event()
        self.stop_rolling_flag = False

        self.frame_queue = SimpleQueue()
        self.frame_future = Future(self.frame_management_loop)

        # Broadcasting process
        self.frame_streamer = frameconsumer.FrameStreamer(self.broadcast_address[1])
        if self.config['do_broadcast']:
            self.frame_streamer.on()

    def _trigger(self, *args, **kwargs):
        """
        The device-specific triggering and acquisition procedure.

        * Blocks until acquisition is done.
        * Does not return anything.
        """
        raise NotImplementedError

    def _arm(self):
        """
        The device-specific arming procedure. Sets up everything so that self._trigger()
        starts an acquisition without delay.
        """
        pass

    def _disarm(self):
        """
        The device-specific disarming procedure.
        """
        pass

    def _rearm(self):
        """
        The device-specific rearming procedure (optional)
        """
        pass

    #
    # INTERNAL METHODS
    #

    @proxycall(admin=True, block=False)
    def snap(self, exp_time=None, exp_num=None, tags=None):
        """
        Capture one or multiple images

        Parameters:
        exp_time (float): exposure time
        exp_num (int): number of exposures
        tags (list or str): optional tags to add to the metadata

        If specified, exp_time and exp_num change self.exposure_time and
        self.exposure_number before proceeding with the acquisition.
        NOTE: These parameters are ignored if the camera is already armed.
        Otherwise, the new parameters persist as the end of the acquisition.
        """
        if self.rolling:
            self.logger.warning("Cannot snap while in rolling mode.")
            return

        # If the manager crashes, getManager() will return None and we can't continue
        man = manager.getManager()
        if man is None:
            self.logger.error("Not connected to manager! Can't start acquisition!")
            return

        # If the camera is not armed, we arm it and remember that it was done automatically in snap
        self.auto_armed = False
        if not self.armed:
            self.logger.debug('Camera was not armed when calling snap. Arming first.')
            self.auto_armed = True
            self.arm(exp_time=exp_time, exp_num=exp_num)

        # Set new tags
        self.tags = tags

        # Camera is now armed and acquisition loop is waiting

        # Build filename
        if self.in_scan:
            prefix = man.next_prefix()
            self.filename = self._build_filename(prefix=prefix, path=self._scan_path)
        else:
            self.counter += 1
            self.filename = self._build_filename(prefix=self.file_prefix, path=self.save_path)

        self.logger.info(f'Save path: {self.filename}')

        # Trigger next acquisition now
        self.do_acquire.set()

        # Wait for the end of the acquisition
        self.acquire_done.wait()
        self.logger.debug(f'Acquire done.')
        self.acquire_done.clear()

        if self.auto_armed:
            self.logger.debug('Camera was auto-armed. Disarming')
            self.disarm()

        # Forget tags
        self.tags = None

        return

    @proxycall(interrupt=True)
    def abort(self):
        """
        Abort whatever the camera was doing.
        """
        self.logger.info('Abort requested.')

        # Set abort flag
        self.abort_flag.set()

        # Rolling is managed differently
        if self.rolling:
            self.logger.info('Camera was rolling. Calling roll_off...')
            self.roll_off()
            self.logger.info('Done.')

    def acquisition_loop(self):
        """
        Main acquisition loop.

        NOTE: This it started on a thread every time the camera is armed.
        """
        self.logger.debug('Acquisition loop started')
        self.abort_flag.clear()
        while True:

            # Wait for the next trigger
            if not self.do_acquire.wait(.2):
                if self.end_acquisition:
                    self.logger.debug('end_acquisition is True. Breaking out.')
                    break
                continue
            filename = self.filename
            self.do_acquire.clear()
            self.logger.debug('Received acquisition request (do_acquire flag).')

            # Prepare next acquisition on the file writing process
            if not self.rolling:
                self.logger.debug('Requesting opening to file writer.')
                self.frame_writer.open(filename=filename)

            # trigger acquisition with subclassed method and wait until it is done
            self.logger.debug('Calling the subclass trigger.')
            try:
                # Execute actual exposures
                self._trigger()

                # Enqueue None to signal end-of-exposure
                self.enqueue_frame(None, None)
            except:
                self.logger.exception('Error in _trigger')
                self.acquire_done.set()
                if not self.rolling:
                    self.logger.warning(f'File {filename} likely incomplete or corrupt because of an error in _trigger.')
                    self.frame_writer.close()
                else:
                    self.roll_off()
                break

            #if self.abort_flag.is_set():
            #    self.logger.info('Acquisition aborted.')
            #    self.acquire_done.set()
            #    break

            self.logger.debug('Done calling the subclass trigger.')

            # Flip flag immediately to allow snap to return.
            self.logger.debug('Setting acquire_done flag.')
            self.acquire_done.set()

            if self.rolling:
                if self.stop_rolling_flag:
                    # We are done rolling
                    break
                # We are not done rolling - ask immediately for another frame
                self.do_acquire.set()
                continue
            else:
                # Finalize saving
                self.end_of_exposure_flag.wait()
                self.logger.debug('Calling file_writer.close()')
                self.frame_writer.close()

            # Automatically armed - this is a single shot
            if self.auto_armed:
                break

            # Get ready for next acquisition
            self._rearm()

        # The loop is closed, we are done
        self.logger.debug('Acquisition loop completed')

    def metadata_loop(self):
        """
        Running on a thread. Waiting for the "grab_metadata flag to be flipped, then
        attach most recent metadata to self.metadata
        """
        time.sleep(.5)
        self.logger.debug('Metadata loop started')
        while True:
            if not self.grab_metadata.wait(1):
                if self.closing:
                    return
                continue
            self.grab_metadata.clear()
            self.logger.debug('Metadata collection requested (grab_metadata flag)')

            # Request global metadata (exclude self, we do that locally instead)
            man = manager.getManager()
            if man is None:
                self.logger.error("Not connected to manager! Cannot request metadata!")
            else:
                man.request_meta(request_ID=self.name, exclude_list=[self.name])

            # Local metadata
            self.localmeta = self.get_meta()
            self.localmeta['acquisition_start'] = now()
        self.logger.debug('Metadata loop completed')

    def frame_management_loop(self):
        """
        Running on a thread. Watches self.frame_queue and deals with the data as
        it comes.
        """
        time.sleep(.5)
        while True:
            try:
                item = self.frame_queue.get(timeout=1.)
            except Empty:
                self.frame_queue_empty_flag.set()
                if self.closing:
                    break
                else:
                    continue

            self.logger.debug(f'New frame arrived in queue (remaining: {self.frame_queue.qsize()})')

            # Deal with frame
            data, meta = item

            if data is None:
                self.logger.debug('Setting end-of-exposure flag')
                self.end_of_exposure_flag.set()
                continue

            if not self.rolling:
                self.logger.debug('Calling file_writer.store() with frame')
                try:
                    self.frame_writer.store(meta=meta, data=data)
                except RuntimeError:
                    self.logger.exception("Problem sending data to the file_writer process")
                self.logger.debug('file_writer.store() returned')

            if self.config['do_broadcast']:
                self.logger.debug('Calling file_streamer.store() with frame')
                self.frame_streamer.store(meta=meta, data=data)
                self.logger.debug('file_streamer.store() returned')

            if self.frame_queue.qsize() == 0:
                self.logger.debug('Setting frame queue empty flag.')
                self.frame_queue_empty_flag.set()

    @proxycall()
    def get_meta(self, metakeys=None):
        """
        Return camera-specific metadata
        """
        man = manager.getManager()

        if man is None:
            self.logger.error("Could not connect to manager! metadata will be incomplete.")
            scan_name = "[unknown]"
            scan_counter = None
        else:
            scan_name = man.scan_name
            scan_path = man.scan_path
            scan_counter = man.get_counter() if scan_path else None

        meta = {'detector': self.name,
                'scan_name': scan_name,
                'psize': self.psize,
                'epsize': self.epsize,
                'exposure_time': self.exposure_time,
                'exposure_number': self.exposure_number,
                'operation_mode': self.operation_mode,
                'filename': self.filename,
                'snap_counter': self.counter,
                'scan_counter': scan_counter,
                'tags': self.tags}
        return meta

    def enqueue_frame(self, frame, meta):
        """
        Add frame and meta to the queue. This is meant to be called
        within _trigger at least once.
        """
        with self.enqueue_lock:
            # Manage end-of-exposure differently
            if frame is None:
                self.end_of_exposure_flag.clear()
                self.frame_queue.put((frame, meta))
                return

            self.logger.debug('Frame arrived in enqueue_frame')
            self.frame_queue_empty_flag.clear()

            metadata = self.metadata
            localmeta = self.localmeta

            self.metadata = {}
            self.localmeta = {}

            # Update frame metadata and add to queue
            localmeta.update(meta)
            metadata[self.name.lower()] = localmeta

            self.frame_queue.put((frame, metadata))
            self.logger.debug('Frame added to queue.')

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


    @proxycall(admin=True)
    def arm(self, exp_time=None, exp_num=None):
        """
        Prepare the camera for acquisition.
        """
        if self.rolling:
            raise RuntimeError('Camera is rolling. Call roll_off first.')

        if self.armed:
            self.logger.warning('arm() called but camera already armed.')
            return

        self.logger.debug('Arming detector.')

        if exp_time is not None:
            if exp_time != self.exposure_time:
                self.logger.info(f'Exposure time: {self.exposure_time} -> {exp_time}')
                self.exposure_time = exp_time
        if exp_num is not None:
            if exp_num != self.exposure_number:
                self.logger.info(f'Exposure number: {self.exposure_number} -> {exp_num}')
                self.exposure_number = exp_num

        # Reset stopping flag
        self.end_acquisition = False
        self.acquire_done.clear()
        self.do_acquire.clear()

        # Check if this is part of a scan
        man = manager.getManager()
        if man is None:
            self.logger.error("Not connected to manager! Can't check scan path!")
            self._scan_path = None
        else:
            self._scan_path = man.scan_path

        # Finish arming with subclassed method
        self._arm()

        # Start the main acquisition loop
        self.loop_future = Future(self.acquisition_loop)

        self.armed = True

    @property
    def in_scan(self):
        """
        True if within a scan context.
        """
        man = manager.getManager()
        if man is None:
            self.logger.error("Could not connect to manager!")
            return False
        return man.scan_path is not None

    @proxycall(admin=True)
    def disarm(self):
        """
        Terminate acquisition.
        """
        if self.rolling and not self.stop_rolling_flag:
            self.logger.info('Camera is rolling. Calling roll_off first.')
            self.roll_off()
            # roll_off() calls disarm (after setting self.stop_rolling_flag to true, so no recursion will occur.
            return

        self.logger.debug('Disarm called')

        # Terminate acquisition loop and wait for it to complete
        self.end_acquisition = True

        try:
            self.loop_future.join()
        except AttributeError:
            pass

        # Disarm with subclassed method
        self._disarm()

        # Reset flags
        self.armed = False

    @proxycall(admin=True)
    def roll_on(self, fps=None):
        """
        Start endless sequence acquisition for live mode.
        """
        self.stop_rolling_flag = False
        # If currently rolling check if fps needs updating
        if self.rolling:
            if fps is not None:
                current_fps = self.roll_fps
                if abs(self.exposure_time - 1/fps) < .01:
                    # Close enough - we don't change fps
                    self.logger.info(f"Already rolling with FPS {current_fps:3.1f}.")
                else:
                    # We need to update fps
                    self.logger.info(f"Updating FPS {current_fps:3.1f} -> {fps:3.1f}.")
                    self.roll_off()
                    self.roll_on(fps=fps)
            return

        # Adjust exposure time
        if not fps:
            fps = self.roll_fps
        else:
            self.roll_fps = fps

        # Start rolling
        if not self.is_live:
            self.live_on()

        self.filename = None

        # Save exposure time to restore it when we stop rolling
        self._exposure_time_before_roll = self.exposure_time
        self.exposure_time = 1./fps

        # Set a largish exposure number to avoid retriggering too often
        self._exposure_number_before_roll = self.exposure_number
        self.exposure_number = 100

        # Arm the camera (this starts acquisition loop)
        if not self.armed:
            self.arm()

        self.rolling = True

        # Trigger the first acquisition
        self.do_acquire.set()


    @proxycall(admin=True)
    def roll_off(self):
        """
        Stop rolling acquisition.
        """
        # Nothing to do if not currently rolling
        if not self.rolling:
            return

        # Inform the _trigger loop that it needs to exit now
        self.stop_rolling_flag = True

        # Disarm camera. This waits for the acquisition loop to finish
        self.disarm()

        # Stop rolling
        self.rolling = False

        # Restore previous exposure time and exposure number
        if self._exposure_time_before_roll:
            self.exposure_time = self._exposure_time_before_roll
        if self._exposure_number_before_roll:
            self.exposure_number = self._exposure_number_before_roll

        return

    @proxycall(admin=True)
    def reset_counter(self, value=0):
        """
        Reset internal counter to 0 (or to specified value)
        """
        self.counter = value

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

    @proxycall()
    def set_log_level(self, level):
        """
        Set logging level - also for the filewriter process.
        """
        super().set_log_level(level)
        #self.frame_writer.set_log_level(level)
        #self.frame_streamer.set_log_level(level)

    def shutdown(self):
        # Stop rolling
        self.roll_off()
        # Stop file_writer process
        self.frame_writer.stop()
        # Stop file_streamer process
        self.frame_streamer.stop()
        # Stop metadata loop
        self.closing = True

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

    @proxycall(admin=True)
    @property
    def binning(self):
        """
        Binning type.
        """
        return self._get_binning()

    @binning.setter
    def binning(self, value):
        self._set_binning(value)

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
    def roll_fps(self):
        """
        Set FPS for rolling mode.
        """
        return self.config['roll_fps']

    @roll_fps.setter
    def roll_fps(self, value):
        fps = float(value)
        if fps > self.MAX_FPS:
            self.logger.warning(f'Requested FPS ({fps}) is higher than the maximum allowed value ({self.MAX_FPS}).')
            fps = self.MAX_FPS
        self.config['roll_fps'] = fps
        if self.rolling:
            self.roll_on(fps=fps)

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

    @proxycall(admin=True)
    def live_on(self):
        """
        Start broadcaster.
        """
        self.frame_streamer.on()
        self.config['do_broadcast'] = True

    @proxycall(admin=True)
    def live_off(self):
        """
        Start broadcaster.
        """
        self.frame_streamer.off()
        self.config['do_broadcast'] = False

    @proxycall()
    @property
    def is_live(self):
        """
        Check if camera is live.
        """
        return self.config['do_broadcast']

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
