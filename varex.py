"""
Driver for Varex flat panel based on our home-grown "dexela" API wrapper.
"""

import time
import importlib.util
import sys
import logging
import json

from .base import admin_only
from .camera import CameraServerBase, CameraDriverBase
from .network_conf import VAREX as DEFAULT_NETWORK_CONF
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

__all__ = ['VarexDaemon', 'Varex', 'Camera']


class VarexDaemon(CameraServerBase):
    """
    Varex Daemon
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    DEFAULT_SERVING_ADDRESS = DEFAULT_NETWORK_CONF['DAEMON']
    PIXEL_SIZE = 74.8e-6  # Physical pixel pitch in meters
    SHAPE = (1536, 1944)  # Native array shape (vertical, horizontal)

    def __init__(self, serving_address=None):
        """
        Initialization.
        """
        if serving_address is None:
            serving_address = self.DEFAULT_SERVING_ADDRESS
        super().__init__(serving_address=serving_address)

        self.detector = None
        self.detector_info = None

        settings = self.config.get('settings', {})

        # Get stored settings, use defaults for parameters that can't be found
        settings.update({'full_well_mode': settings.get('full_well_mode', 'High'),
                         'exposure_mode': settings.get('exposure_mode', 'Expose_and_read'),
                         'exposure_time': settings.get('exposure_time', 200),
                         'bins': settings.get('bins', 'x11'),
                         'num_of_exposures': settings.get('num_of_exposures', 1),
                         'readout_mode': settings.get('readout_mode', 'ContinuousReadout')
                         'gap_time': settings.get('gap_time', 0)})

        # Save settings
        self.config['settings'] = settings


    def init_device(self):
        """
        Access detector with the library
        """
        self.detector = dexela.DexelaDetector()
        self.logger.info('GigE detector is online')
        self._apply_settings()

    def device_cmd(self, cmd) -> bytes:
        """
        Varex specific commands.
        """
        cmds = cmd.strip(self.EOL).split()
        c = cmds.pop(0)
        if c == b'GET':
            c = cmds.pop(0)
            if c == b'FULL_WELL_MODE':
                return self.fr(self.get_full_well_mode())
            if c == b'READOUT_MODE':
                    return self.fr(self.get_readout_mode())

        elif c == b'SET':
            c = cmds.pop(0)
            if c == b'EXPOSURE_TIME':
                return self.fr(self.set_exposure_time(*cmds))
                if c == b'FULL_WELL_MODE':
                    return self.fr(self.get_full_well_mode())
                if c == b'READOUT_MODE':
                    return self.fr(self.get_readout_mode())
            elif c == b'EXPOSURE_MODE':
                return self.fr(self.set_exposure_mode(*cmds))

    def _apply_settings(self, settings=None):
        """
        Apply the settings in the settings dictionary.
        If settings is None, use self.settings
        """
        if settings is None:
            settings = self.config['settings']
        detector = self.detector
        detector.set_full_well_mode(settings['full_well_mode'])
        detector.set_fexposure_mode(settings['exposure_mode'])
        detector.set_exposure_time(settings['exposure_time'])
        detector.set_num_of_exposures(settings['num_of_exposures'])
        detector.set_gap_time(settings['gap_time'])
        detector.set_bins(settings['bins'])

    def go_live(self, fps=10):
        """
        Put the camera in live mode (frames are not saved)
        """
        self.logger.warning("Entering live mode. Frames are not saved.")
        self.



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

    def send_cmd(self, cmd, **kwargs):
        """
        Send a command to the Daemon.
        """
        msg = json.dumps([cmd, kwargs]).encode()
        return self.send_recv(msg + self.EOL)

    def go_live(self, fps=10):
        """
        Put the camera in live mode (frames are not saved)
        """
        self.logger.warning("Entering live mode. Frames are not saved.")
        self.send_cmd('go_live', fps=fps)

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