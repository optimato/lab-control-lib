"""
Logging manager

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import logging
import logging.config
import logging.handlers
import zmq
import json
import threading
import time
import datetime

from .util import Future

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
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] [%(funcName)s():%(lineno)s] [PID:%(process)d TID:%(thread)d] %(message)s",
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


def log_to_file(log_file_name):
    # File logging
    file_handler = logging.handlers.RotatingFileHandler(log_file_name, maxBytes=1024 * 1024 * 10, backupCount=300,
                                                        encoding='utf-8')
    file_handler.setFormatter(dual_formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

# Tell matplotlib to shut up even on debug mode
matplotlib_logger = logging.getLogger('matplotlib')
matplotlib_logger.setLevel(logging.INFO)


class logging_muted:
    def __enter__(self):
        logging.disable(logging.CRITICAL)

    def __exit__(self, exit_type, exit_value, exit_traceback):
        logging.disable(logging.NOTSET)
