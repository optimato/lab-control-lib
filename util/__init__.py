from datetime import datetime

from .filedict import FileDict
#from .fake_device import FakeDevice
from .imstream import FramePublisher, FrameSubscriber
#from .filewriter import H5FileWriter
#from . import viewers


def now():
    return str(datetime.today())


def utcnow():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
