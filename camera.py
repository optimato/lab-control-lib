"""
Base behaviour for all detectors.
"""


from . import experiment


class CameraBase:
    """
    Representation of a pixel-array detector.
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

    def vsnap(self):
        """
        Capture single frame and show it in viewer.
        """

    def capture(self):
        """
        Image capture within a scan. This will take care of file naming and
        metadata collection.
        """

    def sequence(self):
        """
        Capture a sequence within a scan. This will take care of file naming and
        metadata collection.
        """

    def viewer(self):
        """
        Interactive viewer
        """

    def settings(self, **kwargs):
        """
        Set camera-specific settings
        """
        raise NotImplementedError

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