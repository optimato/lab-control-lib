import time

from .base import MotorBase, DriverBase, SocketDeviceServerBase, admin_only, emergency_stop, DeviceException
from .network_conf import XPS as DEFAULT_NETWORK_CONF
from . import motors
from .ui_utils import ask_yes_no

__all__ = ['XPSDeamon', 'XPS', 'Motor']

EOL = b'\n'
EOLr = b',EndOfApi'


class XPSDeamon(SocketDeviceServerBase):
    """
    XPS Daemon
    """

    DEFAULT_SERVING_ADDRESS = DEFAULT_NETWORK_CONF['DAEMON']
    DEFAULT_DEVICE_ADDRESS = DEFAULT_NETWORK_CONF['DEVICE']
    EOL = EOL
    EOLr = EOLr

    def __init__(self, serving_address=None, device_address=None):
        if serving_address is None:
            serving_address = self.DEFAULT_SERVING_ADDRESS
        if device_address is None:
            device_address = self.DEFAULT_DEVICE_ADDRESS
        super().__init__(serving_address=serving_address, device_address=device_address)

    def init_device(self):
        """
        Device initialization.
        """
        # try reading something back
        version = self.device_cmd(b'VERSION\n')
        self.logger.debug('Firmware version is %s.' % version.strip())

        # Set wait mode to NOWAIT. In this case, the controller will acknowledge all
        # commands immediately. This will prevent timeout errors. It should now also
        # be possible to query the AXISSTATUS while the axis is moving
        self.device_cmd(b'WAIT MODE NOWAIT\n')

        self.initialized = True
        return

    def wait_call(self):
        """
        Keep-alive call
        """
        r = self.device_cmd(b'AXISSTATUS(@0)\n')
        if not r:
            self.logger.critical('Disconnected')
            raise DeviceException('Disconnected.')

