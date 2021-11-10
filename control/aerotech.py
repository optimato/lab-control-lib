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

import socket
import os
import time

from .base import MotorBase, DriverBase
from . import motors
from .ui_utils import ask_yes_no

__all__ = ['AeroTech', 'Motor']


class AeroTech(DriverBase):
    """
    Controller class for the AeroTech rotation stage.
    """
    sock = None
    initialized = False

    def __init__(self, host='192.168.0.90', port=8000, poll_interval=10.):
        """
        Connect to axis and set some stuff

        :param host: control server address
        :param port: control server port
        """
        DriverBase.__init__(self, poll_interval=poll_interval)

        self.host = host
        self.port = port

        # This will run the initialisation on the thread
        self.start_thread()

    def _init(self):
        """
        Aerotech driver initialisation - running on the polling thread.
        """

        self.logger.info("Initialising AeroTech controller.")

        # create socket connection
        self.sock = socket.socket(socket.AF_INET,
                                  socket.SOCK_STREAM)  # STREAM should create a TCP socket, UDP is not recommended
        self.sock.settimeout(15)  #

        # connect
        conn_errno = self.sock.connect_ex((self.host, self.port))
        retry_count = 0  # counter for retries, limit to 10 retries
        while conn_errno != 0:  # and conn_errno != 114:
            self.logger.critical(os.strerror(conn_errno))
            time.sleep(.05)

            conn_errno = self.sock.connect_ex((self.host, self.port))
            retry_count += 1
            if retry_count > 10:
                raise RuntimeError('Connection refused.')

        # ---------------------------------------------------------------------------
        # try reading something back
        version = self.cmd_send('VERSION')
        self.logger.debug('Firmware version is %s.' % version.strip())

        # ---------------------------------------------------------------------------
        # set the waitmode to NOWAIT. In this case, the controller will Acknowledge all
        # commands immediately. This will prevent timeout errors. It should now also
        # be possible to query the AXISSTATUS while the axis is moving
        s = self._send_recv('WAIT MODE NOWAIT\n')

        # ---------------------------------------------------------------------------
        # enable axis
        ae_en = self.axis_enable()
        self.logger.debug('Axis enabled is %s.' % ae_en.strip())

        # home axis (user input)
        # ---------------------------------------------------------------------------
        # check if axis is already homed
        status = self.axis_status()
        if int(status[-2]) == 0:
            if ask_yes_no('Axis not homed, perform axis homing?', yes_is_default=False):
                self.axis_home()
            else:
                self.logger.warning('Caution, axis not homed!')
        else:
            self.logger.info('Axis already homed.')

        # Create motor
        self.motor = {'rot': Motor('rot', self)}
        motors['rot'] = self.motor['rot']

        self.logger.info("AeroTech initialization complete.")
        self.initialized = True

    def mqtt_payload(self):
        """
        Generate payload for MQTT, as a dictionary {topic: payload}
        """
        return {'xnig/drivers/aerotech/pos': self.pos_get(),
                'xnig/drivers/aerotech/status': self.axis_status()}

    def _send_recv(self, msg):
        """
        Send message to socket and receive reply message.
        """
        with self._lock:
            self.sock.sendall(msg)
            r = self.sock.recv(128)
            while r[-1:] != '\n':
                r += self.sock.recv(128)
        return r

    def cmd_send(self, cmd, **kwargs):
        """
        This method takes the ASCII input command and optional parameters
        and combines them to a format that can be understood by the Ensemble
        controller. This is then sent to the controller and the response returned.
        Syntax:
           self.cmd_send(cmd, **kwargs)
           cmd: the command string WITHOUT parameters
           possible **kwargs are:
            - axis=<axis>    the only possible axis at the moment is 0)
            - value=<value>  any floating point value to pass as argument to cmd
           returns the answer from the controller
        """

        # ---------------------------------------------------------------------------
        # start creating the output string
        str_in = cmd

        # ---------------------------------------------------------------------------
        # get the **kwargs
        if kwargs is not None:
            for key, value in kwargs.items():
                if key == 'axis':
                    axis = kwargs[key]
                    str_in = str_in + ' @' + str(axis)  # axis argument requires an '@' symbol
                elif key == 'value':
                    val = kwargs[key]
                else:
                    self.logger.warning('Unrecognized parameter %s. Aborting...' % key.strip())
                    return
        # put EOS character
        str_in += '\n'

        # ---------------------------------------------------------------------------
        # send command
        str_out = self._send_recv(str_in)
        return str_out

    def axis_status(self):
        """
        Check the current status of axis. The status is bit encoded.
        Returns axis status
        """

        # ---------------------------------------------------------------------------
        # query status
        status = self._send_recv('AXISSTATUS(@0)\n')

        # parse status (32-bit)
        status = int(status[1:-1])  # need to get rid of the acknowledge and EOS characters
        status = bin(~status ^ (2 ** 32 - 1))  # stats is now a int-coded 32-bit map
        # actually the complement of fault, seems to be a problem with how python handles int to bin conversion
        # now ceck individual bins and look at status? Need to come up with a good way of doing this
        return status

    def axis_enable(self):
        """
        Enable axis connection on socket.
        """
        # ---------------------------------------------------------------------------
        # enable
        enabled = self.cmd_send('ENABLE', axis=0)
        # query status to see if axis was enabled
        status = self.axis_status()
        # enable is bit 0
        if int(status[-1]) == 1:
            return status[-1]
        else:
            self.logger.critical('Error enabling axis:')
            self.axis_fault()
            self.logger.critical('Try running axis_fault() to check for errors.')

    def axis_disable(self):
        """
        Disable axis connected on socket
        """
        # ---------------------------------------------------------------------------
        # enable
        status = self.cmd_send('DISABLE', axis=0)
        if int(status[-1]) == 0:
            return status
        else:
            self.logger.critical('Error disabling axis.')

    def axis_home(self):
        """
        Home the axis
        """
        # ---------------------------------------------------------------------------
        # check if the axis is enabled
        status = self.axis_status()
        if int(status[-1]) == 0:
            self.logger.warning('Axis not enabled, please run aero_init() or aero_axis_enable() before moving anything!')
            self.logger.warning('Aborting...')
            return
        # ---------------------------------------------------------------------------
        # perform Homing
        homed = self.cmd_send('HOME', axis=0)
        # need to query axis till move is complete, so continuously check AXISSTATUS
        # till movement is complete
        move_done = False
        while not move_done:
            # query axis status
            status = self.axis_status()
            # check if axis is homing, this is bit 14 (0-based counting)
            if int(status[-15]) == 1:
                move_done = True
        return homed

    def pos_get(self, to_stdout=False):
        """
        Get calibration corrected position in user units
        """
        pos = self._send_recv('PFBKCAL(@0)\n')

        # ---------------------------------------------------------------------------
        # extract output
        if to_stdout:
            self.logger.debug(("Position: %s" % pos.strip()))

        try:
            pos = float(pos[1:-1])
        except:
            raise Warning("position was not returned as a number, this can occur when you cancel a move command")
        return pos

    def vel_get(self):
        vel = self._send_recv('VFBK(@0)\n')
        vel = float(vel[1:-1])
        return vel

    def rot_abs(self, angle, speed=45, averbose=False):
        """
        Rotate the axis absolute to <angle> [deg] with <speed> [deg/s]
        Returns new position.

        TODO: allow this to be done
        """
        # ---------------------------------------------------------------------------
        # check if the axis is enabled
        status = self.axis_status()
        if int(status[-1]) == 0:
            self.logger.warning('Axis not enabled, please run aero_init() or aero_axis_enable() before moving anything!')
            self.logger.warning('Aborting...')
            return
        # #---------------------------------------------------------------------------
        # # only allow positions between -180 and 180 to avoid twisting the smaract cables
        # if angle < -180 or angle > 180:
        #     # warn user and abort
        #     print 'requested angle %f outside range [-180,180], aborting...'
        #     return
        # # NO, perform this in user_defined_names_for_movements.py
        # # get current position
        # pos_curr = aero_pos_get(sock)
        # # need to make sure to always go over 0 to avoid twisting the smaract cables
        # pos_target = angle
        # angle = -(pos_curr - pos_target) # works?
        # ---------------------------------------------------------------------------
        # perform movement
        s = self._send_recv('MOVEABS @0 %f @0F %f\n' % (angle, speed))

        # need to query axis till move is complete, so continuously check AXISSTATUS
        # till movement is complete
        aborted = self.check_done(averbose)
        pos_new = self.pos_get()
        return pos_new

    def rot_rel(self, angle, speed=45, averbose=False):
        """
        Rotate the axis relative by <angle> [deg] with <speed> [deg/s]
        Returns new position
        """
        # ---------------------------------------------------------------------------
        # check if the axis is enabled
        status = self.axis_status()
        if int(status[-1]) == 0:
            self.logger.warning('Axis not enabled, please run aero_init() or aero_axis_enable() before moving anything!')
            self.logger.warning('Aborting...')
            return
        # ---------------------------------------------------------------------------
        # perform movement
        s = self._send_recv('MOVEINC @0 %f @0F %f\n' % (angle, speed))

        # need to query axis till move is complete, so continuously check AXISSTATUS
        # till movement is complete
        aborted = self.check_done(averbose)
        pos_new = self.pos_get()
        return pos_new

    def check_done(self, averbose=False):
        """
        Poll until movement is complete.
        """
        move_done = False
        while not move_done:
            try:
                # query axis status
                status = self.axis_status()
                if averbose:
                    self.logger.info(status)
                if int(status[-4]) == 0:
                    move_done = True
                    self.logger.info("Finished moving theta stage.")
            except KeyboardInterrupt:
                # run the abort command
                self._send_recv('ABORT @0\n') # works! but doesn't return angle properly
                print()
                self.logger.info("ABORTING THETA ROTATION!")
                return 1

            # Send rapid-fire update on mqtt
            self.mqtt_pub()

            # Temporise
            time.sleep(0.05)

        return 0

    def axis_fault(self):
        """
        Query the bit coded axis fault
        Returns fault code
        """
        # ---------------------------------------------------------------------------
        fault = self._send_recv('AXISFAULT(@0)\n')

        # ---------------------------------------------------------------------------
        # parse fault code
        fault = int(fault[1:-1])
        # fault = bin(~fault^(2**32-1)) # actually the complement of fault, seems to be a problem with how python handles int to bin conversion
        fault = bin(fault)

        # fault has 31 possible fault bits, check if any of those are 1
        if not int(fault, 2):
            self.logger.debug("No errors.")
            return
        else:
            fault_code = int(fault, 2)
            self.logger.critical('Error %s' % fault_code)
            # fault_code = np.asarray([i for i,l in enumerate(fault[-31:]) if l == '1'])
            # print 'error %s' % (fault_code-30)
            self.logger.critical('Please refer to the ensemble help file for error code meaning.')

            if ask_yes_no('Clear errors?', yes_is_default=None):
                self.axis_fault_clear()
            else:
                self.logger.info('To clear all errors run axis_fault_clear().')

    def axis_fault_clear(self):
        """
        Clear task errors and axis faults on all axes
        """
        # ---------------------------------------------------------------------------
        self.logger.info('Clearing errors...')
        ack = self._send_recv('ACKNOWLEDGEALL\n')

        # ---------------------------------------------------------------------------
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
        return self.driver.pos_get()

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
