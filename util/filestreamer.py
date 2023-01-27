from .filewriter import FileWriter


class FileStreamer(FileWriter):
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
        self.FramePublisher = None

    def process_init(self):
        """
        Import is needed only here.
        """
        from .imstream import FramePublisher
        self.FramePublisher = FramePublisher

    def write(self, filename, meta, data):
        """
        We don't write the data but instead send it!
        """
        if self.broadcaster:
            self.broadcaster.pub(data, meta)

    def _on(self):
        """
        Turn on broadcasting (in process)
        """
        self.logger.debug('(sub) Creating FramePublisher for broadcast')
        if self.broadcaster:
            return
        self.broadcaster = self.FramePublisher(port=self.broadcast_port)


    def on(self):
        """
        Turn on broadcasting (from main process)
        """
        self.exec('_on')

    def _off(self):
        """
        Stop broadcasting (in process)
        """
        self.logger.debug('(sub) Deleting FramePublisher.')
        if not self.broadcaster:
            return
        try:
            self.broadcaster.close()
        except BaseException:
            pass
        self.broadcaster = None

    def off(self):
        """
        Turn off broadcasting (from main process)
        """
        self.exec('_off')
