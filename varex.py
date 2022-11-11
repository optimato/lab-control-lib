"""
Driver for Varex flat panel based on our home-grown "dexela" API wrapper.
"""

import time
import importlib.util
import logging
import numpy as np

from .camera import CameraBase
from .network_conf import VAREX as NET_INFO
from .util.proxydevice import proxycall, proxydevice
from .ui_utils import ask_yes_no

logger = logging.getLogger(__name__)

BASE_PATH = "C:\\DATA\\"

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


@proxydevice(address=NET_INFO['control'])
class Varex(CameraBase):
    """
    Varex Driver
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 74.8  # Physical pixel pitch in micrometers
    SHAPE = (1536, 1944)  # Native array shape (vertical, horizontal)
    DEFAULT_BROADCAST_PORT = NET_INFO['broadcast_port']

    def __init__(self, broadcast_port=None):
        """
        Initialization.

        TODO: implement gap time.
        TODO: implement multiple exposure mode (if needed)
        """
        super().__init__(broadcast_port=broadcast_port)

        self.detector = None
        self.init_device()

    def init_device(self):
        """
        Initialize camera
        """

        self.detector = dexela.DexelaDetector()

        self.logger.info('GigE detector is online')

        self.operation_mode = self.config.get('operation_mode', None)
        self.exposure_time = self.config.get('exposure_time', .2)
        self.binning = self.config.get('binning', 'x11')
        self.exposure_number = self.config.get('exposure_number', 1)

        self.detector.set_gap_time(0)
        self.detector.set_trigger_source('internal_software')
        self.initialized = True

    def grab_frame(self):
        """
        Grab and return frame(s)

        Independent of the number of exposures, the returned array
        "frame" is a 3D array, with the frame index as the first dimension
        """
        det = self.detector
        n_exp = self.exposure_number

        det.go_live(0, n_exp - 1, n_exp)
        startCount = det.get_field_count()
        count = startCount + 0

        det.software_trigger()

        while True:
            count = det.get_field_count()
            if count > (startCount + n_exp):
                break
            det.check_for_live_error()
            time.sleep(.05)

        frames = []
        meta = {}
        for i in range(n_exp):
            f, m = det.read_buffer(i)
            frames.append(f)
            # Overwrite meta - it's all the same.
            meta = m

        if det.is_live():
            det.go_unlive()

        return np.array(frames), meta

    def roll(self, switch=None):
        """
        Toggle rolling mode.

        TODO
        """
        raise NotImplementedError

    def _get_exposure_time(self):
        # Convert from milliseconds to seconds
        return self.detector.get_exposure_time() / 1000

    def _set_exposure_time(self, value):
        # From seconds to milliseconds
        etime = int(value*1000)
        self.detector.set_exposure_time(etime)

    def _get_exposure_number(self):
        return self.detector.get_num_of_exposures()

    def _set_exposure_number(self, value):
        self.detector.set_num_of_exposures(value)
        self.config['settings']['num_of_exposures'] = value

    def _get_operation_mode(self):
        opmode = {'full_well_mode': self.detector.get_full_well_mode(),
                  'exposure_mode': self.detector.get_exposure_mode(),
                  'readout_mode': self.detector.get_readout_mode()}
        return opmode

    def set_operation_mode(self, full_well_mode=None, exposure_mode=None, readout_mode=None):
        """
        Set varex operation mode:

        * full_well_mode: ('high' or 'low')
        * exposure_mode: 'Expose_and_read', 'Sequence_Exposure', 'Frame_Rate_exposure', 'Preprogrammed_exposure'
            NOTE: only 'Sequence_Exposure' is supported for now
        * readout_mode: 'ContinuousReadout', 'IdleMode'
            NOTE: only 'ContinuousReadout is supported
        """
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
        self.config['settings']['operation_mode'] = {'full_well_mode': full_well_mode,
                                                     'exposure_mode': exposure_mode,
                                                     'readout_mode': readout_mode}

    def _get_binning(self):
        return self.detector.get_binning_mode()

    def _set_binning(self, value):
        self.detector.set_binning_mode(value)

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
