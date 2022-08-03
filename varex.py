"""
Driver for Varex flat panel

The DexelaPy library wrapper (available only under windows) is not
documented at all, but everything seems to be the same as the C++
API.

TODO: Many question marks, so many checks needed.

1. Does OpenBoard / CloseBoard need to be called often? Is there a
downside do calling OpenBoard on startup and keep it like this for weeks?



"""

import time
import importlib.util
import sys
import logging
import json

from .base import DriverBase, DeviceServerBase, admin_only, emergency_stop, DeviceException
from .network_conf import VAREX as DEFAULT_NETWORK_CONF
from .ui_utils import ask_yes_no
from .camera import CameraBase
from . import _varex_constants as vc
from . import FileDict

logger = logging.getLogger(__name__)


PIXEL_SIZE = 74.8e-6   # Physical pixel pitch in meters
SHAPE = (1536, 1944)   # Native array shape

# Try to import DexelaPy
if importlib.util.find_spec('DexelaPy') is not None:
    import DexelaPy
    from _varex_mappings import API_map
else:
    logger.info("Module DexelaPy unavailable")

    class FakeDexelaPy:
        def __getattr__(self, item):
            raise RuntimeError('Attempting to access DexelaPy on a system where it is no present!')

    globals().update({'DexelaPy': FakeDexelaPy()})

__all__ = ['VarexDaemon', 'Varex', 'Camera']


class VarexDaemon(DeviceServerBase):
    """
    Varex Daemon
    """

    DEFAULT_SERVING_ADDRESS = DEFAULT_NETWORK_CONF['DAEMON']

    def __init__(self, serving_address=None):
        """
        Initialization.
        """
        if serving_address is None:
            serving_address = self.DEFAULT_SERVING_ADDRESS
        super().__init__(serving_address=serving_address)

        self.detector = None
        self.detector_info = None

        # Used to store and restore current settings.
        self.config_filename = self.name + '.conf'

        self.config = FileDict(self.config_filename)

        settings = self.config.get('settings', {})

        settings.update({'well_mode': settings.get('well_mode', vc.FullWellModes.High),
                     'exp_mode': settings.get('exp_mode', vc.ExposureModes.Expose_and_read),
                     'exp_time': settings.get('exp_time', 200),
                     'trigger': settings.get('trigger', vc.ExposureTriggerSource.Internal_Software),
                     'binning': settings.get('binning', vc.Bins.x11),
                     'num_exp': settings.get('num_exp', 1),
                     'gap_time': settings.get('gap_time', 0)})
        # Save settings
        self.config['settings'] = settings


    def init_device(self):
        """
        Access detector using provided library
        """
        scanner = DexelaPy.BusScannerPy()
        count = scanner.EnumerateGEDevices()
        if count == 0:
            self.logger.critical("DexelaPy library did not find a connected device!")
            raise RuntimeError

        self.detector_info = scanner.GetDeviceGE(0)
        self.detector = DexelaPy.DexelaDetectorGE_Py(self.detector_info)
        self.logger.info('GigE detector is online')
        self.detector.OpenBoard()
        self._apply_settings()


    def device_cmd(self, cmd):
        """
        Implementation of the basic API:
         `DO:[some python code]`
           Take the python code and exec it. Return a jsoned version of the content of the 'out' dictionary

         `SNAP`
           Take a frame and save it with all current settings.

         `CAPTURE:SCAN_NUMBER`
           Take a frame with current settings, for scan number `SCAN_NUMBER`.

         `CONTINUOUS_START`
           Start continuous scan with current settings.

         `CONTINUOUS_STOP`
           Stop continuous scan with current settings.

        """
        if cmd.startswith(b'DO:'):
            ret = {'DexelaPy': DexelaPy, 'D':self, 'out':{}}
            exec(cmd.decode('utf-8'), {}, ret)
            return json.dumps(ret['out']).encode() + self.EOL

    def snap(self):


    def _apply_settings(self, settings=None):
        """
        Apply the settings in the settings dictionary.
        If settings is None, use self.settings
        """
        if settings is None:
            settings = self.config['settings']
        detector = self.detector
        detector.SetFullWellMode(API_map[settings['well_mode']])
        detector.SetExposureTime(API_map[settings['exp_time']])
        detector.SetBinningMode(API_map[settings['binning']])
        detector.SetNumOfExposures(API_map[settings['num_exp']])
        detector.SetTriggerSource(API_map[settings['trigger']])
        detector.SetGapTime(API_map[settings['gap_time']])
        detector.SetExposureMode(API_map[settings['exp_mode']])

    def _save_frame(self, frame):
        """
        Store buffered image to disk
        """

    def _finish(self):
        """
        Disconnect socket.
        """
        self.logger.info("Exiting.")
        self.detector.CloseBoard()


class Varex(DriverBase):
    """
    Varex driver
    """

    def __init__(self, address, admin=True, **kwargs):
        """
        Connects to daemon.
        """
        if address is None:
            address = DEFAULT_NETWORK_CONF['DAEMON']

        super().__init__(address=address, admin=admin)

        self.metacalls.update({}) # TODO

    def set_FullWellMode(self, mode):
        """
        Low = 0    # The low noise reduced dynamic range mode
        High = 1   # The normal full well mode
        """
        if mode not in [0, 1]:
            raise RuntimeError('Full Well Mode can only be 0 or 1')

        self.


class Camera(CameraBase):
    """
    Camera class for Varex driver
    """