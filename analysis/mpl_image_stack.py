"""
Matplotlib image stack visualisation

Based on https://matplotlib.org/2.1.2/gallery/animation/image_slices_viewer.html

Simplest use is stackshow, behaves exactly like imshow but takes a 3D stack of images instead of a single 2D image.

TODO: maybe add other callbacks to skip frames/reset/readjust colorrange/etc.
"""

import numpy as np
import matplotlib.pyplot as plt

__all__ = ['stackshow']


class ImageStack(object):
    def __init__(self, X, ax=None, cmap=None, norm=None, aspect=None, interpolation=None, alpha=None,
           vmin=None, vmax=None, origin=None, extent=None, shape=None,
           filternorm=1, filterrad=4.0, imlim=None, resample=None, url=None,
           hold=None, data=None, **kwargs):
        """
        ImageStack object. Same signature as matplotlib.pyplot.imshow, but takes a 3D array (or list of images)
        as argument. Mouse scroll events are used to navigate the stack.
        """

        if ax is None:
            ax = plt.gca()
        self.ax = ax

        self.X = X
        self.slices = X.shape[0]
        self.ind = self.slices//2

        self.im = ax.imshow(self.X[self.ind], cmap=cmap, norm=norm, aspect=aspect,
                        interpolation=interpolation, alpha=alpha, vmin=vmin,
                        vmax=vmax, origin=origin, extent=extent, shape=shape,
                        filternorm=filternorm, filterrad=filterrad,
                        imlim=imlim, resample=resample, url=url, data=data,
                        **kwargs)
        plt.sci(self.im)
        self.ax.set_title('(%d)' % self.ind)
        self.update()

    def onscroll(self, event):
        """
        Callback function for the mouse scroll events.
        """
        if event.button == 'up':
            self.ind = (self.ind + 1) % self.slices
        else:
            self.ind = (self.ind - 1) % self.slices
        self.update()

    def update(self):
        self.im.set_data(self.X[self.ind])
        self.ax.set_title('(%d)' % self.ind)
        self.ax.figure.canvas.draw()


def stackshow(X, cmap=None, norm=None, aspect=None, interpolation=None, alpha=None,
           vmin=None, vmax=None, origin=None, extent=None, shape=None,
           filternorm=1, filterrad=4.0, imlim=None, resample=None, url=None,
           hold=None, data=None, **kwargs):
    """
    stackshow

    Same signature as matplotlib.pyplot.imshow, but takes a 3D array (or list of images)
    as argument. Mouse scroll events are used to navigate the stack.
    """
    s =  ImageStack(X, ax=None, cmap=cmap, norm=norm, aspect=aspect,
                        interpolation=interpolation, alpha=alpha, vmin=vmin,
                        vmax=vmax, origin=origin, extent=extent, shape=shape,
                        filternorm=filternorm, filterrad=filterrad,
                        imlim=imlim, resample=resample, url=url, data=data,
                        **kwargs)
    s.ax.figure.canvas.mpl_connect('scroll_event', s.onscroll)
    return s


if __name__ == "__main__":
    fig, ax = plt.subplots(1, 1)
    X = np.random.rand(40, 20, 20)
    s = ImageStack(X, ax)
    fig.canvas.mpl_connect('scroll_event', s.onscroll)
    plt.show()
