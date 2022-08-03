"""
Base behaviour for all detectors.
"""


from . import experiment

DEFAULT_FILE_FORMAT = 'hdf5'


class CameraBase:
    """
    Representation of a pixel-array detector.

    This is the high-level class to work with on normal operations.
    """
    def __init__(self, name, driver):
        """

        """
        self.name = name
        self.driver = driver

    def snap(self):
        """
        Capture single frame.
        """
        pass # TODO

    def vsnap(self):
        """
        Capture single frame and show it in viewer.
        """
        pass # TODO

    def capture(self):
        """
        Image capture within a scan. This will take care of file naming and
        metadata collection.
        """
        if experiment.SCAN is None:
            raise RuntimeError('capture is meant to be used only in a scan context.')

    def sequence(self):
        """
        Capture a sequence within a scan. This will take care of file naming and
        metadata collection.
        """
        pass # TODO

    def viewer(self):
        """
        Interactive viewer
        """
        pass # TODO

    def settings(self, **kwargs):
        """
        Set camera-specific settings
        """
        raise NotImplementedError

    def set_file_format(self, file_format):
        """
        Set the file format for file saving.
        For now: one of 'hdf' or 'tif'.
        """
        pass # TODO

    # Methods that need to be implemented for the properties to work.
    def _set_exp_time(self, v):
        """
        Set exposure time
        """
        raise NotImplementedError

    def _get_exp_time(self):
        """
        Get exposure time
        """
        raise NotImplementedError

    def _get_shape(self):
        """
        Get current frame shape
        """
        raise NotImplementedError

    def _get_psize(self):
        """
        Get current pixel size (taking into account eventual binning)
        """
        raise NotImplementedError

    def _get_ROI(self):
        """
        Get current ROI parameters
        """
        raise NotImplementedError

    # Properties that can be set
    @property
    def exp_time(self):
        """
        Exposure time for a single frame.
        """
        return self._get_exp_time()

    @exp_time.setter
    def exp_time(self, v):
        """
        Set exposure time.
        """
        self._set_exp_time(v)

    # Properties that can only be accessed
    @property
    def shape(self):
        """
        [READ ONLY] The dimensions of a frame taken with current parameters.
        (numpy style, so (vertical, horizontal)
        """
        return self._get_shape()

    @property
    def psize(self):
        """
        [READ ONLY] The physical pixel size of a frame taken with current parameters.
        """
        return self._get_psize()

    @property
    def ROI(self):
        """
        The current detector region of interest, returned as two slice objects (vertical, horizontal)
        """
        return self._get_ROI()
