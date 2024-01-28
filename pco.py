"""
Driver for the PCO edge 4.2 scientific CMOS
"""

import importlib.util
import logging

from . import manager, register_proxy_client
from .camera import CameraBase
from .network_conf import XLAM as NET_INFO
from .util.proxydevice import proxycall, proxydevice

logger = logging.getLogger(__name__)

# FIXME: this needs to be the local path on the PCO host
BASE_PATH = "C:\\data\\"

# Try to import pco sdk
if importlib.util.find_spec('pco') is not None:
    import pco
else:
    logger.debug("Module pco unavailable on this host")
    class fake_pco:
        def __getattr__(self, item):
            raise RuntimeError('Attempting to access "pco" on a system where it is not present!')
    globals().update({'pco': fake_pco()})

__all__ = ['Pco']


@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class Pco(CameraBase):
    """
    PCO Edge Driver
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 6.5     # Physical pixel pitch in micrometers
    SHAPE = (2160, 2560)   # Native array shape (vertical, horizontal)
    DEFAULT_BROADCAST_PORT = NET_INFO['broadcast_port']
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    LOCAL_DEFAULT_CONFIG = {'number_of_images': 16,            # The size of the ring buffer
                            'record_mode': 'ring buffer',      # Acquisition mode - always ring buffer
                            'binning':(1, 1),                  # binning
                            'roi': None,                       # ROI
                            'pixel_rate': 286000000,           # FIXME: is this the only option?
                            'timestamp': 'off',                # Print timestamp on frames
                            'trigger mode': 'software trigger' # FIXME: is it what we need?
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

        self.init_device()

    def init_device(self):
        """
        Initialize camera
        """
        # Create PCO camera
        self.cam = pco.Camera()

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
                'noise filter': opmode['noise_filter'],
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

        # Start recording
        self.cam.record(number_of_images=self.config['number_of_images'],
                        mode=self.config['record_mode'])

    def _trigger(self):
        """
        Acquisition.
        """
        cam = self.cam

        n_exp = self.exposure_number

        self.logger.debug('Starting acquisition loop.')
        frame_counter = 0
        while True:
            cam.sdk.force_trigger()
            # Trigger metadata collection
            self.grab_metadata.set()

            # Wait for next image
            cam.wait_for_new_image()

            # Get metadata
            man = manager.getManager()
            if man is None:
                self.logger.error("Not connected to manager! No metadata will available!")
                self.metadata = {}
            else:
                self.metadata = man.return_meta(request_ID=self.name)

            # Read out
            f, m  = cam.image(image_index=0xFFFFFFFF)  # This means latest image
            count = m['recorder image number']
            self.logger.debug(f'Acquired frame {count} from buffer...')

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

    def _disarm(self):
        if self.cam.is_recording:
            self.cam.stop()

    def _get_exposure_time(self):
        # FIXME: is there a scenario for which the config will be out of sync with the camera?
        return self.config['exposure_time']

    def _set_exposure_time(self, value):
        """
        Set exposure time.

        Parameters:
        value (float): exposure time (seconds)
        """
        if self.cam.is_recording:
            raise RuntimeError('Cannot set exposure time while camera is recording')
        self.cam.exposure_time = value
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
        return self.config['binning']  # self.detector.get_binning_mode()

    def _set_binning(self, value):
        if self.cam.is_recording:
            raise RuntimeError('Cannot change binning while the camera is running.')
        self.config['binning'] = value

    def _get_psize(self):
        bx, by = self.binning
        return (self.PIXEL_SIZE*bx, self.PIXEL_SIZE*by)

    @proxycall()
    @property
    def roi(self):
        """
        Camera ROI
        """
        return self.config['roi']

    @roi.setter
    def roi(self, value):

        self.config['roi'] = value

    def _get_shape(self) -> tuple:
        # FIXME: CHECK THIS
        raise RuntimeError("Not yet clear how shape is calculated with roi and binning")

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
