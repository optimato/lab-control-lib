"""
Utilities for labcontrol

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
from datetime import datetime

from . import uitools
from .filedict import FileDict
#from .fake_device import FakeDevice
from .imstream import FramePublisher, FrameSubscriber
from . import frameconsumer
#from .filewriter import H5FileWriter
#from . import viewers


def now():
    return str(datetime.today())


def utcnow():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
