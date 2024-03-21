from datetime import datetime

def now():
    return str(datetime.today())

def utcnow():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

from .filedict import FileDict
from .datalogger import DataLogger
from .future import Future
from .h5rw import h5read, h5write
from .imstream import FramePublisher, FrameSubscriber
from . import frameconsumer
