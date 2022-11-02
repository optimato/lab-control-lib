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
    logger.info("Module dexela unavailable")
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
    PIXEL_SIZE = 74.8e-6  # Physical pixel pitch in meters
    SHAPE = (1536, 1944)  # Native array shape (vertical, horizontal)
    DEFAULT_BROADCAST_PORT = NET_INFO['broadcast_port']

    def __init__(self, broadcast_port=None):
        """
        Initialization.

        TODO: implement gap time.
        TODO: implement multiple exposure mode (if needed)
        """
        super().__init__(broadcast_port=broadcast_port)

        self.detector = dexela.DexelaDetector()

        self.logger.info('GigE detector is online')

        settings = self.config.get('settings', {})

        # Get stored settings, use defaults for parameters that can't be found
        settings.update({'full_well_mode': settings.get('full_well_mode', 'High'),
                         'exposure_mode': settings.get('exposure_mode', 'sequence_exposure'),
                         'exposure_time': settings.get('exposure_time', .2),
                         'bins': settings.get('bins', 'x11'),
                         'num_of_exposures': settings.get('num_of_exposures', 1),
                         'readout_mode': settings.get('readout_mode', 'ContinuousReadout'),
                         'gap_time': settings.get('gap_time', 0)})

        # Save settings
        self.config['settings'] = settings
        self._apply_settings()
        self.detector.set_trigger_source('internal_software')

    def _apply_settings(self, settings=None):
        """
        Apply the settings in the settings dictionary.
        If settings is None, use self.settings
        """
        if settings is None:
            settings = self.config['settings']
        detector = self.detector
        detector.set_full_well_mode(settings['full_well_mode'])
        detector.set_exposure_mode(settings['exposure_mode'])
        detector.set_exposure_time(settings['exposure_time'])
        detector.set_num_of_exposures(settings['num_of_exposures'])
        detector.set_gap_time(settings['gap_time'])
        detector.set_binning_mode(settings['bins'])

    def grab_frame(self):
        """
        Grab and return frame(s)
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
        # TODO: find better way of dealing with multiframe metadata
        for i in range(n_exp):
            f, m = det.read_buffer(i)
            frames.append(f)
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
        etime = int(value*1000)
        self.detector.set_exposure_time(etime)
        self.config['settings']['exposure_time'] = etime

    def _get_exposure_number(self):
        return self.detector.get_num_of_exposures()

    def _set_exposure_number(self, value):
        self.detector.set_num_of_exposures(value)
        self.config['settings']['num_of_exposures'] = value

    def _get_exposure_mode(self):
        return self.detector.get_exposure_mode()

    def _set_exposure_mode(self, value):
        self.detector.set_full_well_mode(value)
        self.config['settings']['full_well_mode'] = value

    def _get_binning(self):
        return self.detector.get_binning_mode()

    def _set_binning(self, value):
        self.detector.set_binning_mode(value)
        self.config['settings']['bins'] = value

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
