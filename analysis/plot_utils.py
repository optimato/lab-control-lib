"""
Plotting utilities.

Author: Pierre Thibault
Date: June 23rd 2010
"""
import numpy as np
import time
import sys
from PIL import Image
import weakref
import matplotlib as mpl
import matplotlib.cm
import matplotlib.pyplot as plt
import pylab
from matplotlib.patches import Rectangle


# importing pyplot may fail when no display is available.
import os
if os.getenv("DISPLAY") is None:
    NODISPLAY = True
    matplotlib.use('agg')
    import matplotlib.pyplot
else:
    import matplotlib.pyplot
    NODISPLAY = False

# Improved interactive behavior or matplotlib 
import threading
if matplotlib.get_backend().lower().startswith('qt4'):
    mpl_backend = 'qt'
    from PyQt4 import QtGui
    gui_yield_call = QtGui.qApp.processEvents
elif matplotlib.get_backend().lower().startswith('wx'):
    mpl_backend = 'wx'
    import wx
    gui_yield_call = wx.Yield
elif matplotlib.get_backend().lower().startswith('gtk'):
    mpl_backend = 'gtk'
    import gtk
    def gui_yield_call():
        gtk.gdk.threads_enter()
        while gtk.events_pending():
            gtk.main_iteration(True)
        gtk.gdk.flush()
        gtk.gdk.threads_leave()
else:
    mpl_backend = None

__all__ = ['P1A_to_HSV', 'HSV_to_RGB', 'imsave', 'imload', 'franzmap',\
           'Multiclicks', 'DataBrowser','showim','data_browser',\
           'pause', 'plot_3d_array', 'dark_scheme','Interactive_rect_roi',\
	   'third_angle_projection','cut_3d_volume','colourmap']

# Fix tif import problem
Image._MODE_CONV['I;16'] = (Image._ENDIAN + 'u2', None)

# Grayscale + alpha should also work
Image._MODE_CONV['LA'] = (Image._ENDIAN + 'u1', 2)

if mpl_backend is not None:
    class _Pause(threading.Thread):
        def __init__(self, timeout, message):
            self.message = message
            self.timeout = timeout
            self.ct = True
            threading.Thread.__init__(self)
        def run(self):
            sys.stdout.flush()
            if self.timeout < 0:
                input(self.message)
            else:
                if self.message is not None:
                    print(self.message)
                time.sleep(self.timeout)
            self.ct = False

    def pause(timeout=-1, message=None):
        """\
        Pause the execution of a script while leaving matplotlib figures responsive.
        By default, execution is resumed only after hitting return. If timeout >= 0,
        the execution is resumed after timeout seconds.
        """
        if message is None:
            if timeout < 0:
                message = 'Paused. Hit return to continue.'
        h = _Pause(timeout, message)
        h.start()
        while h.ct:
            gui_yield_call()
            time.sleep(.01)

else:
    def pause(timeout=-1, message=None):
        """\
        Pause the execution of a script.
        By default, execution is resumed only after hitting return. If timeout >= 0,
        the execution is resumed after timeout seconds.
        This version of pause is not GUI-aware (this happens it the matplotlib
        backend is not supported).
        """
        if timeout < 0:
            if message is None:
                message = 'Paused. Hit return to continue.'
            input(message)
        else:
            if message is not None:
                print(message)
            time.sleep(timeout)


'''\
def P1A_to_HSV(cin):
    """\
    Transform a complex array into an RGB image,
    mapping phase to hue, amplitude to value and
    keeping maximum saturation.
    """

    # HSV channels
    h = .5*np.angle(cin)/np.pi + .5
    s = np.ones(cin.shape)
    v = abs(cin)
    v /= v.max()

    i = (6.*h).astype(int)
    f = (6.*h) - i
    q = v*(1. - f)
    t = v*f
    i0 = (i%6 == 0)
    i1 = (i == 1)
    i2 = (i == 2)
    i3 = (i == 3)
    i4 = (i == 4)
    i5 = (i == 5)

    imout = np.zeros(cin.shape + (3,), 'uint8')
    imout[:,:,0] = 255*(i0*v + i1*q + i4*t + i5*v)
    imout[:,:,1] = 255*(i0*t + i1*v + i2*v + i3*q)
    imout[:,:,2] = 255*(i2*t + i3*v + i4*v + i5*q)

    return imout
'''

def P1A_to_HSV(cin, vmin=None, vmax=None):
    """\
    Transform a complex array into an RGB image,
    mapping phase to hue, amplitude to value and
    keeping maximum saturation.
    """
    # HSV channels
    h = .5*np.angle(cin)/np.pi + .5
    s = np.ones(cin.shape)

    v = abs(cin)
    if vmin is None: vmin = 0.
    if vmax is None: vmax = v.max()
    assert vmin < vmax
    v = (v.clip(vmin,vmax)-vmin)/(vmax-vmin)

    return HSV_to_RGB((h,s,v))

def HSV_to_RGB(cin):
    """\
    HSV to RGB transformation.
    """

    # HSV channels
    h,s,v = cin

    i = (6.*h).astype(int)
    f = (6.*h) - i
    p = v*(1. - s)
    q = v*(1. - s*f)
    t = v*(1. - s*(1.-f))
    i0 = (i%6 == 0)
    i1 = (i == 1)
    i2 = (i == 2)
    i3 = (i == 3)
    i4 = (i == 4)
    i5 = (i == 5)

    imout = np.zeros(h.shape + (3,), dtype=h.dtype)
    imout[:,:,0] = 255*(i0*v + i1*q + i2*p + i3*p + i4*t + i5*v)
    imout[:,:,1] = 255*(i0*t + i1*v + i2*v + i3*q + i4*p + i5*p)
    imout[:,:,2] = 255*(i0*p + i1*p + i2*t + i3*v + i4*v + i5*q)

    return imout


def imsave(a, filename=None, vmin=None, vmax=None, cmap=None):
    """
    imsave(a) converts array a into, and returns a PIL image
    imsave(a, filename) returns the image and also saves it to filename
    imsave(a, ..., vmin=vmin, vmax=vmax) clips the array to values between vmin and vmax.
    imsave(a, ..., cmap=cmap) uses a matplotlib colormap.
    """

    if a.dtype.kind == 'c':
        # Image is complex
        if cmap is not None:
            print('imsave: Ignoring provided cmap - input array is complex')
        i = P1A_to_HSV(a, vmin, vmax)
        im = Image.fromarray(np.uint8(i), mode='RGB')

    else:
        if vmin is None:
            vmin = a.min()
        if vmax is None:
            vmax = a.max()
        im = Image.fromarray((255*(a.clip(vmin,vmax)-vmin)/(vmax-vmin)).astype('uint8'))
        if cmap is not None:
            r = im.point(lambda x: cmap(x/255.0)[0] * 255)
            g = im.point(lambda x: cmap(x/255.0)[1] * 255)
            b = im.point(lambda x: cmap(x/255.0)[2] * 255)
            im = Image.merge("RGB", (r, g, b))
        #b = (255*(a.clip(vmin,vmax)-vmin)/(vmax-vmin)).astype('uint8')
        #im = Image.fromstring('L', a.shape[-1::-1], b.tostring())

    if filename is not None:
        im.save(filename)
    return im

def imload(filename):
    """\
    Load an image and returns a numpy array
    """
    a = np.array(Image.open(filename))
    #a = np.fromstring(im.tostring(), dtype='uint8')
    #if im.mode == 'L':
    #    a.resize(im.size[-1::-1])
    #elif im.mode == 'LA':
    #    a.resize((2,im.size[1],im.size[0]))
    #elif im.mode == 'RGB':
    #    a.resize((3,im.size[1],im.size[0]))
    #elif im.mode == 'RGBA':
    #    a.resize((4,im.size[1],im.size[0]))
    #else:
    #    raise RunTimeError('Unsupported image mode %s' % im.mode)
    return a

# Franz map
mpl.cm.register_cmap(name='franzmap',data=
                   {'red': ((   0.,    0,    0),
                            ( 0.35,    0,    0),
                            ( 0.66,    1,    1),
                            ( 0.89,    1,    1),
                            (    1,  0.5,  0.5)),
                  'green': ((   0.,    0,    0),
                            ( 0.12,    0,    0),
                            ( 0.16,   .2,   .2),
                            (0.375,    1,    1),
                            ( 0.64,    1,    1),
                            ( 0.91,    0,    0),
                            (    1,    0,    0)),
                  'blue':  ((   0.,    0,    0),
                            ( 0.15,    1,    1),
                            ( 0.34,    1,    1),
                            (0.65,     0,    0),
                            (1, 0, 0)) },lut=256)
def franzmap():
    """\
    Set the default colormap to Franz's map and apply to current image if any.
    """
    mpl.pyplot.rc('image', cmap='franzmap')
    im = mpl.pyplot.gci()

    if im is not None:
        im.set_cmap(matplotlib.cm.get_cmap('franzmap'))
    mpl.pyplot.draw_if_interactive()
    
    
def plot_3d_array(data, axis=0, title='3d', cmap='gray', interpolation='nearest', vmin=None, vmax=None,**kwargs):
    '''
    plots 3d data with a slider to change the third dimension
    unfortunately the number that the slider shows is rounded weirdly.. be careful!
    TODO: fix that!

    input:
        - data: 3d numpy array containing the data
        - axis: axis that should be changeable by the slider

    author: Mathias Marschner
    added: 30.10.2013
    '''
    fig = plt.figure()
    ax = fig.add_subplot(111)
    plt.title(title)

    if vmin == None:
        vmin = data.min()
    if vmax == None:
        vmax = data.max()

    if axis == 0:
        cax = ax.imshow(data[data.shape[0]/2,:,:], cmap=cmap, vmin=vmin, vmax=vmax, interpolation=interpolation,**kwargs)
    elif axis == 1:
        cax = ax.imshow(data[:,data.shape[1]/2,:], cmap=cmap, vmin=vmin, vmax=vmax, interpolation=interpolation,**kwargs)
    elif axis == 2:
        cax = ax.imshow(data[:,:,data.shape[2]/2], cmap=cmap, vmin=vmin, vmax=vmax, interpolation=interpolation,**kwargs)

    cbar = fig.colorbar(cax)
    axcolor = 'lightgoldenrodyellow'
    ax4 = pylab.axes([0.1, 0.01, 0.8, 0.03], axisbg=axcolor)
    sframe = pylab.Slider(ax4, '', 0, data.shape[axis]-1, valinit=data.shape[axis]/2, closedmin = True, closedmax = True, valfmt = '%d')

    def update(val):
        frame = np.around(np.clip(sframe.val, 0, data.shape[axis]-1))
        if axis == 0:
            cax.set_data(data[frame,:,:])
        elif axis == 1:
            cax.set_data(data[:,frame,:])
        elif axis == 2:
            cax.set_data(data[:,:,frame])

    sframe.on_changed(update)
    return ax     


class Multiclicks(object):
    """\
    Little class to register (and show) the points that are clicked on the specified axis.
    The coordinates are stored in the attribute 'pts'.
    This starts upon creation and finishes when return is pressed.
    The default mode is 'append', that is, build a list of clicked points. The other option is 'replace',
    which allows only for one point, replaced at every click.

    Note: it is a good idea to use Multiclicks.wait_until_closed() after showing the figure to
    ensure that nothing happens until the figure is closed (in multi-threaded cases).

    Example (with ipython -pylab):
    imshow(my_image)
    ax = gca()
    ax.set_title('Select center point (hit return to finish)')
    s = U.Multiclicks(ax, True, mode='replace')
    s.wait_until_closed()
    print "you selected the point: " + str(s.pts[0])
    """

    def __init__(self, ax=None, close=False, mode='append'):
        self.close_ev =  (mpl.__version__ >= '1.0')
        self.isGTK = (mpl.get_backend() == 'GTKAgg') and not self.close_ev
        self.isQt = (mpl.get_backend() == 'Qt4Agg') and not self.close_ev
        self.isTk = (mpl.get_backend() == 'TkAgg') and not self.close_ev
        if not (self.close_ev or self.isGTK or self.isQt or self.isTk):
            raise RuntimeError('Multiclick requires matplotlib version 1.0+ or Qt4Agg or GTKAgg or TkAgg backends.')
        if ax is None:
            ax = mpl.pyplot.gca()
        canvas = ax.figure.canvas
        self.close = close
        self.is_closed = False
        self.axes = weakref.ref(ax)
        self.canvas = weakref.ref(ax.figure.canvas)
        self.pts = []
        self.mode = mode
        self.line = None
        self.cids = []
        self.cids.append(canvas.mpl_connect('button_press_event', self.onpress))
        self.cids.append(canvas.mpl_connect('key_press_event', self.onkeypress))
        if self.close_ev:
            self.cids.append(canvas.mpl_connect('close_event', self.onclose))
    def onpress(self, event):
        axes = self.axes()
        if event.inaxes != axes: return
        if event.button!=1: return
        x,y = event.xdata, event.ydata
        if self.mode == 'append':
            self.pts.append((x,y))
        elif self.mode == 'replace':
            self.pts = [(x,y)]

        if self.line is None:
            self.line = mpl.lines.Line2D([x], [y], linestyle='None', marker='s', markeredgecolor='black', markersize=6)
            axes.add_line(self.line)
        else:
            self.line.set_data(list(zip(*self.pts)))

        self.click()

        canvas = self.canvas()
        canvas.draw_idle()

    def click(self):
        """\
        This can be overloaded to do something every time the figure is clicked
        """
        pass

    def onkeypress(self, event):
        if event.key in ['enter', None]:
            self.stop()

    def onclose(self, event=None):
        self.is_closed = True

    def stop(self):
        if self.close:
            self.is_closed = True
            mpl.pyplot.close(self.axes().figure)
            return
        axes = self.axes()
        canvas = self.canvas()
        axes.lines.remove(self.line)
        for cid in self.cids:
            canvas.mpl_disconnect(cid)
        canvas.draw_idle()
        self.line = None
        self.cids = None

    def wait_until_closed(self):
        if self.is_closed:
            return
        if self.isTk:
            from tkinter import TclError
        while True:
            if self.isGTK:
                self.is_closed = not self.canvas().get_visible()
            elif self.isQt:
                try:
                    w = self.canvas().window()
                except RuntimeError:
                    self.is_closed = True
            elif self.isTk:
                try:
                    w = self.canvas().get_tk_widget().winfo_exists
                except TclError:
                    self.is_closed = True
            if self.is_closed:
                break
            mpl.pyplot.waitforbuttonpress(1)

class DataBrowser(object):
    """
    Click on a pixel to have a popup tell you the location and value of it.
    Use the arrow keys to change pixels if using the Qt4Agg backend.
    If using another backend, pixels can also be navigated with 'h', 'j', 'k' and 'l' (vi style)
    Use 'r', 'c' or 'b' to make line plots for current row, current column or both respectively.
    Use 'q' to get out of the DataBrowser mode and restore the original keyboard mapping.

    Example of usage (with ipython -pylab):
    x = rand(10,10)
    im = imshow(x,picker=True)
    b = U.DataBrowser(im)
    b.connect()

    or use:

    U.showim(x)

    to plot the array x and connect the figure with the DataBrowser automatically.

    or use:

    U.data_browser(fignum = None)

    to connect the current figure or the figure with number fignum to the DataBrowser.

    """
    def __init__(self,im):
        self.is_connected = False
        self.both_plot_active = False
        self.column_plot_active = False
        self.row_plot_active = False
        self.isQt = (mpl.get_backend() == 'Qt4Agg')
        if (self.isQt):
            from PyQt4 import QtCore
            mpl.backends.backend_qt4.FigureCanvasQT.keyvald[QtCore.Qt.Key_Left] = 'left'
            mpl.backends.backend_qt4.FigureCanvasQT.keyvald[QtCore.Qt.Key_Right] = 'right'
            mpl.backends.backend_qt4.FigureCanvasQT.keyvald[QtCore.Qt.Key_Up] = 'up'
            mpl.backends.backend_qt4.FigureCanvasQT.keyvald[QtCore.Qt.Key_Down] = 'down'
        self.im = im
        self.cid_orig_keypress_event = list(self.im.figure.canvas.callbacks.callbacks['key_press_event'].keys())[0]
        self.orig_keypress_event = self.im.figure.canvas.callbacks.callbacks['key_press_event'][self.cid_orig_keypress_event]
        self.im.figure.canvas.mpl_disconnect(self.cid_orig_keypress_event)
        if self.im.get_picker() is not True:
            self.im.set_picker(True)
        self.lastind = (0,0)
        self.arr_data = 0.
        self.ann = None
        self.both_line_1 = None
        self.both_line_2 = None
        self.row_line = None
        self.col_line = None
        self.row_fig = None
        self.col_fig = None
        self.line_fig = None
        self.e = None

    def connect(self):
        if not self.is_connected:
            self.cid_press = self.im.figure.canvas.mpl_connect('key_press_event',self.onpress)
            self.cid_pick = self.im.figure.canvas.mpl_connect('pick_event',self.onpick)
            self.im.figure.canvas.mpl_connect('close_event', self.onclose)
            self.is_connected = True
            self.status = self.im.axes.text(.01,1.02,'DataBrowser active',transform=self.im.axes.transAxes, color='red')
            self.im.figure.canvas.draw()
        else:
            raise Exception('already connected')

    def onpress(self, event):
        if self.lastind is None: return
        if event.key not in ('left', 'right', 'up','down','q','h','j','k','l','r','c','b'): return
        x = 0
        y = 0
        if (event.key=='up' and self.isQt) or event.key == 'k': x = -1
        elif (event.key=='left' and self.isQt) or event.key == 'h': y=-1
        elif (event.key=='down' and self.isQt) or event.key == 'j': x=1
        elif (event.key=='right' and self.isQt) or event.key == 'l': y=1
        elif event.key == 'q':
            self.disconnect()
            return
        elif event.key == 'r':
            self.plot_row()
        elif event.key == 'c':
            self.plot_column()
        elif event.key == 'b':
            self.plot_both()

        if self.lastind[0]+x < 0 or self.lastind[1]+y < 0 or self.lastind[0]+x > self.im.get_size()[0] or self.lastind[1]+y > self.im.get_size()[1]:
            return
        self.lastind = (self.lastind[0]+x, self.lastind[1]+y)
        self.update()

    def onpick(self, event):
       # the click locations
       y = np.round(event.mouseevent.xdata)+.5
       x = np.round(event.mouseevent.ydata)+.5
       self.lastind = (x,y)
       self.update()

    def onclose(self,event):
        if self.row_fig is not None and matplotlib.pyplot.fignum_exists(self.row_fig.number):
            matplotlib.pyplot.close(self.row_fig)
        if self.col_fig is not None and matplotlib.pyplot.fignum_exists(self.col_fig.number):
            matplotlib.pyplot.close(self.col_fig)
        if self.line_fig is not None and matplotlib.pyplot.fignum_exists(self.line_fig.number):
            matplotlib.pyplot.close(self.line_fig)

    def onclose_lineplot(self, event):
        self.e = event
        if self.both_line_1 in self.im.axes.lines and matplotlib.pyplot.fignum_exists(self.im.figure.number):
            self.im.axes.lines.remove(self.both_line_1)
            self.im.axes.lines.remove(self.both_line_2)
            self.im.figure.canvas.draw()
            self.both_plot_active = False

    def onclose_rowplot(self,event):
        if self.row_line in self.im.axes.lines and matplotlib.pyplot.fignum_exists(self.im.figure.number):
            self.im.axes.lines.remove(self.row_line)
            self.im.figure.canvas.draw()
            self.row_plot_active = False

    def onclose_colplot(self,event):
        if self.col_line in self.im.axes.lines and matplotlib.pyplot.fignum_exists(self.im.figure.number):
            self.im.axes.lines.remove(self.col_line)
            self.im.figure.canvas.draw()
            self.column_plot_active = False

    def update(self):
        if self.lastind is None: return
        dataind = self.lastind
        max_x, max_y = self.im.get_size()
        x_offset = 20
        y_offset = 20
        if dataind[0] > max_x/2:
            y_offset = 20
        else:
            y_offset = -20
        if dataind[1] > max_y/2:
            x_offset = -95
            arrow_offset = .8
        else:
            x_offset = 20
            arrow_offset = .2

        A = self.im.get_array()
        self.arr_data = A[dataind[0],dataind[1]]
        if self.ann in self.im.axes.texts:
            self.im.axes.texts.remove(self.ann)
        self.ann = self.im.axes.annotate('x: %d\ny: %d\nval: %f' % (dataind[0],dataind[1],self.arr_data), (dataind[1]-.5,dataind[0]-.5),  xycoords='data',
                xytext=(x_offset,y_offset), textcoords='offset points',
                size=10, va="center",
                bbox=dict(boxstyle="round", fc=(.7, 0.7, 0.7), ec="none"),
                arrowprops=dict(arrowstyle="wedge,tail_width=1.",
                                fc=(.7, 0.7, 0.7), ec="none",
                                patchA=None,
                                patchB=None,
                                relpos=(arrow_offset, 0.5),
                                )
                )
        self.im.figure.canvas.draw()
        if self.both_plot_active:
            if not matplotlib.pyplot.fignum_exists(self.line_fig.number):
                self.im.axes.lines.remove(self.both_line_1)
                self.im.axes.lines.remove(self.both_line_2)
                self.both_plot_active = False
                return
            else:
                self.plot_both()
                if self.both_line_1 in self.im.axes.lines:
                    self.im.axes.lines.remove(self.both_line_1)
                if self.both_line_2 in self.im.axes.lines:
                    self.im.axes.lines.remove(self.both_line_2)
                self.both_line_1, = self.im.axes.plot([dataind[1]-.5,dataind[1]-.5],[-.5,max_x-.5],'r')
                self.both_line_2, = self.im.axes.plot([-.5,max_y-.5],[dataind[0]-.5,dataind[0]-.5],'g')
                self.im.axes.set_xlim([-.5,max_y-.5])
                self.im.axes.set_ylim([max_x-.5,-.5])

        if self.row_plot_active:
            if not matplotlib.pyplot.fignum_exists(self.row_fig.number):
                self.im.axes.lines.remove(self.row_line)
                self.row_plot_active = False
                return
            else:
                self.plot_row()
                if self.row_line in self.im.axes.lines:
                    self.im.axes.lines.remove(self.row_line)
                self.row_line, = self.im.axes.plot([-.5,max_y-.5],[dataind[0]-.5,dataind[0]-.5],'g')
                self.im.axes.set_xlim([-.5,max_y-.5])
                self.im.axes.set_ylim([max_x-.5,-.5])

        if self.column_plot_active:
            if not matplotlib.pyplot.fignum_exists(self.col_fig.number):
                self.im.axes.lines.remove(self.col_line)
                self.column_plot_active = False
                return
            else:
                self.plot_column()
                if self.col_line in self.im.axes.lines:
                    self.im.axes.lines.remove(self.col_line)
                self.col_line, = self.im.axes.plot([dataind[1]-.5,dataind[1]-.5],[-.5,max_x-.5],'r')
                self.im.axes.set_xlim([-.5,max_y-.5])
                self.im.axes.set_ylim([max_x-.5,-.5])


    def disconnect(self):
        if self.is_connected:
            if self.ann in self.im.axes.texts:
                self.im.axes.texts.remove(self.ann)
                if self.status in self.im.axes.texts:
                    self.im.axes.texts.remove(self.status)
                if self.both_line_1 in self.im.axes.lines:
                    self.im.axes.lines.remove(self.both_line_1)
                    self.im.axes.lines.remove(self.both_line_2)
                self.im.figure.canvas.mpl_disconnect(self.cid_press)
                self.im.figure.canvas.mpl_disconnect(self.cid_pick)
                self.im.figure.canvas.mpl_connect('key_press_event', self.orig_keypress_event)
        self.im.figure.canvas.draw()
        self.is_connected = False

    def plot_row(self):
        if not self.row_plot_active or not matplotlib.pyplot.fignum_exists(self.row_fig.number):
            self.row_plot_active = True
            self.row_fig = matplotlib.pyplot.figure()
        else:
            self.row_fig.clf()
        ax = self.row_fig.add_subplot(111)
        A = self.im.get_array()
        line, = ax.plot(A[self.lastind[0],:])
        ax.set_xlim(0,A.shape[1]-1)
        ax.set_xlabel('horizontal coordinate')
        self.row_fig.canvas.mpl_connect('close_event',self.onclose_rowplot)
        self.row_fig.canvas.draw()


    def plot_column(self):
        if not self.column_plot_active or not matplotlib.pyplot.fignum_exists(self.col_fig.number):
            self.column_plot_active = True
            self.col_fig = matplotlib.pyplot.figure()
        else:
            self.col_fig.clf()
        ax = self.col_fig.add_subplot(111)
        A = self.im.get_array()
        line, = ax.plot(A[:,self.lastind[1]])
        ax.set_xlim(0,A.shape[0]-1)
        ax.set_xlabel('vertical coordinate')
        self.col_fig.canvas.mpl_connect('close_event',self.onclose_colplot)
        self.col_fig.canvas.draw()

    def plot_both(self):
        if not self.both_plot_active or not matplotlib.pyplot.fignum_exists(self.line_fig.number):
            self.both_plot_active = True
            self.line_fig = matplotlib.pyplot.figure()
        else:
            self.line_fig.clf()
        ax1 = self.line_fig.add_subplot(211)
        ax2 = self.line_fig.add_subplot(212)
        A = self.im.get_array()
        line1, = ax1.plot(A[:,self.lastind[1]],'r')
        ax1.set_xlim(0,A.shape[0]-1)
        ax1.set_xlabel('vertical coordinate')
        line2, = ax2.plot(A[self.lastind[0],:],'g')
        ax2.set_xlim(0,A.shape[1]-1)
        ax2.set_xlabel('horizontal coordinate')
        matplotlib.pyplot.subplots_adjust(hspace = 0.4)
        self.line_fig.canvas.mpl_connect('close_event',self.onclose_lineplot)
        self.line_fig.canvas.draw()

def showim(data,*args,**kwargs):
    """
    Show an image with a connected DataBrowser to be able to click on pixels to get their value.
    """
    im = matplotlib.pyplot.imshow(data,picker=True,*args,**kwargs)
    b = DataBrowser(im)
    b.connect()
    return b
    #matplotlib.pyplot.show()

def data_browser(fignum = None):
    """
    Convenience function to add a data browser to an existing figure.
    Usage:

        imshow(x)
        data_browser()

    Optional argument:
        fignum: figure number of figure to connect to DataBrowser
    """
    if len(matplotlib.pyplot.get_fignums()) == 0:
        print('no figure open')
        return
    if fignum is None:
        fig = matplotlib.pyplot.gcf()
    else:
        try:
            fig = matplotlib.pyplot.figure(fignum)
        except TypeError:
            print('fignum has to be an integer')
    if not matplotlib.pyplot.fignum_exists(fig.number):
        print('no figure currently open')
        return
    try:
        im = fig.gca().get_images()[0]
    except IndexError:
        print('no image in figure')
        im = None
        return
    b = DataBrowser(im)
    b.connect()
    return b


# dark plot scheme by Andreas Fehringer:

class dark_scheme(object):

    def __init__(self, on = True):
        """
        Turn on dark plot scheme.
        Turn off with dark_scheme(False).
        It is also usable in the with statement (making error handling nicer).
        """
        
        if on and not dark_scheme._is_on:
            dark_scheme._is_on = True

            # set plot style and store standand parameters
            dark_scheme._old_rc = {}
            for k, v in dark_scheme._rc.items():
                dark_scheme._old_rc[k] = mpl.rcParams[k]
                mpl.rcParams[k] = v
        
        else:  self.off()
    

    def off(self):
        # reset plot style
        # (rcdefaults() does not jive with ipython, 
        #  resetting all keys in rcParams also does not work)
        for k, v in dark_scheme._old_rc.items():
            mpl.rcParams[k] = v
        dark_scheme._old_rc = {}
        dark_scheme._is_on = False


    # make it work with the with statement:
    def __enter__(self):  return self
    def __exit__(self, type, value, tb):  self.off()


dark_scheme._is_on = False
dark_scheme._old_rc = {}
dark_scheme._rc = {}
dark_scheme._rc['lines.color']          = \
dark_scheme._rc['text.color']           = \
dark_scheme._rc['patch.edgecolor']      = \
dark_scheme._rc['savefig.edgecolor']    = \
dark_scheme._rc['figure.edgecolor']     = \
dark_scheme._rc['axes.edgecolor']       = \
dark_scheme._rc['axes.labelcolor']      = \
dark_scheme._rc['xtick.color']          = \
dark_scheme._rc['ytick.color']          = \
dark_scheme._rc['grid.color']           = '#cccccc'
dark_scheme._rc['savefig.facecolor']    = \
dark_scheme._rc['figure.facecolor']     = '#333333'
dark_scheme._rc['axes.facecolor']       = '#444444'
dark_scheme._rc['image.cmap']           = 'gray'
dark_scheme._rc['image.interpolation']  = 'nearest'
dark_scheme._rc['patch.facecolor']      = '#000000'
dark_scheme._rc['axes.color_cycle']     = [
#    ( 79, 129, 189),  # blue
#    (155, 187,  89),  # green
#    (192,  80,  77),  # red
#    (128, 100, 162),  # purple
#    ( 75, 172, 198),  # turquoise
#    (247, 150,  70)   # orange
    '4f81bd',  # blue
    '9bbb59',  # green
    'c0504d',  # red
    '8064a2',  # purple
    '4bacc6',  # turquoise
    'f79646'   # orange
]


class Annotate(object):
    '''Class to draw an interactive rectangular selection onto an image in plt.
    Options: Square = True only allows squares instead of rectangles. For further
    usage see the Interactive_square_roi function
    '''
    def __init__(self,square=True, symmetric=False):
        self.ax = plt.gca()
        self.rect = Rectangle((0,0), 1, 1, facecolor='None', edgecolor='green')
        self.y,self.x = plt.gci().get_size()
        self.x0 = None
        self.y0 = None
        self.x1 = None
        self.y1 = None
        self.ax.add_patch(self.rect)
        self.ax.figure.canvas.mpl_connect('button_press_event', self.on_press)
        self.ax.figure.canvas.mpl_connect('button_release_event', self.on_release)
        self.ax.figure.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.is_pressed=False
        self.square=square
        self.symmetric=symmetric
    def on_press(self, event):
      #print 'press'
        self.is_pressed=True
        self.x0 = event.xdata
        self.y0 = event.ydata    
        self.x1 = event.xdata
        self.y1 = event.ydata
        if self.symmetric==True:
            self.rect.set_width(self.x-self.x0*2)     
        else:
            self.rect.set_width(self.x1 - self.x0)
        if self.square==True:
            self.rect.set_height(self.x1 - self.x0)        
        else:
            self.rect.set_height(self.y1 - self.y0)
        self.rect.set_xy((self.x0, self.y0))
        self.rect.set_linestyle('dashed')
        self.ax.figure.canvas.draw()
    def on_motion(self,event):
        if self.is_pressed is False:
            return
        self.x1 = event.xdata
        self.y1 = event.ydata
        if self.symmetric==True:
            self.rect.set_width(self.x-self.x0*2)
        else:
            self.rect.set_width(self.x1 - self.x0)
        if self.square==True:
            self.rect.set_height(self.x1 - self.x0)        
        else:
            self.rect.set_height(self.y1 - self.y0)
        self.rect.set_xy((self.x0, self.y0))
        self.rect.set_linestyle('dashed')
        self.ax.figure.canvas.draw()
    def on_release(self, event):
        self.is_pressed=False
        #print 'release'
        self.x1 = event.xdata
        self.y1 = event.ydata
        if self.symmetric==True:
            self.rect.set_width(self.x-self.x0*2)
        else:
            self.rect.set_width(self.x1 - self.x0)
        if self.square==True:
            self.rect.set_height(self.x1 - self.x0)        
        else:
            self.rect.set_height(self.y1 - self.y0)
        self.rect.set_xy((self.x0, self.y0))
        self.rect.set_linestyle('solid')
        self.ax.figure.canvas.draw()
        #print self.x0,self.x1,self.y0,self.y1
        if self.square==True:
            self.y1=self.y0+(self.x1-self.x0)
            return [self.x0,self.x1,self.y0,self.y1]
        elif self.symmetric==True:
            self.x1=self.x-self.x0
            return [self.x0,self.x1,self.y0,self.y1]
        else:
            return [self.x0,self.x1,self.y0,self.y1]
      
def Interactive_rect_roi(image,show_crop=True,square=True, symmetric=False):
    '''Function to draw a square ROI on a plt plot.
    Click and drag on the figure to define the ROI, press
    Enter to confirm.
    
    Parameters
    ----------
    image : array-like
        The image on which the ROI should be drawn.
    show_crop : boolean, default=True
        If True, the cropped ROI is opened in a new plt figure.
    square : boolean, default = True
        If True, only square-rectangles are allowed, if False
        all rectangles are allowed.
	symmetric : boolean, default=False
		If True, only symmetric-rectangles are allowed, if False
        all rectangles are allowed.
    
    Returns:
    --------
    cropped_image : array-like
        The ROI of the image
    coords : list
        The coordinates of press (index 0) and release (index 1)
        in the order [x0,x1,y0,y1]. Note, that those coordinates
        are in the coordinate system of plt.
        For numpy usage, swap x with y.        
        
    '''
    plt.figure()
    plt.imshow(image,cmap='gray')
    try:
        plt.get_current_fig_manager().window.raise_()
    except:
         print('Sorry, figure could not be raised')
    Selector=Annotate(square,symmetric)
    pause()
    x0,x1,y0,y1=Selector.x0,Selector.x1,Selector.y0,Selector.y1
    if x0>x1:
        (x0,x1)=(x1,x0)
        (y0,y1)=(y1,y0)
    cropped_image=image[y0:y1,x0:x1]
    if show_crop==True:
        plt.figure()
        plt.imshow(cropped_image,cmap='gray')
        try:
            plt.get_current_fig_manager().window.raise_()
        except:
            print('Sorry, figure could not be raised')
        pause()
        plt.close()
    return cropped_image,[x0,x1,y0,y1]
    
def  third_angle_projection(volume, title="", cut_center=(None,None,None), crosshair=True, binning=False):
    """Represent a 3D-Volume in a third angle projection.
    
    Paramteters
    -----------
    volume : 3d-numpy-array
        The 3d volume which shall be represented.
    title : str, Default=""
        Title in plot.
    cut_center : array, Default=(None,None,None)
        The point where all cuts intersect. By default the middle of volume.
    crosshair : bool, Defualt=Ture
        If True show postion of cuting plans.
    binning : int, Default= False
        Reduce the pixels, for presentaion, by the ``binning`` factor (``pixel_x``/``binning``).
        
    Returns
    -------
    cut_center : array-like
        The point where all cuts intersect after dynamical selection.
    f : matplotlib.figure.Figure object
        Figure object for later modification.
    (ax1,ax2,ax3,ax4) : matplotlib.axes.AxesSubplot object
        Axes object for later modification.
    
    Example
    -------
    >>> import pyE17
    >>> import scipy.misc
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> lena = pyE17.utils.rebin(scipy.misc.lena(),scipy.misc.lena().shape[0]/4,scipy.misc.lena().shape[1]/4)
    >>> lena.shape
    >>> volume = np.array([lena for i in range(128)])
    >>> cut_center, figure, axes = third_angle_projection(volume, title="Lena" ,cut_center=(100,50,30), crosshair=True)
    >>> ax1,ax2,ax3,ax4= axes
    >>> ax1.set_title("New title")
    
    .. note::
        3D-array with more than (150x150x150) pixel show bad performence by interactive slicing.
        
    :Author: Daniel Maier
    :Date: 2014-12-15
    """
    def update(val):
        cross_x1 = np.ones_like(volume)
        cross_x2 = np.ones_like(volume)
        cross_x3 = np.ones_like(volume)
        frame_front = int(np.clip(s1frame.val, 0, x1-1))
        frame_side  = int(np.clip(s3frame.val, 0, x2-1))
        frame_plan  = int(np.clip(s2frame.val, 0, x3-1))
        if crosshair:
            cross_thick = (np.ceil(x1/200.),np.ceil(x2/200.),np.ceil(x3/200.))
        else:
            cross_thick = (0.,0.,0.)
        
        cross_x1[:,s3frame.val:s3frame.val+cross_thick[1],:]=0
        cross_x1[:,:,s2frame.val:s2frame.val+cross_thick[2]]=0
        cross_x2[s1frame.val:s1frame.val+cross_thick[0],:,:]=0
        cross_x2[:,:,s2frame.val:s2frame.val+cross_thick[2]]=0
        cross_x3[s1frame.val:s1frame.val+cross_thick[0],:,:]=0
        cross_x3[:,s3frame.val:s3frame.val+cross_thick[1],:]=0
        
        front = (volume*cross_x1)[frame_front,:,:]
        plan  = (volume*cross_x2)[:,frame_side,:]
        side  = (volume*cross_x3)[:,:,frame_plan]
        
        axx1.set_data(np.fliplr(front))
        axx2.set_data(np.rot90(side,3))
        axx3.set_data(np.rot90(plan,2))
        return (frame_front, frame_side, frame_plan)
    
    plt.ion()
    if binning:
        volume = volume[::binning,::binning,::binning]
    x1,x2,x3=volume.shape
    if cut_center[0]==None and cut_center[1]==None and cut_center[2]==None: 
        cut_center = (x1/2, x2/2, x3/2)
    elif cut_center[0]>=0 and cut_center[1]>=0 and cut_center[2]>=0:
        pass
    else:
        print("Wrong cut_center")
    f, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, sharex=True, sharey=True)
    f.suptitle(title)
    
    axx1 = ax1.imshow(np.fliplr(volume[cut_center[0],:,:]))
    ax1.set_title("Front")
    axs1 = pylab.axes([0.13, 0.51, 0.34, 0.02])
    s1frame = pylab.Slider(axs1, '', 0, x1-1, valinit=cut_center[0], closedmin = True, closedmax = True, valfmt = '%d')
    s1frame.on_changed(update)
    
    axx2 = ax2.imshow(np.rot90(volume[:,:,cut_center[2]],3))
    ax2.set_title("Side")
    axs2 = pylab.axes([0.55, 0.51, 0.34, 0.02])
    s2frame = pylab.Slider(axs2, '', 0, x3-1, valinit=cut_center[2], closedmin = True, closedmax = True, valfmt = '%d')
    s2frame.on_changed(update)
    
    axx3 = ax3.imshow(np.rot90(volume[:,cut_center[1],:],2))
    ax3.set_title("Plan")
    axs3 = pylab.axes([0.13, 0.03, 0.34, 0.02])
    s3frame = pylab.Slider(axs3, '', 0, x2-1, valinit=cut_center[1], closedmin = True, closedmax = True, valfmt = '%d')
    s3frame.on_changed(update)
    
    ax4.plot(np.arange(0,x1),np.arange(0,x1),'k--')
    ax4.set_title("Axis of symmetry")
    update(0)
    pause()
    return (np.array(update(0))*binning ,f, (ax1,ax2,ax3,ax4))

    
class Selector(object):
    '''Class to select a image in a subplot.\n Used in ``cut_3d_volume``.
    
    :Author: Daniel Maier
    :Date: 2014-12-15
    '''
    def __init__(self):
        self.ax = plt.gca()
        #self.gci = plt.gci()
        self.gcf= plt.gcf()
        self.subplot=None
        self.ax.figure.canvas.mpl_connect('button_press_event', self.on_press)
        self.ax.figure.canvas.mpl_connect('button_release_event', self.on_release)
        self.is_pressed=False
    def on_press(self, event):
        self.is_pressed=True
        self.subplot= event.inaxes

    def on_release(self, event):
        self.is_pressed=False
        if(self.subplot==self.gcf.get_axes()[0] or self.subplot==self.gcf.get_axes()[1] or self.subplot==self.gcf.get_axes()[2]):#  
            plt.close()
        return self.subplot
 
def cut_3d_volume(array_3d, show_resualt=True, binning=True):
    """Cut a user defined volume out of a body.
    
    User choose a axis in a third angle projection were then a rectangular region can be defined for cutting.
    
    Parameters
    ----------
    array_3d : 3d-numpy-array
        Volume to crop.
    show_resualt : bool, Default=True
        If ``True`` show the cutted volume in a third angle projection.
    binning : bool, Default=True
        If True the number of voxel of ``array_3d`` will be reduced, 'only' for ploting, for a better performance by representation of selection.
    
    Returns
    -------
    cut_3d : 3d-numpy-array
        Cutted volume.
        
    Example
    -------
    >>> import pyE17
    >>> import scipy.misc
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> lena = pyE17.utils.rebin(scipy.misc.lena(),scipy.misc.lena().shape[0]/4,scipy.misc.lena().shape[1]/4)
    >>> lena.shape
    >>> volume = np.array([lena for i in range(128)])
    >>> cut_3d_volume(volume)
    
    :Author: Daniel Maier
    :Date: 2014-12-15
    """
    x,y,z=array_3d.shape
    voxel=x*y*z
    if voxel > 3375000:
        binning = int((voxel/3375000)**(1./3))
    else:
        binning = 1
    cut_center, figure, axes = third_angle_projection(array_3d, title="Choose dynamical cut position, hit retur and click on figure witch to trim (Front, Sied or Flat)", binning=binning)  
    try:
        plt.get_current_fig_manager().window.raise_()
    except:
         print('Sorry, figure could not be raised')
    selector = Selector()
    plt.show(block=True)
    cut = selector.subplot
    
    if(cut== axes[0]):
        coord = Interactive_rect_roi(array_3d[cut_center[0],:,:], square=False, show_crop=False)[1]
        coord=np.round(coord)
        cut_3d=array_3d[:,coord[2]:coord[3],coord[0]:coord[1]]
    elif(cut==axes[1]):
        coord = Interactive_rect_roi(array_3d[:,:,cut_center[2]], square=False, show_crop=False)[1]
        coord=np.round(coord)
        cut_3d=array_3d[coord[2]:coord[3],coord[0]:coord[1],:]
    elif(cut==axes[2]):
        coord = Interactive_rect_roi(array_3d[:,cut_center[1],:], square=False, show_crop=False)[1]
        coord=np.round(coord)
        cut_3d=array_3d[coord[2]:coord[3],:,coord[0]:coord[1]]
    else:
        print("\nWrong imput\n")
        
    plt.close("all") 
    
    if(show_resualt):
        if np.product(cut_3d.shape) > 3375000:
            binning = int((voxel/3375000)**(1./3))
        else:
            binning = 1
        third_angle_projection(cut_3d, title="Trimmed volume", binning=binning)
    plt.close("all") 
    return cut_3d
    



def grayify_cmap(cmap):
    """Return a grayscale version of the colormap"""
    cmap = plt.cm.get_cmap(cmap)
    colors = cmap(np.arange(cmap.N))
    
    # convert RGBA to perceived greyscale luminance
    # cf. http://alienryderflex.com/hsp.html
    RGB_weight = [0.299, 0.587, 0.114]
    luminance = np.sqrt(np.dot(colors[:, :3] ** 2, RGB_weight))
    colors[:, :3] = luminance[:, np.newaxis]
    
    return cmap.from_list(cmap.name + "_grayscale", colors, cmap.N)
 
def colourmap():
    '''A simple function that plots every colourmap together with
    its perceived intensity mapping'''
    fig, axes = plt.subplots(36, 6, figsize=(10, 7))
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1,
                    hspace=0.1, wspace=0.1)

    im = np.outer(np.ones(10), np.arange(100))

    cmaps = [m for m in plt.cm.datad if not m.endswith("_r")]
    cmaps.sort()

    axes = axes.T.ravel()
    for ax in axes:
        ax.axis('off')

    for cmap, color_ax, gray_ax, null_ax in zip(cmaps, axes[1::3], axes[2::3], axes[::3]):
        del null_ax
        color_ax.set_title(cmap, fontsize=10)
        color_ax.imshow(im, cmap=cmap)
        gray_ax.imshow(im, cmap=grayify_cmap(cmap))
