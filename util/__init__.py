from . import logs
from .filedict import FileDict

# Silently fail if mqtt libraries are not present
try:
    from . import mqttlib
except ImportError:
    class PlaceHolder(object):
        def __getattribute__(self, item):
            raise RuntimeError("Paho libraries are not installed.")
    mqttlib = PlaceHolder()
