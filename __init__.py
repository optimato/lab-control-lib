"""
OptImaTo control package
"""
import logging
import optimatools as opt
from . import util
from ._version import version

# Package-wide default log level (this sets up console handler)
util.logs.set_level(logging.INFO)

# logging.getLogger().info('XNIG verion %s' % version)
# Subpackages have to be imported explicitly for now
