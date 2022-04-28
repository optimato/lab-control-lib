from .base import MotorBase
import numpy as np


class Motor(MotorBase):
    """
    Pseudo motor in the lab frame
    """

    def __init__(self, name, sx, sz, rot, axis):
        """
        Will use a combination of sx and sz given the value of the rotation stage rot.
        Calibration depends on the 0s of sx, sz and rot!
        """
        super(Motor, self).__init__(name, None)
        self.rot = rot
        self.sx = sx
        self.sz = sz
        self.axis = axis

    def _local_to_lab(self):
        th = self.rot.pos
        x0 = self.sx.pos
        y0 = self.sz.pos
        xl = x0 * np.cos(np.pi * th / 180.) - y0 * np.sin(np.pi * th / 180.)
        yl = x0 * np.sin(np.pi * th / 180.) + y0 * np.cos(np.pi * th / 180.)
        return xl, yl

    def _lab_to_local(self, xl, yl):
        th = self.rot.pos
        x = xl * np.cos(np.pi * th / 180.) + yl * np.sin(np.pi * th / 180.)
        y = -xl * np.sin(np.pi * th / 180.) + yl * np.cos(np.pi * th / 180.)
        return x, y

    def _get_pos(self):
        """
        Return dial position of lab coordinate in mm
        """
        return self._local_to_lab()[self.axis]

    def _set_abs_pos(self, x):
        """
        Set absolute position
        """
        # Get current lab position
        xl, yl = self._local_to_lab()

        # Convert back to local after update
        if self.axis == 0:
            x0, y0 = self._lab_to_local(x, yl)
        else:
            x0, y0 = self._lab_to_local(xl, x)

        # Move both motors simultaneously
        tx = self.sx.mv(x0, block=False)
        ty = self.sz.mv(y0, block=False)
        tx.join()
        ty.join()
        return x

    def _within_limits(self, x):
        """
        Check if *user* position x is within soft limits. Overridden from base class.
        """
        # Compute new local position based on x
        xl, yl = self._local_to_lab()

        # Convert back to local with x-self.offset as the other coordinate
        if self.axis == 0:
            x0, y0 = self._lab_to_local(x - self.offset, yl)
        else:
            x0, y0 = self._lab_to_local(xl, x - self.offset)

        # Check dial limits of both motors
        return (x0 > self.sx.limits[0]) and (x0 < self.sx.limits[1]) and \
               (y0 > self.sz.limits[0]) and (y0 < self.sz.limits[1])


class FakeMotor(MotorBase):
    """
    Can be useful for testing purposes, e.g:

    fsx = FakeMotor('fakesx')
    fsz = FakeMotor('fakesz')
    frot = FakeMotor('fakerot')
    fsxl = Motor('fsxl', fsx, fsz, frot, axis=0)
    fszl = Motor('fszl', fsx, fsz, frot, axis=1)

    (...)
    """

    def __init__(self, name):
        super(FakeMotor, self).__init__(name, None)
        self.dial = 0.

    def _get_pos(self):
        return self.dial

    def _set_abs_pos(self, x):
        self.dial = x