"""
Logging manager
"""

import logging
import logging.config
import logging.handlers

# Basic config
DEFAULT_LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
}
logging.config.dictConfig(DEFAULT_LOGGING)

# Available formatters
default_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
                                      "%d/%m/%Y %H:%M:%S")
extended_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
                                       "%d/%m/%Y %H:%M:%S")
second_extended_formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s():%(lineno)s] [PID:%(process)d TID:%(thread)d] %(message)s",
    "%d/%m/%Y %H:%M:%S")

# Initial configuration
console_handler = logging.StreamHandler()
console_handler.setFormatter(default_formatter)
logging.root.addHandler(console_handler)


# Tell matplotlib to shut up even on debug mode
matplotlib_logger = logging.getLogger('matplotlib')
matplotlib_logger.setLevel(logging.INFO)


def set_level(log_level=logging.INFO):
    """
    Package-wide console logging level
    """
    # Change level
    logging.root.setLevel(log_level)

    # Change console formatter
    if log_level == logging.DEBUG:
        console_handler.setFormatter(extended_formatter)
    elif log_level == 5:
        console_handler.setFormatter(second_extended_formatter)
    else:
        console_handler.setFormatter(default_formatter)
