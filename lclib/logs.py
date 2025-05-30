"""
Logging manager

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import logging
import logging.config
import logging.handlers
import sys
import json
import collections
import threading

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

# This is overwritten by init()
log_dir = None

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
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] [%(funcName)s():%(lineno)s] [PID:%(process)d TID:%(thread)d] %(message)s",
        "%d/%m/%Y %H:%M:%S")

    def format(self, record):
        level = logging.getLogger(record.name).getEffectiveLevel()
        if level <= logging.DEBUG:
            return self.extended_formatter.format(record)
        else:
            return self.default_formatter.format(record)

dual_formatter = DualFormatter()

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

json_formatter = JsonFormatter()

class InMemoryLogHandler(logging.Handler):
    def __init__(self, capacity=1000):
        """
        A logging handler that stores log messages in memory.
        Parameters:
        -----------
        capacity (int): Maximum number of log messages to store.
        """
        super().__init__()
        self.log_buffer = collections.deque(maxlen=capacity)
        self._access_lock = threading.Lock()
        self.setFormatter(json_formatter)

    def emit(self, record):
        msg = self.format(record)
        with self._access_lock:
            self.log_buffer.append(msg)

    def get_logs(self, last_n=None, since=None):
        """
        Retrieve the last `last_n` log messages as a list.
        Parameters:
        -----------
        last_n (int): If specified, return only the last `last_n` messages.
        since (float): If specified, return messages logged after this timestamp.
        """
        try:
            with self._access_lock:
                logs = [json.loads(log) for log in self.log_buffer]
        except json.JSONDecodeError:
            # If JSON decoding fails, return an empty list
            return []
        
        if since is not None:
            logs = [log for log in logs if log['created'] > since]

        if last_n is not None:
            logs = logs[-last_n:]

        return logs

# Console logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(dual_formatter)
logger.addHandler(console_handler)

# Manage uncaught exceptions
def log_uncaught_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Let KeyboardInterrupt exit silently
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
sys.excepthook = log_uncaught_exceptions

# Function to implement file logging
def log_to_file(log_file_name, logobj=None, level=logging.DEBUG):
    """
    Set up file logging with rotation.
    Parameters:
    -----------
    log_file_name (str): The name of the log file.
    logobj (logging.Logger, optional): The logger object to which the handler should be added. If None, the root logger is used.
    level (int): The logging level for the file handler.
    """
    file_handler = logging.handlers.RotatingFileHandler(log_file_name, maxBytes=1024 * 1024 * 10, backupCount=300,
                                                        encoding='utf-8')
    file_handler.setFormatter(dual_formatter)
    file_handler.setLevel(level)
    logobj = logobj or logger
    logobj.addHandler(file_handler)

# Function to implement memory logging
def log_to_mem(logobj=None, level=logging.DEBUG):
    """
    Set up in-memory logging.
    Parameters:
    -----------
    logobj (logging.Logger, optional): The logger object to which the handler should be added. If None, the root logger is used.
    level (int): The logging level for the in-memory handler.
    """
    mem_handler = InMemoryLogHandler()
    mem_handler.setLevel(level)
    logobj = logobj or logger
    logobj.addHandler(mem_handler)
    logobj.in_memory_handler = mem_handler

# Context manager to mute logging
class logging_muted:
    def __enter__(self):
        logging.disable(logging.CRITICAL)

    def __exit__(self, exit_type, exit_value, exit_traceback):
        logging.disable(logging.NOTSET)

# Tell matplotlib to shut up even on debug mode
matplotlib_logger = logging.getLogger('matplotlib')
matplotlib_logger.setLevel(logging.INFO)
