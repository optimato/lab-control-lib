"""
Tests of the logging setup (lclib/logs.py) and of the logger names used in lclib.
"""
import datetime

import pytest

from lclib import logs


def _time(text):
    return datetime.datetime.strptime(text, '%d/%m/%Y %H:%M:%S').timestamp()


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

def test_parse_log_lines():
    lines = ['*** banner ***',
             '[27/10/2026 12:00:01.250] [INFO] [excillum] [init():12] [PID:1 TID:2] Device initialized',
             '[27/10/2026 12:00:02.500] [ERROR] [excillum.proxy] [f():3] [PID:1 TID:2] Call to x failed',
             'Traceback (most recent call last):',
             '  File "x.py", line 1, in f',
             'ValueError: wrong',
             '[27/10/2026 12:00:03] [WARNING] [labcontrol.pco] console format, without ms']
    entries = logs.parse_log_lines(lines)
    assert [e.level for e in entries] == [None, 'INFO', 'ERROR', 'WARNING']
    assert [e.name for e in entries] == [None, 'excillum', 'excillum.proxy', 'labcontrol.pco']
    assert [e.message for e in entries] == ['*** banner ***', 'Device initialized', 'Call to x failed',
                                            'console format, without ms']

    # Lines before the first timestamp: an entry without time
    assert entries[0].time is None
    assert entries[0].lines == ['*** banner ***']

    # Times with and without milliseconds
    assert entries[1].time == pytest.approx(_time('27/10/2026 12:00:01') + .25)
    assert entries[3].time == _time('27/10/2026 12:00:03')

    # The traceback belongs to the error
    assert len(entries[2].lines) == 4
    assert entries[2].lines[-1] == 'ValueError: wrong'

    assert logs.parse_log_lines([]) == []

def test_parse_old_logger_names():
    # Log files written before the logger names changed
    line = '[01/10/2026 08:00:00] [INFO] [lclib.ExcillumProxyServer] Client 12 disconnected'
    assert logs.parse_log_lines([line])[0].name == 'lclib.ExcillumProxyServer'

def test_merge_log_entries():
    a = logs.parse_log_lines(['[27/10/2026 12:00:01] [INFO] [a] first of a',
                              'continuation of a',
                              '[27/10/2026 12:00:03] [INFO] [a] second of a'])
    b = logs.parse_log_lines(['banner of b',
                              '[27/10/2026 12:00:02] [INFO] [b] first of b',
                              '[27/10/2026 12:00:04] [INFO] [b] second of b'])
    merged = logs.merge_log_entries({'a': a, 'b': b})

    assert [(source, entry.lines[0]) for source, entry in merged] == [
        ('a', '[27/10/2026 12:00:01] [INFO] [a] first of a'),
        ('b', 'banner of b'),
        ('b', '[27/10/2026 12:00:02] [INFO] [b] first of b'),
        ('a', '[27/10/2026 12:00:03] [INFO] [a] second of a'),
        ('b', '[27/10/2026 12:00:04] [INFO] [b] second of b')]
    # Continuation lines stay with their entry
    assert merged[0][1].lines[1] == 'continuation of a'

def test_log_follower():
    def read(*lines):
        return logs.parse_log_lines(lines)

    follower = logs.LogFollower()
    first = read('[27/10/2026 12:00:01] [INFO] [a] one',
                 '[27/10/2026 12:00:02] [ERROR] [a] two',
                 'Traceback (most recent call last):')

    # First read: everything is new
    added, new, complete = follower.new_entries('a', first)
    assert added is None and new == first and complete

    # Same window plus new entries: only the new ones. The traceback being written when
    # read the first time has more lines now.
    second = read('[27/10/2026 12:00:02] [ERROR] [a] two',
                  'Traceback (most recent call last):',
                  'ValueError: wrong',
                  '[27/10/2026 12:00:03] [INFO] [a] three')
    added, new, complete = follower.new_entries('a', second)
    assert added == (second[0], ['ValueError: wrong'])
    assert [e.message for e in new] == ['three'] and complete

    # Nothing new
    assert follower.new_entries('a', second[-1:]) == (None, [], True)
    assert follower.new_entries('a', []) == (None, [], True)

    # The last entry seen is not in the window anymore: lines may have been missed
    third = read('[27/10/2026 12:00:09] [INFO] [a] nine')
    added, new, complete = follower.new_entries('a', third)
    assert new == third and not complete

    # Sources are followed separately
    assert follower.new_entries('b', first)[1] == first

def test_util_loggers():
    from lclib.util import h5rw, imstream
    assert h5rw.logger.name == 'lclib.h5rw'
    assert imstream.rootlogger is logs.logger
