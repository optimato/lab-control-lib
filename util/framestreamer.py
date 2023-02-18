from threading import Event
from queue import Empty

from .frameconsumer import FrameConsumerProcess
from .future import Future

class FrameStreamer(FrameConsumerProcess):
    """
    A worker class to stream frames
    """
    def __init__(self, broadcast_port):
        """
        Frame publisher working on a separate process.
        """
        super().__init__()
        self.broadcast_port = broadcast_port
        self.broadcaster = None
        self.broadcast_future = None
        self.FramePublisher = None

    def process_init(self):
        """
        [subprocess]
        Attributes that need to be assigned in the sub-process.
        """
        from .imstream import FramePublisher
        self.FramePublisher = FramePublisher
        self.off_flag = Event()

    def _set_log_level(self, level):
        """
        [subprocess]
        """
        super()._set_log_level(level)
        if self.broadcaster:
            self.broadcaster.logger.setLevel(level)

    def _on(self):
        """
        [subprocess]
        Turn on broadcasting
        """
        if self.broadcast_future and not self.broadcast_future.done():
            return {'status': 'error', 'msg': 'Already broadcasting'}

        self.broadcast_future = Future(self._worker)
        return {'status': 'ok'}

    def _worker(self):
        """
        [subprocess]
        Worker started by self._on that publishes frames until notified to stop.
        """
        self.logger.debug('(sub) Creating FramePublisher for broadcast')
        if self.broadcaster:
            return
        self.broadcaster = self.FramePublisher(port=self.broadcast_port)

        # self.msg_flag is set but the "_open" call, so we need to ignore this first flip.
        if not self.msg_flag.wait(5):
            return {'status': 'error', 'msg': 'Something went wrong when starting _worker'}
        self.msg_flag.clear()

        while True:
            # Wait for commands from main process.
            if not self.msg_flag.wait(.5):
                if self.stop_flag.is_set():
                    break
                continue

            self.msg_flag.clear()

            # Do we need to wrap up?
            if self.off_flag.is_set():
                break

            # Otherwise we are being notified because a new frame is in the queue
            try:
                item = self.queue.get(timeout=.01)
            except Empty:
                continue

            data, meta, receive_time = item

            if self.broadcaster:
                self.logger.debug('Publishing new frame')
                self.broadcaster.pub(data, meta)
                self.logger.debug('Done publishing new frame')

        self.logger.debug('(sub) Deleting FramePublisher.')
        try:
            self.broadcaster.close()
        except:
            pass
        self.broadcaster = None
        return {'status': 'ok'}

    def on(self):
        """
        [main process]
        Turn on broadcasting (from main process)
        """
        self.exec('_on')

    def _off(self):
        """
        [subprocess]
        Stop broadcasting
        """
        self.off_flag.set()

    def off(self):
        """
        [main process]
        Turn off broadcasting
        """
        self.exec('_off')
