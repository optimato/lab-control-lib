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

def level_number(level):
    """
    Logging level as a number, from a number or a name (e.g. 10, '10', 'DEBUG' or 'debug').
    """
    if isinstance(level, int):
        return level
    try:
        return int(level)
    except ValueError:
        pass
    number = logging.getLevelName(str(level).upper())
    if not isinstance(number, int):
        raise ValueError(f'Unknown log level: {level}')
    return number

def short_name(name):
    """
    Logger name as shown in the logs: without the 'lclib.' prefix (e.g. 'excillum.proxy').
    """
    prefix = logger.name + '.'
    return name[len(prefix):] if name.startswith(prefix) else name

class ShortNameFormatter(logging.Formatter):
    """
    Formatter providing %(shortname)s, the logger name without the 'lclib.' prefix.
    """
    def format(self, record):
        record.shortname = short_name(record.name)
        return super().format(record)

# Custom formatter
class DualFormatter(logging.Formatter):
    """
    Use "extented format" if logger level is DEBUG or below.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.default_formatter = ShortNameFormatter("[%(asctime)s] [%(levelname)s] [%(shortname)s] %(message)s",
                                      "%d/%m/%Y %H:%M:%S")
        self.extended_formatter = ShortNameFormatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(shortname)s] [%(funcName)s():%(lineno)s] [PID:%(process)d TID:%(thread)d] %(message)s",
        "%d/%m/%Y %H:%M:%S")

    def format(self, record):
        level = logging.getLogger(record.name).getEffectiveLevel()
        if level <= logging.DEBUG:
            return self.extended_formatter.format(record)
        else:
            return self.default_formatter.format(record)

dual_formatter = DualFormatter()

# Log files always use the extended format: they are mostly read after the fact
extended_formatter = dual_formatter.extended_formatter

class JsonFormatter(logging.Formatter):
    """
    Format a record as JSON encoded.
    """
    def format(self, record):
        keys = ['created',
                'filename',
                'funcName',
                'levelname',
                'levelno',
                'lineno',
                'module',
                'msecs',
                'name',
                'pathname',
                'process',
                'processName',
                'relativeCreated',
                'thread',
                'threadName']

        d = {k: getattr(record, k, None) for k in keys}

        # Computed here rather than relying on another handler having formatted the record
        d['message'] = record.getMessage()
        d['msg'] = str(record.msg)
        d['exc_text'] = self.formatException(record.exc_info) if record.exc_info else None
        return json.dumps(d, default=str)

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
        try:
            msg = self.format(record)
            with self._access_lock:
                self.log_buffer.append(msg)
        except Exception:
            self.handleError(record)

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

# Same for uncaught exceptions in threads (otherwise only printed on stderr)
def log_uncaught_thread_exceptions(args):
    if issubclass(args.exc_type, SystemExit):
        return
    thread_name = args.thread.name if args.thread is not None else 'unknown'
    logger.error(f"Uncaught exception in thread {thread_name}",
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
threading.excepthook = log_uncaught_thread_exceptions

# Function to implement file logging
def log_to_file(log_file_name, logobj=None, level=logging.DEBUG, max_bytes=1024 * 1024 * 10, backup_count=300):
    """
    Set up file logging with rotation.
    Parameters:
    -----------
    log_file_name (str): The name of the log file.
    logobj (logging.Logger, optional): The logger object to which the handler should be added. If None, the root logger is used.
    level (int): The logging level for the file handler.
    max_bytes (int): Size of a log file before rotation.
    backup_count (int): Number of rotated log files to keep.
    """
    file_handler = logging.handlers.RotatingFileHandler(log_file_name, maxBytes=max_bytes, backupCount=backup_count,
                                                        encoding='utf-8')
    file_handler.setFormatter(extended_formatter)
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

# Function to collect what is logged outside lclib
def log_other_loggers(package=None, level=logging.INFO):
    """
    Send to the lclib handlers (console, file, memory) what is logged outside lclib: warnings
    and errors of all modules (lab package, libraries), and the messages of `package` (e.g.
    the lab package) from `level`. Call after the lclib handlers are set up.
    Parameters:
    -----------
    package (str, optional): name of a package whose messages are kept from `level`.
    level (int): The logging level for the messages of `package`.
    """
    root = logging.getLogger()
    for handler in logger.handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(logging.WARNING)
    if package:
        logging.getLogger(package).setLevel(level)

# Context manager to mute logging
class logging_muted:
    def __enter__(self):
        logging.disable(logging.CRITICAL)

    def __exit__(self, exit_type, exit_value, exit_traceback):
        logging.disable(logging.NOTSET)

# Tell matplotlib to shut up even on debug mode
matplotlib_logger = logging.getLogger('matplotlib')
matplotlib_logger.setLevel(logging.INFO)
