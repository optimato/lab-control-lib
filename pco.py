"""
Driver for the PCO edge 4.2 scientific CMOS

Notes Feb 2023: It was difficult to find an acquisition mode that could acquire long
exposures responsively (start acquisition a short time after the software trigger)
AND not take too long after the acquisition to be ready for a new acquisition.
The solution adopted (for now at least) is to start continuous acquisition with a short
exposure time, and change the exposure time when "real images" need to be collected.
The total overhead is about 125 ms (80-100 ms for the initial trigger, 25-50 ms for
the end of acquisition)

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import importlib.util
import logging
import time
import threading

from . import manager, register_proxy_client
from .camera import CameraBase
from .network_conf import PCO as NET_INFO
from .util.proxydevice import proxycall, proxydevice
from .util.future import Future

logger = logging.getLogger(__name__)

BASE_PATH = "D:\\data\\"

# Try to import pco sdk
if importlib.util.find_spec('pco') is not None:
    import pco
else:
    logger.debug("Module pco unavailable on this host")
    class fake_pco:
        def __getattr__(self, item):
            raise RuntimeError('Attempting to access "pco" on a system where it is not present!')
    globals().update({'pco': fake_pco()})

__all__ = ['PCO']

@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class PCO(CameraBase):
    """
    PCO Edge Driver
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 6.5     # Physical pixel pitch in micrometers
    SHAPE = (2048, 2060)   # Native array shape (vertical, horizontal)
    IDLE_EXPOSURE_TIME = .001 # Exposure time while the camera is running "idle"
    EXP_TIME_TOLERANCE = .1
    SHORT_EXPOSURE_TIME = 0.2 # Threshold below which we just "grab frame"
    INTERFACE = 'Camera Link ME4'
    DEFAULT_BROADCAST_PORT = NET_INFO['broadcast_port']
    DEFAULT_LOGGING_ADDRESS = None #NET_INFO['logging']
    LOCAL_DEFAULT_CONFIG = {'number_of_images': 16,            # The size of the ring buffer
                            'record_mode': 'ring buffer',      # Acquisition mode - always ring buffer
                            'binning':(1, 1),                  # binning
                            'roi': None,                       # ROI
                            'pixel_rate': 95333333,           # FIXME: is this the only option?
                            'timestamp': 'off',                # Print timestamp on frames
                            'trigger_mode': 'auto sequence',    # automatic trigger
                            'save_path': 'D:\\snaps\\',
                            }
    # python <3.9
    DEFAULT_CONFIG = CameraBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(LOCAL_DEFAULT_CONFIG)

    def __init__(self, broadcast_port=None):
        """
        Initialization.

        """
        super().__init__(broadcast_port=broadcast_port)

        self.cam = None
        self.info = None
        self.acq_future = None        # Will be replaced with a future when starting to acquire.
        self._pco_is_acquiring = False
        self._stop_pco_acquisition = False
        self._start_grab = False
        self._do_grab = False
        self._new_frame_flag = threading.Event()
        self._new_frame_flag.clear()
        self._acquisition_ready_flag = threading.Event()
        self._acquisition_ready_flag.clear()

        self.init_device()

    def init_device(self):
        """
        Initialize camera
        """
        # Create PCO camera
        self.cam = pco.Camera(interface=self.INTERFACE)

        d = self.cam.description
        self.info = {'serial_number': d['serial'],
                     'interface': d['interface type'],
                     'min_exposure_time': d['min exposure time'],
                     'max_exposure_time': d['max exposure time'],
                     'roi_steps': d['roi steps'],
                     'pixel_rates': d['pixelrates']}

        # Perform some checks:
        # pixel rates
        assert self.config['pixel_rate'] in self.info['pixel_rates'], 'Adjust pixel rate!'

        # roi
        # FIXME: how do ROI work?

        self.logger.info('PCO camera is online')
        self.initialized = True

    def _set_configuration(self):
        """
        Put together all parameters and configure camera

        This also arms the camera, but doesn't start acquisition.
        """
        if self.armed:
            raise RuntimeError('Cannot set configuration while camera is armed')

        opmode = self.operation_mode
        conf = {'exposure time': self.exposure_time,
                'delay time': 0,
                'roi': self.roi,
                'timestamp': opmode['timestamp'],
                'pixel rate': opmode['pixel_rate'],
                'trigger': opmode['trigger_mode'],
                'acquire': 'auto',
                'metadata': 'off',
                'binning': self.binning}
        self.cam.configuration = conf

    def _arm(self):
        """
        Prepare the camera for acquisition
        """
        self.logger.debug('Detector going live.')

        # Apply configuration - this arms the PCO also
        self._set_configuration()

        # Start IDLE acquisition loop
        self.acq_future = Future(self._pco_acquisition_loop)

    def _idle(self):
        """
        Set the camera idle exposure time to a short value to keep it responsive.
        """
        if not self._pco_is_acquiring:
            # This should not happen
            raise RuntimeError('_idle should be called only while acquiring')

        exp_time = self.exposure_time
        idle_exp_time = exp_time if (exp_time < self.SHORT_EXPOSURE_TIME) else self.IDLE_EXPOSURE_TIME
        self.cam.exposure_time = idle_exp_time
        self.logger.debug(f'Idle exposure time: {idle_exp_time:6.3g} s')

    def _pco_acquisition_loop(self):
        """
        Acquisition loop that keeps the camera "ready" for a real acquisition.
        """
        self._pco_is_acquiring = True
        self._idle()

        # start recording
        self.cam.record(number_of_images=self.config['number_of_images'],
                        mode=self.config['record_mode'])

        self._stop_pco_acquisition = False

        # This allows triggering
        self._acquisition_ready_flag.set()

        # Wait for the camera to be ready (needed for cam.wait_for_new_image to work)
        while not self.cam.is_recording:
            time.sleep(.01)
        self.logger.debug('PCO Camera object is now recording')

        t2 = time.perf_counter()
        while not self._stop_pco_acquisition:

            exp_time = self.exposure_time

            # Set camera exposure time if necessary
            if self._start_grab and (exp_time > self.SHORT_EXPOSURE_TIME):
                self.logger.debug('Long exposure grab requested')
                self._start_grab = False
                self.cam.exposure_time = exp_time

            # Wait for new image
            self.cam.wait_for_new_image()
            t2, t1 = time.perf_counter(), t2

            # Measure time since last exposure
            dt = t2 - t1

            if self._do_grab:
                self.logger.debug(f'Grab requested, dt = {dt:6.3g} s')

            skip = (not self._do_grab)
            if not skip and (exp_time > self.SHORT_EXPOSURE_TIME):
                dt_error = abs(dt - exp_time)
                if dt_error > (exp_time * self.EXP_TIME_TOLERANCE):
                    # Skip this frame
                    # Hack to make camera believe that we have read the buffer
                    skip = True
            if skip:
                self.cam._image_number = self.cam.recorded_image_count
                continue

            self.logger.debug('Frame flagged.')

            # We are here because this is a real frame
            self._new_frame_flag.set()
            self._new_frame_flag.clear()
            self._new_frame_flag.wait()
            self._new_frame_flag.clear()

        self._pco_is_acquiring = False
        self.cam.stop()

    def _trigger(self):
        """
        Acquisition.
        """
        # Eventually wait for the camera to be armed.
        self._acquisition_ready_flag.wait()

        if not self._pco_is_acquiring:
            raise RuntimeError('PCO should be acquiring continuously when triggered.')

        self._start_grab = True
        self._do_grab = True

        n_exp = self.exposure_number

        self.logger.debug('Starting acquisition.')
        frame_counter = 0
        while True:
            # Trigger metadata collection
            self.grab_metadata.set()

            time.sleep(min(.1*self.exposure_time, 1.))
            if frame_counter == n_exp-1:
                self._idle()

            # Wait for new frame notification
            self._new_frame_flag.wait()
            self.logger.debug(f'New frame in trigger (frame count = {frame_counter})')

            # Get metadata
            man = manager.getManager()
            if man is None:
                self.logger.error("Not connected to manager! No metadata will available!")
                self.metadata = {}
            else:
                self.metadata = man.return_meta(request_ID=self.name)

            # Read out
            f, m  = self.cam.image(image_index=0xFFFFFFFF)  # This means latest image
            count = m['recorder image number']
            self.logger.debug(f'Acquired frame {count} from buffer...')

            self._new_frame_flag.set()

            # Include frame counter in meta
            m['frame_counter'] = frame_counter + 1

            # Add frame to the queue
            self.enqueue_frame(f, m)

            # increment count
            frame_counter += 1

            if frame_counter == n_exp:
                # Exit if we have reached the requested nuber of exposures
                break

            if self.rolling and self.stop_rolling_flag:
                # Exit if rolling and stop was requested
                break

            if self.abort_flag.is_set():
                break

        # All frames have been collected. Change exposure time back to IDLE
        self._do_grab = False
        self.logger.debug('Grabbing stopped.')
        self._idle()

    def _disarm(self):
        self._acquisition_ready_flag.clear()
        self._stop_pco_acquisition = True
        # Wait until the camera has actually stopped.
        while self.cam.is_recording:
            time.sleep(.05)
        self.logger.debug('PCO Camera object has stopped recording.')

    def _get_exposure_time(self):
        # We need to return the *wanted* exposure time, not the actual one, because
        # of the idle loop.
        return self.config['exposure_time']

    def _set_exposure_time(self, value):
        """
        Set exposure time.

        Parameters:
        value (float): exposure time (seconds)
        """
        if self.cam.is_recording:
            raise RuntimeError('Cannot set exposure time while camera is recording')
        self.config['exposure_time'] = value

    def _get_exposure_number(self):
        return self.config['exposure_number']

    def _set_exposure_number(self, value):
        if self.cam.is_recording:
            raise RuntimeError('Cannot set exposure time while camera is recording')

        self.config['exposure_number'] = value

    def _get_operation_mode(self):
        """
        PCO operation mode.

        This is a mix from the pco configuration entries and other parameters.

        """
        opmode = {'record_mode': self.config['record_mode'],
                  'roi': self.config['roi'],
                  'timestamp': self.config['timestamp'],
                  'pixel_rate': self.config['pixel_rate'],
                  'trigger_mode': self.config['trigger_mode']}
        return opmode

    def _set_operation_mode(self, opmode):
        """
        Set PCO operation mode.
        """
        current_opmode = self._get_operation_mode()
        opmode_keys = list(current_opmode.keys())
        for k in opmode.keys():
            if k not in opmode_keys:
                raise RuntimeError(f'Unknown key for operation mode: {k}')
        self.config.update(opmode)

    def _get_binning(self):
        return self.config['binning']

    def _set_binning(self, new_bin):
        if self.cam.is_recording:
            raise RuntimeError('Cannot change binning while the camera is running.')

        if new_bin[0] != new_bin[1]:
            raise RuntimeError('Different binning in x and y are not yet implemented!')

        # This special case resets everything, no need to go further
        if new_bin == (1, 1) and self.config['roi'] is None:
            self.config['binning'] = new_bin
            self._set_configuration()
            return

        # Get current binning
        old_bin = self.binning

        # Recompute roi if necessary
        roi_steps = self.info['roi_steps']
        old_roi = self.roi
        x0, y0, x1, y1 = old_roi

        # recompute horizontal roi if horizontal binning changed
        if new_bin[0] != old_bin[0]:
            x0 = 1 + ((x0-1)*old_bin[0])//new_bin[0]
            x1 = (x1*old_bin[0])//new_bin[0]
            x0 = 1 + roi_steps[0]*((x0-1)//roi_steps[0])
            x1 = roi_steps[0]*(x1//roi_steps[0])

        # recompute vertical roi if vertical binning changed
        if new_bin[1] != old_bin[1]:
            y0 = 1 + ((y0-1)*old_bin[1])//new_bin[1]
            y1 = (y1*old_bin[1])//new_bin[1]
            y0 = 1 + roi_steps[1]*((y0-1)//roi_steps[1])
            y1 = roi_steps[1]*(y1//roi_steps[1])

        new_roi = (x0, y0, x1, y1)
        self.config['roi'] = new_roi
        self.config['binning'] = new_bin
        self.logger.info(f'Binning: {old_bin} -> {new_bin}')
        self.logger.info(f'ROI: {old_roi} -> {new_roi}')
        self._set_configuration()

    def _get_psize(self):
        # Supporting only square pixels for now
        bx, by = self.binning
        return self.PIXEL_SIZE*bx

    @proxycall(admin=True)
    def set_pco_log_level(self, level):
        """
        Untested - would be better to use our own handlers.
        """
        logger = logging.getLogger("pco")
        logger.setLevel(level)
        logger.addHandler(pco.stream_handler)

    @proxycall()
    @property
    def roi(self):
        """
        Camera ROI
        """
        if self.config['roi'] is None:
            b = self.binning
            roi_steps = self.info['roi_steps']
            return (1,
                    1,
                    roi_steps[0]*(self.SHAPE[1]//(b[0]*roi_steps[0])),
                    roi_steps[1]*(self.SHAPE[0]//(b[1]*roi_steps[1])))
        else:
            return self.config['roi']

    @roi.setter
    def roi(self, value):
        if self.cam.is_recording:
            raise RuntimeError('Cannot set ROI while camera is recording.')

        # Store then retrieve value (this will convert None into a real roi)
        self.config['roi'] = value

        # Apply to camera
        self._set_configuration()

    def _get_shape(self) -> tuple:
        roi = self.roi
        return roi[3]-roi[1]+1, roi[2]-roi[0]+1

    @proxycall()
    @property
    def temperature(self):
        """
        Temperatures of 'sensor', 'camera' and 'power' unit
        """
        return self.cam.sdk.get_temperature()

    @proxycall()
    @property
    def status(self):
        """
        Camera health status
        """
        # FIXME: Add warning in case something is not ok
        return self.cam.sdk.get_camera_health_status()

    def shutdown(self):
        """
        Shut down the camera and driver.
        """
        self.cam.close()
        super().shutdown()
