
import threading

import napari
from napari.qt.threading import create_worker
from qtpy.QtWidgets import QPushButton
import numpy as np
import time
import logging

from .imstream import FrameSubscriber


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

        self.logger = logging.getLogger(self.__class__.__name__)

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
        pass

    def start_viewer(self):
        pass

    def stop_viewer(self):
        pass

    def yield_new_frame(self):
        """
        Generator that yields a new frame at a maximum rate of self.max_fps
        """
        twait = 1. / self.max_fps
        t0 = time.time()
        while True:
            try:
                frame, metadata = self.frame_subscriber.receive(1)
            except TimeoutError:
                if self.yield_timeout and self.yield_timeout < time.time() - t0:
                    self.logger.info('Timed out.')
                    return
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
        self.frame_subscriber = FrameSubscriber(address=self.address, frames=not self.compress)
        self._stop_yielding = False
        self.start_viewer()
        print('here')

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

    def __init__(self, address=None, compress=False, max_fps=25, yield_timeout=None):
        self.v = None
        self.worker = None
        self.epsize = None
        super().__init__(address=address, compress=compress, max_fps=max_fps, yield_timeout=yield_timeout)

    def prepare_viewer(self):
        pass

    def start_viewer(self):
        # find viewer from some list of instances (TODO), create new one if inexistent.
        self.v = napari.viewer.Viewer()

        # Napari thread worker
        self.worker = create_worker(self.yield_new_frame)

        # This will update the GUI each time the function yields
        self.worker.yielded.connect(self.manage_new_frame)

        # Create toggle start/pause button TODO: change all this.
        """
        button = QPushButton("Pause")
        button.clicked.connect(self.worker.toggle_pause)
        self.worker.finished.connect(button.clicked.disconnect)

        
        # Add to napari viewer
        self.v.window.add_dock_widget(button, area='right')
        """
        from magicgui import magicgui

        @magicgui(call_button="Pause")
        def pause():
            self.worker.toggle_pause()
        print(5)

        """
        @magicgui(
            call_button="Calculate",
            slider_float={"widget_type": "FloatSlider", 'max': 10},
            dropdown={"choices": ['first', 'second', 'third']},
        )
        def widget_demo(
                maybe: bool,
                some_int: int,
                spin_float=3.14159,
                slider_float=4.5,
                string="Text goes here",
                dropdown='first',
        ):
            pass
        """
        self.v.window.add_dock_widget(pause, area='right')

        self.worker.start()
        napari.run()

    def stop_viewer(self):
        self.worker.quit()

    def manage_new_frame(self, frame_and_meta):
        """
        Update the viewer and scale bar. This could be overridden for detector-specific
        viewers.
        """
        frame, metadata = frame_and_meta
        epsize = None
        for v in metadata.values():
            epsize = v.get('epsize')
            if epsize:
                break
        self.update_layer(frame, metadata)
        self.update_scalebar(epsize)

    def update_layer(self, frame, metadata):
        """
        Update the data in the live view layer.
        """
        try:
            self.v.layers['Live View'].data = frame
        except KeyError:
            # First time.
            self.v.add_image(frame, name='Live View')

    def update_scalebar(self, epsize):
        """
        Update or add scale bar if needed.
        """
        if epsize == self.epsize:
            return
        self.epsize = epsize
        self.v.layers['Live View'].scale = [self.epsize, self.epsize]
        self.v.scale_bar.visible = True
        self.v.scale_bar.unit = 'um'
        self.v.reset_view()


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
        frame, metadata = frame_and_meta
        title = 'Live View'
        if detector_name := metadata.get('detector'):
            title = ' - '.join([title, detector_name])
        self.cv2.imshow(title, frame)
        self.cv2.waitKey(1)

if __name__ == "__main__":
    v = NapariViewer()
    v.start()
