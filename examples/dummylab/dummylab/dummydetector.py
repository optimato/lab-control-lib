"""
Dummy detector driver

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import numpy as np
import time

from lclib import register_driver, proxycall, proxydevice, manager
from lclib.camera import CameraBase

BASE_PATH = "C:\\data\\"

__all__ = ['Dummydetector']

ADDRESS = ('localhost', 5060)  # Address for the proxy driver

@register_driver
@proxydevice(address=ADDRESS)
class Dummydetector(CameraBase):
    """
    Dummy detector class
    """

    DEFAULT_BROADCAST_PORT = 8000  # Port to broadcast images for viewers
    BASE_PATH = BASE_PATH  # All data is saved in subfolders of this one
    PIXEL_SIZE = 50        # Physical pixel pitch in micrometers
    SHAPE = (256, 512)     # Native array shape (vertical, horizontal)
    MAX_FPS = 15           # The real max FPS is higher (especially in binning mode) but this seems sufficient.
    LOCAL_DEFAULT_CONFIG = {'binning':(1,1),
                            'save_path': 'C:\\snaps\\',
                            'gain_mode':'high'  # Example of camera-specific parameter
                            }
    
    # python <3.9
    DEFAULT_CONFIG = CameraBase.DEFAULT_CONFIG.copy()
    DEFAULT_CONFIG.update(LOCAL_DEFAULT_CONFIG)

    def __init__(self, broadcast_port=None):
        """
        Initialization.
        """
        super().__init__(broadcast_port=broadcast_port)

        self.detector = None
        self.init_device()

    def init_device(self):
        """
        Initialize camera
        """

        self.detector = 'Would be some kind of API object'
        self.logger.info('Detector is ready')

        # Apply saved configuration
        self.operation_mode = self.operation_mode  # Calls getter/setter
        self.exposure_time = self.config['exposure_time']
        self.binning = self.config['binning']
        self.exposure_number = self.config['exposure_number']
        self.initialized = True

    def _arm(self):
        """
        Prepare the camera for acquisition
        """
        self.logger.debug('Detector going live.')
        # self.detector.go_live() # Or whatever

    def _trigger(self):
        """
        Acquisition.
        """
        det = self.detector

        n_exp = self.exposure_number
        exp_time = self.exposure_time

        self.logger.debug('Triggering detector.')
        # det.software_trigger() # or whatever

        self.logger.debug('Starting acquisition loop.')
        frame_counter = 0
        while True:
            # Trigger metadata collection
            self.grab_metadata.set()

            # det.wait_for_new_frame() # or whatever
            time.sleep(self.exposure_time)

            # Get metadata
            man = manager.getManager()
            if man is None:
                self.logger.error("Not connected to manager! No metadata will available!")
                self.metadata = {}
            else:
                self.metadata = man.return_meta(request_ID=self.name)

            # Read out buffer
            # frame, meta = det.read_buffer() # or whatever
            frame = np.random.uniform(size=self.shape)
            meta = {'frame_counter':frame_counter}
            self.logger.debug(f'Acquired frame from buffer.')

            # Add frame to the queue
            self.enqueue_frame(frame, meta)

            # increment count
            frame_counter += 1

            if frame_counter == n_exp:
                # Exit if we have reached the requested nuber of exposures
                break

            if self.rolling and self.stop_rolling_flag:
                # Exit if rolling and stop was requested
                break

            if self.abort_flag.is_set():
                break

    def _disarm(self):
        # self.detector.disarm() # or whatever
        return

    def _rearm(self):
        # self.detector.rearm() # or whatever
        return

    def _get_exposure_time(self):
        return self.config['exposure_time']

    def _set_exposure_time(self, value):
        # self.detector.set_exposure_time(value) # or whatever
        self.config['exposure_time'] = value

    def _get_exposure_number(self):
        return self.config['exposure_number']

    def _set_exposure_number(self, value):
        # self.detector.set_num_of_exposures(value) # or whatever
        self.config['exposure_number'] = value

    def _get_operation_mode(self):
        opmode = {'gain_mode': self.config['gain_mode']}
        return opmode

    def _set_operation_mode(self, opmode):
        """
        Set operation mode.
        """
        # self.detector.set_gain(opmode['gain_mode']) # or whatever
        self.config.update(opmode)

    def _get_binning(self):
        return self.config['binning']

    def _set_binning(self, value):
        self.config['binning'] = tuple(value)

    def _get_psize(self):
        bins = tuple(self.binning)
        if bins == (1,1):
            return self.PIXEL_SIZE
        elif bins == (2,2):
            return 2*self.PIXEL_SIZE
        else:
            raise RuntimeError("Unknown (or not implemented) binning for pixel size calculation.")

    def _get_shape(self) -> tuple:
        bins = tuple(self.binning)
        if bins == (1,1):
            return self.SHAPE
        elif bins == (2,2):
            return self.SHAPE[0]//2, self.SHAPE[1]//2
        else:
            raise RuntimeError("Unknown (or not implemented) binning for shape calculation.")
