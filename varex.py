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

from .base import DriverBase, DeviceServerBase, admin_only, emergency_stop, DeviceException
from .network_conf import VAREX as DEFAULT_NETWORK_CONF
from .ui_utils import ask_yes_no
from .camera import CameraBase

logger = logging.getLogger(__name__)

# Try to import DexelaPy
if importlib.util.find_spec('DexelaPy') is not None:
    import DexelaPy
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

    def _SetFullWellMode(self, mode):
        """

        """

    def device_cmd(self, cmd):
        """

        """




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


class Camera(CameraBase):
    """
    Camera class for Varex driver
    """