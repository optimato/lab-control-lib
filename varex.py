"""
Driver for Varex flat panel based on our home-grown "dexela" API wrapper.
"""

import time
import importlib.util
import sys
import logging
import json

from .camera import CameraBase
from .network_conf import VAREX as DEFAULT_NETWORK_CONF
from .util.proxydevice import proxycall, proxydevice
from .ui_utils import ask_yes_no

logger = logging.getLogger(__name__)

BASE_PATH = "C:\\DATA\\"

# Try to import dexela
if importlib.util.find_spec('dexela') is not None:
    import dexela
else:
    logger.info("Module dexela unavailable")
    class FakeDexela:
        def __getattr__(self, item):
            raise RuntimeError('Attempting to access "dexela" on a system where it is no present!')
    globals().update({'DexelaPy': FakeDexela()})

__all__ = ['Varex']


@proxydevice(address=DEFAULT_NETWORK_CONF['DAEMON'])
class Varex(CameraBase):
    """
    Varex Driver
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 74.8e-6  # Physical pixel pitch in meters
    SHAPE = (1536, 1944)  # Native array shape (vertical, horizontal)
    DEFAULT_BROADCAST_PORT = DEFAULT_NETWORK_CONF['BROADCAST']

    def __init__(self, broadcast_port=None):
        """
        Initialization.
        """
        super().__init__(broadcast_port=broadcast_port)

        self.detector = dexela.DexelaDetector()

        self.logger.info('GigE detector is online')

        settings = self.config.get('settings', {})

        # Get stored settings, use defaults for parameters that can't be found
        settings.update({'full_well_mode': settings.get('full_well_mode', 'High'),
                         'exposure_mode': settings.get('exposure_mode', 'Expose_and_read'),
                         'exposure_time': settings.get('exposure_time', 200),
                         'bins': settings.get('bins', 'x11'),
                         'num_of_exposures': settings.get('num_of_exposures', 1),
                         'readout_mode': settings.get('readout_mode', 'ContinuousReadout'),
                         'gap_time': settings.get('gap_time', 0)})

        # Save settings
        self.config['settings'] = settings
        self._apply_settings()

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
        detector.set_bins(settings['bins'])

    def grab_frame(self):
        pass

    def _get_exposure_time(self):
        # Convert from milliseconds to seconds
        return self.detector.get_exposure_time() * 1000

    def _set_exposure_time(self, value):
        etime = int(value*1000)
        self.detector.set_exposure_time(etime)

    def _get_exposure_number(self):
        return self.detector.get_num_of_exposure()

    def _set_exposure_number(self, value):
        # TODO: IMPLEMENT THIS
        pass

    def _get_exposure_mode(self):
        return self.detector.get_exposure_mode()

    def _set_exposure_mode(self, value):
        # TODO: IMPLEMENT THIS
        pass

    def _get_binning(self):
        return self.detector.get_bins()

    def _set_binning(self, value):
        self.detector.set_bins(value)

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
