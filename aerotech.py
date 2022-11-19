"""
Aerotech rotation stage interface

The rotation stage and ensemble controller come preconfigured by Aerotech. The
file containing all factory setting is 600568-1-1.prme. If worst comes to worst
this can be loaded to restore a working setup. Most parameters can be set by the
ensemble composer software that runs on windows exclusively. Some parameters can
also be set through the ASCII command set.

!!! ASCII communication needs to be enabled through the ensemble windows software.
Also, the controller needs to be set to work as a server instead of client
for best ASCII communication performance.!!!

For the rest, a socket like for the smaracts or the mclennans can be used.
It looks like the controller DOES need to be polled continuously, but this
needs testing. This causes timing errors when a command is sent while motor
is being polled, leading to a timeout error... Other commands will be reading
the output of the polling, effectively flushing the buffer (or vice versa), so there
is nothing to read --> timeout error on sock...

The ASCII syntax seems to be "COMMAND @(AXIS) (VALUE)\n".

!!! Some commands (as AXISSTATUS) are dodgy and require different syntax!!!

The commands will return Ack/Nack, InvalidCharacter or TimeOut symbols.
The defaults are:
- Ack (success) : "%"
- Nack (fault): "#"
- InvalidCharacter: "!"
- TimeOut: "$"
these can be changed...

Command acknowledgement can be set to occur at different time points through
the WaitMode parameter. Possible values are NOWAIT, MOVEDONE and INPOS.
If set to either MOVEDONE or INPOS, it might be a good idea to set the socket
to blocking, i.e. "infinite" timeout time as moves might take a long time to
complete.

Initial Version: Hans Deyhle
06-2018: Object oriented version (PT)
"""

import time

from .base import MotorBase, SocketDriverBase, emergency_stop, DeviceException
from .network_conf import AEROTECH as NET_INFO
from .util.proxydevice import proxydevice, proxycall
from .util.uitools import ask_yes_no

__all__ = ['Aerotech', 'Motor']


@proxydevice(address=NET_INFO['control'])
class Aerotech(SocketDriverBase):
    """
    Aerotech socket driver.
    """

    DEFAULT_DEVICE_ADDRESS = NET_INFO['device']
    DEFAULT_LOGGING_ADDRESS = NET_INFO['logging']
    POLL_INTERVAL = 0.01     # temporization for rapid status checks during moves.
    EOL = b'\n'

    def __init__(self, device_address=None):
        device_address = device_address or self.DEFAULT_DEVICE_ADDRESS
        super().__init__(device_address=device_address)
        self.metacalls.update({'rotation_angle': self.get_pos})

    def init_device(self):
        """
        Device initialization.
        """
        # try reading something back
        version = self.device_cmd(b'VERSION\n')
        self.logger.debug('Firmware version is %s.' % version.strip())

        # Set wait mode to NOWAIT to get immediate acknowledgement.
        self.device_cmd(b'WAIT MODE NOWAIT\n')

        # enable axis if not already done.
        ae_en = self.axis_enable().strip()
        self.logger.debug(f'Axis enabled is {ae_en}.')

        # check if axis is already homed
        status = self.axis_status()
        if int(status[-2]) == 0:
            self.logger.warning('Caution, axis not homed!')
        else:
            self.logger.info('Axis already homed.')

        """
        # Create motor
        self.motor = {'rot': Motor('rot', self)}
        motors['rot'] = self.motor['rot']
        """

        self.logger.info(f"{self.name} initialization complete.")

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

    @proxycall()
    def axis_status(self):
        """
        Check the current status of axis. The status is bit encoded.
        Returns axis status
        """
        # query status
        status = self.device_cmd(b'AXISSTATUS(@0)\n')

        # parse status (32-bit)
        status = int(status[1:-1])  # need to get rid of the acknowledge and EOS characters
        status = bin(~status ^ (2 ** 32 - 1))  # stats is now a int-coded 32-bit map
        # actually the complement of fault, seems to be a problem with how python handles int to bin conversion
        # now ceck individual bins and look at status? Need to come up with a good way of doing this
        return status

    @proxycall()
    @property
    def axis_enabled(self):
        """
        Property to check if axis is enabled.
        """
        status = self.axis_status()
        return int(status[-1]) == 1

    @proxycall(admin=True)
    def axis_enable(self):
        """
        Enable axis connection on socket.
        """
        self.send_recv(b'ENABLE @0\n')
        if not self.axis_enabled:
            self.logger.critical('Error enabling axis:')
            self.axis_fault()
            self.logger.critical('Try axis_fault() to check for errors.')

    @proxycall(admin=True)
    def axis_disable(self):
        """
        Disable axis connected on socket
        """
        self.send_recv(b'DISABLE @0\n')
        if self.axis_enabled:
            self.logger.critical('Error disabling axis.')

    @proxycall(admin=True, block=False)
    def axis_home(self):
        """
        Home the axis
        """
        if not self.axis_enabled:
            self.logger.warning(f"Axis not enabled. See '{self.name}.axis_enable'")
            return

        # perform Homing
        homed = self.send_recv(b'HOME @0\n')
        self.check_done()
        return homed

    @proxycall(interrupt=True)
    def abort(self):
        """
        Emergency stop.
        """
        self.logger.info("ABORTING ROTATION!")
        self.send_recv(b'ABORT @0\n')

    @proxycall()
    def get_pos(self):
        """
        Get calibration corrected position in user units
        """
        pos = self.send_recv(b'PFBKCAL(@0)\n')

        try:
            pos = float(pos[1:-1])
        except:
            raise Warning("position was not returned as a number, this can occur when you cancel a move command")
        return pos

    @proxycall()
    def get_velocity(self):
        """
        Get velocity
        TODO: confirm degree/second?
        """
        vel = self.send_recv(b'VFBK(@0)\n')
        vel = float(vel[1:-1])
        return vel

    @proxycall(admin=True, block=False)
    def rot_abs(self, angle, speed=45):
        """
        Rotate the axis absolute to <angle> [deg] with <speed> [deg/s]
        Returns new position.

        TODO: allow this to be done
        """
        if not self.axis_enabled:
            self.logger.warning('Axis not enabled. Aborting.')
            return

        self.send_recv(f'MOVEABS @0 {angle} @0F {speed}\n'.encode())
        self.check_done()
        return self.get_pos()

    @proxycall(admin=True, block=False)
    def rot_rel(self, angle, speed=45):
        """
        Rotate the axis relative by <angle> [deg] with <speed> [deg/s]
        Returns new position
        """
        if not self.axis_enabled:
            self.logger.warning('Axis not enabled. Aborting.')
            return
        self.send_recv(f'MOVEINC @0 {angle} @0F {speed}\n'.encode())
        self.check_done()
        return self.get_pos()

    @proxycall(admin=True)
    def check_done(self):
        """
        Poll until movement is complete.
        """
        with emergency_stop(self.abort):
            while True:
                # query axis status
                status = self.axis_status()
                if int(status[-4]) == 0:
                    break
                # Temporise
                time.sleep(self.POLL_INTERVAL)
        self.logger.info("Finished moving theta stage.")

    @proxycall()
    def axis_fault(self):
        """
        Query the bit coded axis fault
        Returns fault code
        """
        fault = self.send_recv(b'AXISFAULT(@0)\n')

        # parse fault code
        fault = int(fault[1:-1])
        fault = bin(fault)

        # fault has 31 possible fault bits, check if any of those are 1
        if not int(fault, 2):
            self.logger.debug("No errors.")
            return
        else:
            fault_code = int(fault, 2)
            self.logger.critical('Error %s' % fault_code)
            self.logger.critical('Please refer to the ensemble help file for error code meaning.')

            if ask_yes_no('Clear errors?', yes_is_default=None):
                self.axis_fault_clear()
            else:
                self.logger.info('To clear all errors run axis_fault_clear().')

    @proxycall(admin=True)
    def axis_fault_clear(self):
        """
        Clear task errors and axis faults.
        """
        self.logger.info('Clearing errors...')
        self.send_recv(b'ACKNOWLEDGEALL\n')

        # check for faults for good measure...
        self.axis_fault()

    def _finish(self):
        """
        Disconnect socket.
        """
        self.logger.info("Exiting.")
        self.sock.close()


class Motor(MotorBase):
    def __init__(self, name, driver):
        super(Motor, self).__init__(name, driver)
        #self.limits = (-90., 270.)  # safer limits based on cabling - cabling has now changed

    def _get_pos(self):
        """
        Return position in degrees
        """
        return self.driver.get_pos()

    def _set_abs_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.rot_abs(x)

    def _set_rel_pos(self, x):
        """
        Set absolute position
        """
        return self.driver.rot_rel(x)
