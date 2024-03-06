"""
Driver for the Lambda 350 by xpectrum, built on top of their python interface.

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import time
import os
import importlib.util
import logging
import numpy as np

from lclib import register_proxy_client, proxycall, proxydevice, manager
from lclib.camera import CameraBase
from labcontrol.lclib.util.future import Future
from .network_conf import XLAM as NET_INFO


logger = logging.getLogger(__name__)

BASE_PATH = os.path.abspath(os.path.expanduser("~/data/"))

# Try to import pyxsp
if importlib.util.find_spec('pyxsp') is not None:
    import pyxsp
else:
    logger.debug("Module pyxsp unavailable on this host")
    class fake_pyxsp:
        def __getattr__(self, item):
            raise RuntimeError('Attempting to access "pyxsp" on a system where it is not present!')
    globals().update({'pyxsp': fake_pyxsp()})

__all__ = ['Xlam']


@register_proxy_client
@proxydevice(address=NET_INFO['control'])
class Xlam(CameraBase):
    """
    X-Spectrum lambda 350 Driver
    """

    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 55     # Physical pixel pitch in micrometers
    SHAPE = (516, 772)   # Native array shape (vertical, horizontal)
    DEFAULT_BROADCAST_PORT = NET_INFO['broadcast_port']
    SYSTEM_FILE = '/etc/opt/xsp/system.yml'
    LOCAL_DEFAULT_CONFIG = {'beam_energy': None,
                            'charge_summing':'on',
                            'counter_mode':'single',
                            'thresholds':[7, 15],
                            'bit_depth':14,
                            'voltage': 300.,
                            'save_path': '~/snaps/'}

    # python >3.9
    # DEFAULT_CONFIG = (CameraBase.DEFAULT_CONFIG | LOCAL_DEFAULT_CONFIG)
 
    # python <3.9
    DEFAULT_CONFIG = CameraBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(LOCAL_DEFAULT_CONFIG)

    def __init__(self, broadcast_port=None):
        """
        Initialization.
        """
        super().__init__(broadcast_port=broadcast_port)

        self.system = None
        self.det = None
        self.rec = None
        self.init_device()

    def init_device(self):
        """
        Initialize camera.
        """

        s = pyxsp.System(self.SYSTEM_FILE)
        if not s:
            raise RuntimeError('Loading pyxsp system file failed.')

        # Identify detector and receiver
        det_ID = s.list_detectors()[0]
        self.logger.debug(f'Detector ID: {det_ID}')

        rec_ID = s.list_receivers()[0]
        self.logger.debug(f'Receiver ID: {rec_ID}')

        # Open detector and receiver
        det = s.open_detector(det_ID)
        rec = s.open_receiver(rec_ID)

        det.connect()
        det.initialize()

        rec.connect()
        rec.initialize()

        self.logger.info('Lambda detector is online')

        self.system = s
        self.det = det
        self.rec = rec

        # The Lambda "forgets" parameters after reboots. We load the latest saved
        # on file
        operation_mode = {k: self.config[k] for k in ['beam_energy',
                                                      'bit_depth',
                                                      'charge_summing',
                                                      'counter_mode',
                                                      'thresholds']}
        self.operation_mode = operation_mode
        self.exposure_time = self.config['exposure_time']
        self.exposure_number = self.config['exposure_number']

        # self.initialized will be True only at completion of this Future
        self.future_init = Future(target=self._init)

    def _init(self):
        """
        Check if detector is ready
        """
        while not self.rec.ram_allocated:
            time.sleep(0.1)
        self.logger.debug('Ram allocated.')
        self.initialized = True

    def _arm(self):
        """
        Arming X Spectrum detector: nothing to do apparently.
        """
        if not self.initialized:
            raise RuntimeError('Initialization is not completed.')
        if not self.det.voltage_settled(1):
            self.logger.warning(f'Detector is not yet settled! (Current voltage: {self.voltage})')

    def _trigger(self):
        """
        Trigger the acquisition and manage frames.
        """
        num_frames = self.exposure_number
        exp_time = self.exposure_time
        rec = self.rec

        # Start acquiring
        self.logger.debug('Starting acquisition.')
        self.det.start_acquisition()

        # Manage dual mode
        dual = (self.counter_mode == 'dual')
        if dual:
            self.logger.debug('Dual mode: will grab 2x frames')
            frames = [[], []]
        else:
            frames = []
            fsub = frames

        pair = []

        frame_counter = 0
        while True:
            # Trigger metadata collection
            self.grab_metadata.set()

            # Wait for frame
            time.sleep(exp_time - .1)
            frame = rec.get_frame(2000*exp_time)
            if not frame:
                self.det.stop_acquisition()
                raise RuntimeError('Time out during acquisition!')

            # Check status
            if frame.status_code != pyxsp.FrameStatusCode.FRAME_OK:
                raise RuntimeError(f'Error reading frame: {frame.status_code.name}')

            sh = (rec.frame_height, rec.frame_width)
            fdata = np.array(frame.data)
            fdata.resize(sh)

            # Release RAM
            rec.release_frame(frame)

            if dual:
                if frame.subframe == 0:
                    self.logger.debug(f'Acquired frame {frame_counter}[0].')
                    pair = [fdata]
                    # Continue acquisition immediately
                    continue
                else:
                    self.logger.debug(f'Acquired frame {frame_counter}[1].')
                    pair.append(fdata)
                    fdata = np.array(pair)
            else:
                self.logger.debug(f'Acquired frame {frame_counter}.')

            # Get metadata
            man = manager.getManager()
            if man is None:
                self.logger.error("Not connected to manager! No metadata will available!")
                self.metadata = {}
            else:
                self.metadata = man.return_meta(request_ID=self.name)

            # Create metadata
            m = {'shape': sh,
                 'dtype': str(fdata.dtype),
                 'frame_counter': frame_counter + 1
                }

            # Add frame to the queue
            self.enqueue_frame(fdata, m)

            # increment count
            frame_counter += 1

            if frame_counter == num_frames:
                break

            if self.rolling and self.stop_rolling_flag:
                # Exit if rolling and stop was requested
                break

            if self.abort_flag.is_set():
                break

        # Out of loop
        self.det.stop_acquisition()



    def _disarm(self):
        """
        Nothing to do on Lambda.
        """
        pass

    def _get_exposure_time(self):
        # Convert to seconds
        exp_time = self.det.shutter_time / 1000
        self.config['exposure_time'] = exp_time
        return exp_time

    def _set_exposure_time(self, value):
        # Convert to milliseconds
        self.det.shutter_time = 1000 * value
        self.config['exposure_time'] = value

    def _get_exposure_number(self):
        n = self.det.number_of_frames
        self.config['exposure_number'] = n
        return n

    def _set_exposure_number(self, value):
        self.det.number_of_frames = value
        self.config['exposure_number'] = value

    def _get_operation_mode(self):
        opmode = {'beam_energy': self.beam_energy,
                  'bit_depth': self.bit_depth,
                  'charge_summing': self.charge_summing,
                  'counter_mode': self.counter_mode,
                  'thresholds': self.thresholds
                  }
        return opmode

    def _set_operation_mode(self, opmode):
        beam_energy = opmode.get('beam_energy')
        if beam_energy:
            self.beam_energy = beam_energy
        bit_depth = opmode.get('bit_depth')
        if bit_depth:
            self.bit_depth = bit_depth
        charge_summing = opmode.get('charge_summing')
        if charge_summing:
            self.charge_summing = charge_summing
        counter_mode = opmode.get('counter_mode')
        if counter_mode:
            self.counter_mode = counter_mode
        thresholds = opmode.get('thresholds')
        if thresholds:
            self.thresholds = thresholds

    def _get_binning(self):
        raise RuntimeError('Binning not available on this detector')

    def _set_binning(self, value):
        raise RuntimeError('Binning not available on this detector')

    def _get_psize(self):
        return self.PIXEL_SIZE

    def _get_shape(self) -> tuple:
        return self.SHAPE

    @proxycall(admin=True)
    @property
    def beam_energy(self):
        """
        Beam energy
        """
        be = self.det.beam_energy
        self.config['beam_energy'] = be
        return be

    @beam_energy.setter
    def beam_energy(self, value):
        self.det.beam_energy = value
        self.config['beam_energy'] = value

    @proxycall(admin=True)
    @property
    def bit_depth(self):
        """
        Bit depth: 1, 6, 12, 24
        """
        bd = self.det.bit_depth.value
        self.config['bit_depth'] = bd
        return bd

    @bit_depth.setter
    def bit_depth(self, value):
        if value == 1:
            self.det.bit_depth = pyxsp.BitDepth.DEPTH_1
        elif value == 6:
            self.det.bit_depth = pyxsp.BitDepth.DEPTH_6
        elif value == 12:
            self.det.bit_depth = pyxsp.BitDepth.DEPTH_12
        elif value == 24:
            self.det.bit_depth = pyxsp.BitDepth.DEPTH_24
        else:
            raise RuntimeError(f'Unknown or unsupported bit depth: {value}.')
        self.config['bit_depth'] = value

    @proxycall(admin=True)
    @property
    def charge_summing(self):
        """
        Charge summing ('on', 'off')
        """
        cs = self.det.charge_summing.name.lower()
        self.config['charge_summing'] = cs
        return cs

    @charge_summing.setter
    def charge_summing(self, value):
        if (value is True) or (value == 'on') or (value == 'ON'):
            self.det.charge_summing = pyxsp.ChargeSumming.ON
        elif (value is False) or (value == 'off') or (value == 'OFF'):
            self.det.charge_summing = pyxsp.ChargeSumming.OFF
        else:
            raise RuntimeError(f'charge_summing cannot be set to {value}.')
        self.config['charge_summing'] = value

    @proxycall(admin=True)
    @property
    def counter_mode(self):
        """
        Counter mode ('single', 'dual')
        """
        cm = self.det.counter_mode.name.lower()
        self.config['counter_mode'] = cm
        return cm

    @counter_mode.setter
    def counter_mode(self, value):
        if (value == 1) or (value == 'single') or (value == 'SINGLE'):
            self.det.counter_mode = pyxsp.CounterMode.SINGLE
        elif (value == 2) or (value == 'dual') or (value == 'DUAL'):
            self.det.ccounter_mode = pyxsp.CounterMode.DUAL
        else:
            raise RuntimeError(f'counter_mode cannot be set to {value}.')
        self.config['counter_mode'] = value

    @proxycall(admin=True)
    @property
    def thresholds(self):
        """
        Energy thresholds in keV
        """
        th = self.det.thresholds
        self.config['thresholds'] = th
        return th

    @thresholds.setter
    def thresholds(self, value):
        self.det.thresholds = value
        self.config['thresholds'] = value

    @proxycall(admin=True)
    @property
    def voltage(self):
        """
        Energy thresholds in keV
        """
        v = self.det.voltage(1)
        self.config['voltage'] = v
        return v

    @voltage.setter
    def voltage(self, value):
        self.det.set_voltage(1, value)
        self.config['voltage'] = value

    @proxycall()
    @property
    def temperature(self):
        """
        Sensor temperature (in degree C)
        """
        return self.det.temperature(1)
