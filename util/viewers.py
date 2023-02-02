
import threading

import napari
from napari.qt.threading import create_worker
import numpy as np
import time
import logging

from .imstream import FrameSubscriber
from .logs import logger as rootlogger
from .guitools import LiveView

class ViewerBase:

    DEFAULT_ADDRESS = ('localhost', 5555)

    def __init__(self, address=None, compress=False, max_fps=25, yield_timeout=15):
        """
        Base class for frame viewers. This class contains a FrameSubscriber that connects to a FramePublisher.
        The method yield_new_frame is a generator that can be iterated over.

        address: tuple (ip, port) of the FramePublisher
        compress: whether to use JPG compressed images (not a good idea for now)
        max_fps: maximum FPS: Skip frames if they are incoming at a higher rate.
        yield_timeout: time in seconds after which the generator will stop yielding and return.
                       If None: never times out.
        """
        self.compress = compress
        self.max_fps = max_fps
        self.yield_timeout = yield_timeout

        self.logger = rootlogger.getChild(self.__class__.__name__)

        # Start with no frame source
        self.frame_subscriber = None

        if address is None:
            self.address = self.DEFAULT_ADDRESS
        else:
            self.address = address

        self._stop_yielding = False
        self.prepare_viewer()

    def prepare_viewer(self):
        """
        Backend-dependent viewer initialization
        """
        pass

    def manage_new_frame(self, frame_and_meta):
        """
        Show the frame. metadata is any metadata sent along with the frame.
        """
        return frame_and_meta

    def start_viewer(self):
        pass

    def stop_viewer(self):
        pass

    def yield_new_frame(self):
        """
        Generator that yields a new frame at a maximum rate of self.max_fps
        If yield_timeout is reached, yield None.
        """
        twait = 1. / self.max_fps
        t0 = time.time()
        while True:
            try:
                frame, metadata = self.frame_subscriber.receive(1)
            except TimeoutError:
                if self.yield_timeout and self.yield_timeout < time.time() - t0:
                    self.logger.info('Timed out.')
                    yield
                    continue
                elif self._stop_yielding:
                    self.logger.info('Exiting frame yielding loop.')
                    return
                else:
                    continue
            except AttributeError:
                return
            if self.compress:
                frame = self.uncompress(frame)
            yield frame, metadata
            time.sleep(twait)
            t0 = time.time()

    def start(self):
        """
        Initialize a subscriber to the frame source and start the viewer.
        """
        self.frame_subscriber = FrameSubscriber(address=self.address)
        self._stop_yielding = False
        self.start_viewer()

    def stop(self):
        """
        Stop the subscriber and stop the viewer
        """
        self._stop_yielding = True
        self.stop_viewer()
        self.frame_subscriber.close()
        self.frame_subscriber = None

    def once(self, timeout=15):
        """
        Grab a single frame, waiting for maximum time timeout.
        """
        if self.frame_subscriber is not None:
            self.manage_new_frame(next(self.yield_new_frame()))
        else:
            with FrameSubscriber(address=self.address, frames=not self.compress) as f:
                frame, metadata = f.receive(timeout=timeout)
            self.manage_new_frame((frame, metadata))

    @staticmethod
    def uncompress(buffer):
        import cv2
        return cv2.imdecode(np.frombuffer(buffer, dtype='uint8'), -1)


class NapariViewer(ViewerBase):

    MAX_BUFFER_SIZE = 50
    LIVEVIEW_LABEL = 'Live View'

    def __init__(self, address=None, compress=False, max_fps=25, yield_timeout=2):
        self.v = None
        self.worker = None
        self.epsize = None
        self.buffer_size = 1
        super().__init__(address=address, compress=compress, max_fps=max_fps, yield_timeout=yield_timeout)

    def prepare_viewer(self):
        """
        Create the viewer and prepare the dock
        """
        self.v = napari.viewer.Viewer()

        # Napari thread worker
        self.worker = create_worker(self.yield_new_frame)

        # This will update the GUI each time the function yields
        self.worker.yielded.connect(self.manage_new_frame)

        self.live_view = LiveView(self)
        self.live_view.liveModePause.connect(self.worker.pause)
        self.live_view.liveModePlay.connect(self.worker.resume)
        self.live_view.bufferSizeChange.connect(self.set_buffer_size)

        self.v.window.add_dock_widget(self.live_view, area='right')

    def start_viewer(self):
        """
        Not sure things are split the right way.
        """
        self.worker.start()
        napari.run()

    def stop_viewer(self):
        self.worker.quit()

    def manage_new_frame(self, frame_and_meta):
        """
        Update the viewer and scale bar. This could be overridden for detector-specific
        viewers.
        """
        if frame_and_meta is None:
            return

        self.live_view.is_alive()
        frame, metadata = frame_and_meta
        if frame is None:
            return
        self.logger.debug('New frame received.')
        epsize = None
        for v in metadata.values():
            epsize = v.get('epsize')
            if epsize:
                self.logger.debug('Effective pixel size: {epsize:0.2} μm')
                break
        self.update_layer(frame, metadata)
        self.update_scalebar(epsize)

    def update_layer(self, frame, metadata):
        """
        Update the data in the live view layer.

        Not so simple because of (1) managing the ring buffer and
        (2) the possibility that frame is already an image stack.
        """
        try:
            current_buffer = self.v.layers[self.LIVEVIEW_LABEL].data
        except KeyError:
            # First time.
            if frame.ndim == 2:
                frame = frame[np.newaxis, :]
            bs = frame.shape[0]
            self.set_buffer_size(bs)
            self.v.add_image(frame, name=self.LIVEVIEW_LABEL)
            return

        if frame.ndim == 2 or frame.shape[0] == 1:
            new_buffer = np.roll(current_buffer, 1, axis=0)
            new_buffer[0] = frame
        else:
            # Dealing with 3d incoming frame.
            N = len(frame)
            if N == self._buffer_size:
                # Same size: replace
                new_buffer = frame
            if N > self._buffer_size:
                # Larger than current buffer: enlarge it first
                self.set_buffer_size(N)
                new_buffer = frame
            else:
                # Smaller than current buffer: prepend
                new_buffer = np.roll(current_buffer, N, axis=0)
                new_buffer[:N] = frame
        self.v.layers[self.LIVEVIEW_LABEL].data = new_buffer
        self.v.layers[self.LIVEVIEW_LABEL].refresh()
        return

    def set_buffer_size(self, size: int):
        size = np.clip(size, 1, self.MAX_BUFFER_SIZE)
        self._buffer_size = size
        self.live_view.update_buffer_size(size)
        self.update_buffer()

    def update_buffer(self):
        """
        Reshape the napari buffer
        """
        bs = self._buffer_size
        try:
            current_buffer = self.v.layers[self.LIVEVIEW_LABEL].data
        except KeyError:
            # No buffer yet, we can't do much
            return
        sh = current_buffer.shape

        if len(sh) == 2:
            # Current buffer is 2D
            if bs == 1:
                # Buffer size is 1 -> nothing to do
                return
            else:
                # New buffer
                new_buffer = np.zeros_like(current_buffer, shape=(bs,) + sh)
                new_buffer[0] = current_buffer
        elif sh[0] == bs:
            # Current buffer has the right size -> nothing to do
            return
        elif sh[0] < bs:
            # Current buffer is smaller -> expand
            new_buffer = np.zeros_like(current_buffer, shape=(bs,) + sh[1:])
            new_buffer[:sh[0]] = current_buffer
        else:
            # Current buffer is larger -> cut
            new_buffer = current_buffer[:bs].copy()

        # Replace buffer
        self.v.layers[self.LIVEVIEW_LABEL].data = new_buffer
        self.v.layers[self.LIVEVIEW_LABEL].refresh()

    def update_scalebar(self, epsize):
        """
        Update or add scale bar if needed.
        """
        if epsize == self.epsize:
            return
        self.epsize = epsize
        self.v.layers[self.LIVEVIEW_LABEL].scale = [self.epsize, self.epsize]
        self.v.scale_bar.visible = True
        self.v.scale_bar.unit = 'um'
        self.v.reset_view()

    def data_received(self):
        """
        Notification that the connection is alive.
        """
        pass

class CvViewer(ViewerBase):

    def __init__(self, address=None, compress=False, max_fps=25, yield_timeout=None):
        import cv2
        self.cv2 = cv2
        self.thread = None
        self._stop = False
        super().__init__(address=address, compress=compress, max_fps=max_fps, yield_timeout=yield_timeout)

    def prepare_viewer(self):
        self.thread = threading.Thread(target=self._imshow, daemon=True)

    def start_viewer(self):
        self.thread.start()

    def stop_viewer(self):
        self._stop = True

    def _imshow(self):
        for frame_and_meta in self.yield_new_frame():
            self.manage_new_frame(frame_and_meta)
            if self._stop:
                break

    def manage_new_frame(self, frame_and_meta):
        """
        Show the frame.
        """
        if frame_and_meta is None:
            return
        frame, metadata = frame_and_meta
        if frame is None:
            return
        title = 'Live View'
        if detector_name := metadata.get('detector'):
            title = ' - '.join([title, detector_name])
        self.cv2.imshow(title, frame)
        self.cv2.waitKey(1)

if __name__ == "__main__":
    v = NapariViewer()
    v.start()
