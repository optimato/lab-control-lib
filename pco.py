"""
Driver for the PCO edge 4.2 scientific CMOS
"""

import time
import os
import importlib.util
import logging
import numpy as np

from . import manager, register_proxy_client
from .camera import CameraBase
from .network_conf import XLAM as NET_INFO
from .util.proxydevice import proxycall, proxydevice
from .util.future import Future

logger = logging.getLogger(__name__)

# FIXME: this needs to be the local path on the PCO host
BASE_PATH = "C:\\data\\"

# Try to import pco sdk
if importlib.util.find_spec('pco') is not None:
    from pco.sdk import sdk
    from pco.recorder import recorder
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
    LOCAL_DEFAULT_CONFIG = {'binning':(1, 1),
                            'roi': None,
                            'pixel_rate': 'slow',
                            'interface': 'Camera Link Silicon Software',
                            'camera_number': 0,
                            'acquisition_mode': 'ring buffer',
                            'debug_level': 'off',
                            'print_timestamp': 'off'}
    # python <3.9
    DEFAULT_CONFIG = CameraBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(LOCAL_DEFAULT_CONFIG)

    def __init__(self, broadcast_port=None):
        """
        Initialization.

        """
        super().__init__(broadcast_port=broadcast_port)

        self.sdk = None
        self.rec = None

        # FIXME: initialize other attributes here

        self.init_device()

    def init_device(self):
        """
        Initialize camera
        """
        # Create PCO objects
        self.sdk = sdk(debuglevel=self.debug_level, print_timestamp=self.print_timestamp, name=self.name)
        self.rec = recorder(self.sdk, self.sdk.get_camera_handle(), debuglevel=self.debug_level,
                            print_timestamp=self.print_timestamp, name=self.name)

        # Open camera
        interface = self.config['interface']
        camera_number = self.config['camera_number']
        error = self.sdk.open_camera_ex(interface=interface, camera_number=camera_number)

        # FIXME: is the camera number always going to be the same?
        if error:
            self.logger.warning(f'Camera number {camera_number} not found. Looking for others.')
            for number in range(10):
                error = self.sdk.open_camera_ex(interface=interface, camera_number=number)
                if error == 0:
                    self.logger.warning(f'Camera number is {number}.')
                    self.config['camera_number'] = number
                    break
        if error:
            raise RuntimeError('No camera could be found.')

        self.logger.info('Camera is now open')

        # Reset settings
        self.sdk.reset_settings_to_default()

        # Apply configuration


        # FIXME: >>>>>>>>>>>>>>>>> THIS IS OLD VAREX CODE

        self.detector = dexela.DexelaDetector()

        self.logger.info('GigE detector is online')

        # Apply saved configuration
        self.operation_mode = self.operation_mode  # Calls getter/setter
        self.exposure_time = self.config['exposure_time']
        self.binning = self.config['binning']
        self.exposure_number = self.config['exposure_number']

        self.detector.set_gap_time(0)
        self.detector.set_trigger_source('internal_software')
        self.initialized = True

    def _arm(self):
        """
        Prepare the camera for acquisition
        """
        self.logger.debug('Detector going live.')

        # Allocate
        max_num_imgs = self.rec.create('memory')['maximum available images']

        self.rec.init(number_of_images, mode)
        self.rec.set_compression_parameter()
        t = datetime.datetime.now()
        self.rec.start_record()



        self.detector.go_live()
        self.count_start = self.detector.get_field_count()

    def _trigger(self):
        """
        Acquisition.
        NOTE: This implementation reads out the data as it is collected. There doesn't seem to be significant
        overhead with this.
        """
        det = self.detector

        n_exp = self.exposure_number
        exp_time = self.exposure_time

        self.logger.debug('Triggering detector.')
        det.software_trigger()

        self.logger.debug('Starting acquisition loop.')
        frame_counter = 0
        while True:
            # Trigger metadata collection
            self.grab_metadata.set()

            # Wait for end of acquisition
            # det.wait_image is a busy wait! So we sleep for exposure_time - 50 ms, and only then we wait
            time.sleep(max(exp_time - .05, 0))
            while True:
                try:
                    det.wait_image(50.)
                    break
                except TimeoutError:
                    continue

            # Get metadata
            man = manager.getManager()
            if man is None:
                self.logger.error("Not connected to manager! No metadata will available!")
                self.metadata = {}
            else:
                self.metadata = man.return_meta(request_ID=self.name)

            # Find and read out buffer
            count = det.get_field_count()
            i = det.get_captured_buffer()
            self.logger.debug(f'Acquired frame {count} from buffer {i}...')
            f, m = det.read_buffer(i)

            # Rotate frame
            f = np.rot90(f)

            # Include frame counter in meta
            m['frame_counter'] = frame_counter + 1

            # Add frame to the queue
            self.enqueue_frame(f, m)

            # increment count
            frame_counter += 1

            det.check_for_live_error()

            if frame_counter == n_exp:
                # Exit if we have reached the requested nuber of exposures
                break

            if self.rolling and self.stop_rolling_flag:
                # Exit if rolling and stop was requested
                break

            if self.abort_flag.is_set():
                break

            # For very high number of exposures, we need to reset the loop
            if (count - self.count_start - 1) % n_exp == 0:
                if det.is_live():
                    det.go_unlive()
                det.go_live()
                det.software_trigger()
                self.count_start = count

    def _disarm(self):
        if self.detector.is_live():
            self.detector.go_unlive()

    def _rearm(self):
        if self.detector.is_live():
            self.detector.go_unlive()
        self.detector.go_live()

    def _get_exposure_time(self):
        # FIXME: is there a scenario for which the config will be out of sync with the camera?
        return self.config['exposure_time']

    def _set_exposure_time(self, value):
        """
        Set exposure time.

        Parameters:
        value (float): exposure time (seconds)
        """
        if self.is_recording:
            raise RuntimeError('Cannot set exposure time while camera is recording')

        if value > 1e-1:
            # millisecond precision is good enough
            self.sdk.set_delay_exposure_time(0, 'ms', int(1000*value), 'ms')
        else:
            # Use microseconds
            self.sdk.set_delay_exposure_time(0, 'ms', int(1000000*value), 'us')

        self.config['exposure_time'] = value

    def _get_exposure_number(self):
        return self.config['exposure_number']

    def _set_exposure_number(self, value):
        if self.is_recording:
            raise RuntimeError('Cannot set exposure time while camera is recording')

        self.config['exposure_number'] = value

    def _get_operation_mode(self):
        opmode = {'full_well_mode': self.config['full_well_mode'],
                  'exposure_mode': self.config['exposure_mode'],
                  'readout_mode': self.config['readout_mode']}
        return opmode

    def _set_operation_mode(self, opmode):
        """
        Set operation mode.
        """
        self.set_operation_mode(**opmode)

    def set_operation_mode(self, full_well_mode=None, exposure_mode=None, readout_mode=None):
        """
        Set varex operation mode:

        * full_well_mode: ('high' or 'low')
        * exposure_mode: 'Expose_and_read', 'Sequence_Exposure', 'Frame_Rate_exposure', 'Preprogrammed_exposure'
            NOTE: only 'Sequence_Exposure' is supported for now
        * readout_mode: 'ContinuousReadout', 'IdleMode'
            NOTE: only 'ContinuousReadout is supported
        """
        if self.detector.is_live():
            raise RuntimeError('Cannot set operation mode while the detector is armed.')

        if (exposure_mode is not None) and exposure_mode.lower() != 'sequence_exposure':
            raise RuntimeError('exposure_mode cannot be changed in the current implementation.')
        if (readout_mode is not None) and readout_mode.lower() != 'continuousreadout':
            raise RuntimeError('readout_mode cannot be changed in the current implementation.')

        full_well_mode = full_well_mode or 'high'
        readout_mode = 'continuousreadout'
        exposure_mode = 'sequence_exposure'
        self.detector.set_full_well_mode(full_well_mode)
        self.detector.set_exposure_mode(exposure_mode)
        self.detector.set_readout_mode(readout_mode)
        self.config.update({'full_well_mode': full_well_mode,
                            'exposure_mode': exposure_mode,
                            'readout_mode': readout_mode})

    def _get_binning(self):
        return self.config['binning']  # self.detector.get_binning_mode()

    def _set_binning(self, value):
        if self.detector.is_live():
            raise RuntimeError('Cannot change binning while the detector is armed.')
        self.detector.set_binning_mode(value)
        self.config['binning'] = value

    def _get_psize(self):
        bins = self.binning
        if bins == 'x11':
            return self.PIXEL_SIZE
        elif bins == 'x22':
            return 2*self.PIXEL_SIZE
        elif bins == 'x44':
            return 4*self.PIXEL_SIZE
        else:
            raise RuntimeError("Unknown (or not implemented) binning for pixel size calculation.")

    def _get_shape(self) -> tuple:
        bins = self.binning
        if bins == 'x11':
            return self.SHAPE
        elif bins == 'x22':
            return self.SHAPE[0]//2, self.SHAPE[1]//2
        elif bins == 'x44':
            return self.SHAPE[0]//4, self.SHAPE[1]//4
        else:
            raise RuntimeError("Unknown (or not implemented) binning for shape calculation.")

    # FIXME: >>>>>>>>>>>>>>>>>>>>> END OF OLD VAREX CODE

    @property
    def is_recording(self):
        """
        Recording state
        """
        return self.sdk.get_recording_state()['recording state'] == 'on'

    @proxycall()
    @property
    def temperature(self):
        """
        Temperatures of 'sensor', 'camera' and 'power' unit
        """
        return self.sdk.get_temperature()

    @proxycall()
    @property
    def recording_status(self):
        """
        Recording status.

        The output contains a variety of information, including the number of images
        already acquired, a boolean telling if the buffer is full, a boolean telling
        if there has been an overflow in "fifo" mode, and so on... It can be called
        only after a pco.Camera().record() and before a pco.Camera().clear().
        """
        # FIXME: document better (and possibly reformat) the output ot this call.
        return self.rec.get_status()

    @proxycall()
    @property
    def status(self):
        """
        Camera health status
        """
        return self.sdk.get_camera_health_status()

    @proxycall()
    @property
    def info(self):
        """
        Extract information from camera interface.
        """
        info = self.sdk.get_camera_description()
        firmware = self.sdk.get_firmware_info(self.config['camera_number'])
        info['firmware'] = (firmware['name'], '{major}.{minor}.{variant}'.format(**firmware))
        info['camera'] = self.sdk.get_info_string('INFO_STRING_CAMERA')['info string']
        info['sensor'] = self.sdk.get_info_string('INFO_STRING_SENSOR')['info string']
        info['material'] = self.sdk.get_info_string('INFO_STRING_PCO_MATERIALNUMBER')['info string']

        return info

    def shutdown(self):
        """
        Shut down the camera and driver.
        """
        # FIXME: add here pco-specific shutdown procedure
        super().shutdown()

    @proxycall()
    @property
    def debug_level(self):
        """
        SDK debug level.
        ['off', 'error', 'verbose', 'extra verbose']
        """
        return self.config['debug_level']

    @debug_level.setter
    def debug_level(self, level):
        assert level in ['off', 'error', 'verbose', 'extra verbose'], 'Selected `debuglevel` is not valid. Refer to the docstring for accepted values.'
        self.config['debug_level'] = level
        # FIXME can this be changed after initialization?

    @proxycall()
    @property
    def print_timestamp(self):
        """
        SDK timestamp printing.
        True or False
        """
        return self.config['print_timestamp']

    @print_timestamp.setter
    def print_timestamp(self, switch):
        self.config['print_timestamp'] = switch
        # FIXME can this be changed after initialization?