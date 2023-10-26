"""
Driver for Varex flat panel based on our home-grown "dexela" API wrapper.
"""

import time
import importlib.util
import logging
import numpy as np
from threading import Event

from . import manager, register_proxy_client
from .camera import CameraBase
from .network_conf import VAREX as NET_INFO
from .util.proxydevice import proxydevice
from .util.future import Future

logger = logging.getLogger(__name__)

BASE_PATH = "C:\\data\\"

# Try to import dexela
if importlib.util.find_spec('dexela') is not None:
    import dexela
else:
    logger.debug("Module dexela unavailable on this host")
    class fake_dexela:
        def __getattr__(self, item):
            raise RuntimeError('Attempting to access "dexela" on a system where it is no present!')
    globals().update({'dexela': fake_dexela()})

__all__ = ['Varex']


@register_proxy_client
@proxydevice(address=NET_INFO['control'], stream_address=NET_INFO['stream'])
class Varex(CameraBase):
    """
    Varex Driver
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 74.8  # Physical pixel pitch in micrometers
    SHAPE = (1944, 1536)  # Native array shape (vertical, horizontal - after 90 degree cc rotation)
    DEFAULT_BROADCAST_PORT = NET_INFO['broadcast_port']
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    MAX_FPS = 5           # The real max FPS is higher (especially in binning mode) but this seems sufficient.
    DEFAULT_CONFIG = (CameraBase.DEFAULT_CONFIG |
                      {'binning':'x11',
                       'full_well_mode': 'high',
                       'exposure_mode': 'sequence_exposure',
                       'readout_mode': 'continuousreadout'})

    def __init__(self, broadcast_port=None):
        """
        Initialization.

        TODO: implement gap time.
        TODO: implement multiple exposure mode (if needed)
        """
        super().__init__(broadcast_port=broadcast_port)

        self.detector = None
        self.cont_acq_future = None      # Will be set with future created by init_rolling
        self._stop_continuous_acquisition = False
        self.cont_buffer = []
        self.cont_flag = Event()
        self.cont_flag.clear()
        self.init_device()

    def init_device(self):
        """
        Initialize camera
        """

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
            time.sleep(exp_time - .05)
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
                self.metadata = man.return_meta()

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
        # Convert from milliseconds to seconds
        return self.config['exposure_time']   # self.detector.get_exposure_time()

    def _set_exposure_time(self, value):
        # From seconds to milliseconds
        etime = int(value*1000)
        if self.detector.is_live():
            raise RuntimeError('Cannot set exposure time while the detector is armed.')
        self.detector.set_exposure_time(etime)
        self.config['exposure_time'] = value

    def _get_exposure_number(self):
        return self.config['exposure_number']  # self.detector.get_num_of_exposures()

    def _set_exposure_number(self, value):
        if self.detector.is_live():
            raise RuntimeError('Cannot set exposure number while the detector is armed.')
        self.detector.set_num_of_exposures(value)
        self.config['exposure_number'] = value

    def _get_operation_mode(self):
        opmode = {'full_well_mode': self.config['full_well_mode'],
                  'exposure_mode': self.config['exposure_mode'],
                  'readout_mode': self.config['readout_mode']}
        return opmode

    def _set_operation_mode(self, full_well_mode=None, exposure_mode=None, readout_mode=None):
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
