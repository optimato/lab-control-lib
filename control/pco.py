"""
PCO camera driver (epics-based)
"""

import epics as ep
import time
import os
import logging
import datetime
import json
import errno

from .base import DriverBase
from . import conf_path

__all__ = ['PCO']

DEFAULTS = {'exp_time': 1.,
            'file_type': 'HDF5',
            'drive': 'camserver',
            'path': '',
            'prefix': 'snap',
            'file_number': 0,
            'increment': False,
            'frame_count': 1,
            'num_exposures': 1,
            'time_stamp': 0,
            'pixel_rate': 0}

windows_drives = {'fileserver': 'D:/',
                  'camserver': 'D:/'} #fileserver changed from Z:/
local_drives = {'fileserver': '/camserver/',
                'camserver': '/camserver/'} #fileserver changed from /CTData_incoming/


class PCO(DriverBase):
    """
    Controller class for PCO camera through EPICS driver
    """

    logger = logging.getLogger(__name__)
    ARMING_DELAY = 1.1

    def __init__(self):
        """
        Initialisation.
        """
        DriverBase.__init__(self, poll_interval=10)

        self.config_file = os.path.join(conf_path, 'drivers', 'PCO_settings.json')

        # Everything is done by the initialisation/polling thread
        self.start_thread()

    @property
    def FT(self):
        return self.conf['file_type']

    def _init(self):
        """
        PCO driver initialisation.
        """
        self.logger.info("Initializing camera.")

        # Load default settings from disk
        self._load_conf()

        FT = self.FT

        self.logger.debug("File type: %s." % FT)

        self._last_arm = 0.
        self._last_capture = 0.

        # Initial camera settings
        # stop all capturing
        ep.caput('PCO:%s:Capture' % FT, 0)
        # disarm (arm = 1)
        ep.caput('PCO:CAM:Acquire', 0)
        # Acquire period in s, 0 for default
        ep.caput('PCO:CAM:AcquirePeriod', 0)
        # Disarm the camera
        ep.caput('PCO:CAM:ARM_MODE', 0)
        # Auto Acquire mode
        ep.caput('PCO:CAM:ACQUIRE_MODE', 0)
        # number of exposures per image, resulting image is sum over the num exposures
        ep.caput('PCO:CAM:NumExposures', 1)
        # number of images to capture (if ImageMode is "1-multiple")
        ep.caput('PCO:CAM:NumImages', 1)
        # Image mode: 0-single, 1-multiple, 2-continuous
        ep.caput('PCO:CAM:ImageMode', 1)
        # Trigger mode: 0-auto, 1-soft, 2-Ext.+Soft,3-Ext. Pulse, 5-Ext. only
        ep.caput('PCO:CAM:TriggerMode', 1)

        # HDF5 settings
        # Enable EPICS complaining about things
        ep.caput('PCO:%s:EnableCallbacks' % FT, 1)
        # Write mode:
        #     0 - single
        #     1 - capture (reads everything to memory, then writes in one file to disk)
        #     2 - Stream (appends to file on disk)
        ep.caput('PCO:%s:FileWriteMode' % FT, 2)
        # Needed to avoid EPICS wanting to have an image prior to recording
        ep.caput('PCO:%s:LazyOpen' % FT, 1)
        # Layout of the HDF5 file
        ep.caput('PCO:%s:XMLFileName' % FT, 'C:/autosave/exampleCamera/test01_hdf5layout.xml')
        # this file defines the layout of the
        # hdf5 file, including which metadata will be written
        # the definition of the metadata attributes is done in a separate xml file
        # (at the moment C:\epics\support\pcocam2-3-0-4\iocs\exampleStandalone\exampleStandaloneApp\data\attribute_list.xml)
        # this second file is specified in the .boot file of the ioc and loaded at startup.
        # It is stored in the PV PCO:HDF5:NDAttributesFile, this pointer can be changed via caput

        # TODO: reset ROI to full frame and binning to 1
        # self.pco_roi_reset()
        # self.pco_bin_xy_set(1, 1)
        # self.logger.debug("Binning and ROI reset.")

        # Add MQTT callback to the acquire process variable
        ep.get_pv('PCO:CAM:Acquire').add_callback(self._mqtt_callback)

        self._push_conf()

    def _push_conf(self):
        """
        Transfer conf to epics server.
        """

        FT = self.FT

        # Cancel if currently acquiring
        if ep.caget('PCO:CAM:Acquire_RBV'):
            raise RuntimeError('Camera is currently acquiring. Cannot push configuration now.')

        # Disarm if not already done
        if self._armed():
            ep.caput('PCO:CAM:ARM_MODE', 0)

        # Push all parameters
        ep.caput('PCO:CAM:AcquireTime', self.conf['exp_time'])
        ep.caput('PCO:CAM:AcquirePeriod', 0)
        path = os.path.join(windows_drives[self.conf['drive']], self.conf['path'])
        ep.caput('PCO:%s:FilePath' % FT, path)
        ep.caput('PCO:%s:FileName' % FT, self.conf['prefix'])
        ep.caput('PCO:%s:FileNumber' % FT, self.conf['file_number'])
        ep.caput('PCO:%s:AutoIncrement' % FT, self.conf['increment'])
        ep.caput('PCO:%s:NumCapture' % FT, self.conf['frame_count'])
        ep.caput('PCO:CAM:NumExposures', self.conf['num_exposures'])
        ep.caput('PCO:CAM:NumImages', self.conf['frame_count'])
        ep.caput('PCO:CAM:TIMESTAMP_MODE', self.conf['time_stamp'])
        ep.caput('PCO:CAM:PIX_RATE', self.conf['pixel_rate'])

        # Use Auto: needed because of a bug in PCO epics driver
        if (self.conf['num_exposures'] > 1) or (self.conf['frame_count'] > 1):
            ep.caput('PCO:CAM:TriggerMode', 0)
        else:
            ep.caput('PCO:CAM:TriggerMode', 1)

        # Store latest configuration on disc
        self._save_conf()

    def _load_conf(self):
        """
        Load configuration from disc.
        """
        try:
            with open(self.config_file, 'r') as f:
                self.conf = json.load(f)
        except IOError:
            self.logger.warn('Could not find config file "%s". Continuing with default values.' % self.config_file)
            # Create path
            try:
                os.makedirs(os.path.split(self.config_file)[0])
            except OSError as e:
                if e.errno == errno.EEXIST:
                    pass
                else:
                    raise
            self.conf = DEFAULTS
            # Save file
            self._save_conf()
            return False
        return True

    def _save_conf(self):
        """
        Save pco configuration.
        """
        with open(self.config_file, 'w') as f:
            json.dump(self.conf, f)

    def settings(self, **kwargs):
        """
        Return or set settings.
        :return:
        """
        if not kwargs:
            return self.conf

        # Some checks to avoid bad surprises:
        if ('exp_time' in kwargs.keys()) and (self.conf['num_exposures'] > 1) and ('num_exposures' not in kwargs.keys()):
            raise RuntimeError('Changing the exposure time without changing num_exposures looks like a mistake.')
        for parameter, value in kwargs.items():
            if not self.conf.has_key(parameter):
                raise RuntimeError('Unsupported setting key "%s"' % parameter)
            self.conf[parameter] = value

        # Push parameters to the camera
        self._push_conf()

        return self.conf

    def arm(self):
        """
        Arm the camera.
        (time of arming is saved to enable auto-disarm after some delay)
        """
        if not ep.caget('PCO:CAM:ARM_MODE_RBV'):
            ep.caput('PCO:CAM:ARM_MODE', 1)
            self.logger.debug('Arming camera')
            time.sleep(self.ARMING_DELAY)
        self._last_arm = time.time()
        return

    def _armed(self):
        """
        Returns true if camera is armed.
        """
        return ep.caget('PCO:CAM:ARM_MODE_RBV') and (time.time() - self._last_arm > self.ARMING_DELAY)

    def disarm(self):
        """
        Disarm the camera.
        """
        if ep.caget('PCO:CAM:ARM_MODE_RBV'):
            ep.caput('PCO:CAM:ARM_MODE', 0)
            self.logger.debug('Camera disarmed')
        return

    def capture(self, **kwargs):
        """
        Capture one or multiple frames, to be stored in a single file.
        See self.settings or self.conf for a list of (optional) accepted keyword arguments.

        NOTE: providing arguments requires disarming/rearming the camera (about 1s overhead)
        """

        FT = self.FT

        ACQ = ep.get_pv('PCO:CAM:Acquire')
        CAP = ep.get_pv('PCO:%s:Capture' % FT)

        # Apply optional settings
        if kwargs:
            self.settings(**kwargs)

        # Arm if not done already
        self.arm()

        # Construct local path
        path = os.path.join(local_drives[self.conf['drive']], self.conf['path'])

        # Create path if it doesn't exist
        if not os.path.exists(path):
            print('%s does not exist!' % path)
            os.makedirs(path)

        # Capture
        self.logger.debug('Starting capture')
        #self.mqtt_pub({'xnig/drivers/pco/exp_time': self.conf['exp_time'],
        #               'xnig/drivers/pco/acquire': ep.caget('PCO:CAM:Acquire_RBV')})

        t = datetime.datetime.now()
        fn = ep.caget('PCO:%s:FileNumber_RBV' % FT)
        ACQ.put(1)
        CAP.put(1, wait=True)
        self.logger.debug("Capture completed in %s seconds" % str(datetime.datetime.now()-t))

        # Construct file name
        ext = 'h5' if FT == 'HDF5' else 'tif'
        filename = os.path.join(local_drives[self.conf['drive']],
                                self.conf['path'],
                                '%s_%06d.%s' % (self.conf['prefix'], fn, ext))
        self.logger.debug('File "%s" saved.' % filename)

        self.mqtt_pub({'xnig/drivers/pco/acquire': ep.caget('PCO:CAM:Acquire_RBV'),
                       'xnig/drivers/pco/last_save': filename})

        # Update last arm time for auto-disarm
        self._last_capture = time.time()

        return filename

    def _mqtt_callback(self, **kwargs):
        """
        PV callback that pushes mqtt payloads.
        """
        if kwargs['pvname'] == 'PCO:CAM:Acquire':
            self.mqtt_pub({'xnig/drivers/pco/acquire': kwargs['value']})

    def _finish(self):
        """
        Stop polling and
        Disconnect socket.
        """
        ep.get_pv('PCO:CAM:Acquire').clear_callbacks()
        self.logger.info("Exiting.")

    def _poll(self):
        """
        Currently: auto-disarm
        """
        #if self._armed() and (time.time() > (self._last_arm + 600)) and (time.time() > (self._last_capture + 600)):
        #    self.logger.info('Auto-disarming the camera after 10 minutes.')
        #    ep.caput('PCO:CAM:ARM_MODE', 0)
        pass

    @property
    def exp_time(self):
        """
        Total exposure time
        """
        return self.conf['num_exposures'] * self.conf['exp_time']
