"""
Tests of the logging setup (lclib/logs.py) and of the logger names used in lclib.
"""
from lclib import logs


def test_short_name():
    assert logs.short_name('lclib.excillum.proxy') == 'excillum.proxy'
    assert logs.short_name('lclib') == 'lclib'
    assert logs.short_name('labcontrol.pco') == 'labcontrol.pco'
    assert logs.short_name('lclibrary.x') == 'lclibrary.x'

def test_motor_logger(tmp_path, monkeypatch):
    from lclib import base
    monkeypatch.setattr(base, 'get_config', lambda: {'conf_path': str(tmp_path)})

    class Motor(base.MotorBase):
        pass

    assert Motor('sx', driver=None).logger.name == 'lclib.motor.sx'

def test_util_loggers():
    from lclib.util import h5rw, imstream
    assert h5rw.logger.name == 'lclib.h5rw'
    assert imstream.rootlogger is logs.logger
