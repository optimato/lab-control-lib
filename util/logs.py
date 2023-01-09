"""
Logging manager
"""

import logging
import logging.config
import logging.handlers
import zmq
import json
from contextlib import contextmanager
import threading
import time
import datetime

from .. import LOG_FILE
from .future import Future


# This adds another debug level but it is not well managed by
# zmq.logs.PubHandler so for now not used.
"""
VERBOSE_NUM = 5
logging.addLevelName(VERBOSE_NUM, "VERBOSE")
def verbose(self, message, *args, **kws):
    if self.isEnabledFor(VERBOSE_NUM):
        # Yes, logger takes its '*args' as 'args'.
        self._log(VERBOSE_NUM, message, args, **kws)
logging.Logger.verbose = verbose
"""
# Basic config
DEFAULT_LOGGING = {
    'version': 1,
    'disable_existing_loggers': False
}

logging.config.dictConfig(DEFAULT_LOGGING)

# Create root logger
logger = logging.getLogger(__package__.split('.')[0])

# Do not reach root handler
logger.propagate = False

# Custom formatter
class DualFormatter(logging.Formatter):
    """
    Use "extented format" if logger level is DEBUG or below.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.default_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
                                      "%d/%m/%Y %H:%M:%S")
        self.extended_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s():%(lineno)s] [PID:%(process)d TID:%(thread)d] %(message)s",
        "%d/%m/%Y %H:%M:%S")

    def format(self, record):
        level = logging.getLogger(record.name).getEffectiveLevel()
        if level <= logging.DEBUG:
            return self.extended_formatter.format(record)
        else:
            return self.default_formatter.format(record)

class JsonFormatter(logging.Formatter):
    """
    Format a record as JSON encoded.
    """
    def format(self, record):
        keys = ['created',
                'exc_text',
                'filename',
                'funcName',
                'levelname',
                'levelno',
                'lineno',
                'message',
                'module',
                'msecs',
                'name',
                'pathname',
                'process',
                'processName',
                'relativeCreated',
                'thread',
                'threadName',
                'msg']

        d = {k: getattr(record, k, None) for k in keys}
        return json.dumps(d)

dual_formatter = DualFormatter()
json_formatter = JsonFormatter()

# Console logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(dual_formatter)
logger.addHandler(console_handler)

# File logging
file_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1024 * 1024 * 10, backupCount=300,
                                                    encoding='utf-8')
file_handler.setFormatter(dual_formatter)
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# Tell matplotlib to shut up even on debug mode
matplotlib_logger = logging.getLogger('matplotlib')
matplotlib_logger.setLevel(logging.INFO)

@contextmanager
def logging_muted(highest_level=logging.CRITICAL):
    """
    A context manager that will prevent any logging messages
    triggered during the body from being processed.
    :param highest_level: the maximum logging level in use.
      This would only need to be changed if a custom level greater than CRITICAL
      is defined.

    (adapted from: https://gist.github.com/simon-weber/7853144)
    """
    previous_level = logging.root.manager.disable

    logging.disable(highest_level)

    try:
        yield
    finally:
        logging.disable(previous_level)


class LogClient:

    def __init__(self, address):
        """
        Subscriber to a PubHandler Logger. Messages are assumed to be json formatted.
        """
        ip, port = address
        self.address = f'tcp://{ip}:{port}'

        # Stats to evaluate the rate of dropped frames
        self.num_frames = 0
        self.num_frames_dropped = 0
        self.num_frames_dropped_sequence = 0

        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.SUB)
        self.zmq_socket.setsockopt(zmq.SUBSCRIBE, b'')
        self.zmq_socket.connect(self.address)

        self._stop = False
        self._data_ready = threading.Event()
        self.recv_future = Future(self._run)

    def _run(self):
        """
        Start receiving on a separate thread to avoid data backlogs
        """
        while not self._stop:
            if (self.zmq_socket.poll(50.) & zmq.POLLIN) == 0:
                continue
            self._data = self._recv()
            self._data_ready.set()

    def _recv(self):
        """
        Receive message
        """
        name, json_data = self.zmq_socket.recv_multipart()
        data = json.loads(json_data)
        return data

    def receive(self, timeout=0.):
        """
        Receive log message. Return None if timed out.
        """
        flag = self._data_ready.wait(timeout=timeout)
        if not flag:
            return None
        self._data_ready.clear()
        return self._data

    def close(self):
        """
        Close socket and stop receiving thread.
        """
        self._stop = True
        self.recv_future.join()
        self.zmq_socket.close()
        self.zmq_context.term()


class DisplayLogger:

    def __init__(self):
        """
        Connect to given addresses to print out logs.
        """
        self.log_clients = {}

    def sub(self, name, address):
        """
        Add or replace Log client.
        """
        if cl := self.log_clients.get(name, None):
            cl.close()

        cl = LogClient(address)
        self.log_clients[name] = cl

    @staticmethod
    def _show(data):
        """
        TODO: implement custom highlights.
        """
        #print('[{name}] - {levelname} - {msg}'.format(**data))
        if data['levelno'] >= 40:
            L = _cE('E')
        elif data['levelno'] >= 30:
            L = _cW('W')
        else:
            L = data['levelname'][0]

        T = str(datetime.datetime.utcfromtimestamp(data['created']))
        N = data['name'].split('.', 1)[1]
        M = data['msg']
        print(f'[{L}] {T} - {" " + N + " ":-^30s} - {M}')


    def show(self):
        try:
            while True:
                for name, cl in self.log_clients.items():
                    if data := cl.receive():
                        self._show(data)
                # temporize slightly
                time.sleep(.05)
        except KeyboardInterrupt:
            # We are done.
            return
def _cE(s):
    """
    Formatting for ERROR
    """
    return f"\x1b[1;4;31;40m{s}\x1b[0m"

def _cW(s):
    """
    Formatting for WARNING
    """
    return f"\x1b[1;33;40m{s}\x1b[0m"

def _cU(s):
    """
    Formatting for underline
    """
    return f"\x1b[4m{s}\x1b[0m"
