"""
Logging manager
"""

import logging
import logging.config
import logging.handlers
import json
from contextlib import contextmanager

from .. import LOG_FILE

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
                'threadName']

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
