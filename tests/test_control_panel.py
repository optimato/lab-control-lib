"""
Tests of the control panel logic (lclib/ui/driver_control_panel.py), with stand-ins for the
NiceGUI widgets, the daemons and the driver clients.
"""
import asyncio
from unittest import mock

import pytest

import lclib.ui.driver_control_panel as cp
from lclib.daemon import API_VERSION


@pytest.fixture
def ui(monkeypatch):
    """
    Stand-ins for the NiceGUI widgets, and for run.io_bound (runs the function directly).
    """
    ui = mock.MagicMock()
    ui.tooltip.side_effect = lambda *args, **kwargs: mock.MagicMock()
    monkeypatch.setattr(cp, 'ui', ui)

    async def io_bound(f, *args):
        return f(*args)
    monkeypatch.setattr(cp, 'run', mock.MagicMock(io_bound=io_bound))
    return ui

@pytest.fixture
def row(ui, monkeypatch):
    """
    A row of the panel, with stand-in widgets, client to the driver and daemon.
    """
    client = mock.MagicMock(connected=False)
    monkeypatch.setattr(cp, 'client_or_None', lambda *args, **kwargs: client)
    daemon = mock.MagicMock(connected=True)
    return cp.GridRow({'name': 'motor', 'labname': 'lab', 'daemon': daemon, 'hostname': 'h'}, mock.MagicMock())

def _tooltip(row):
    return row.status_tooltip.set_text.call_args.args[0]

def _status(state, **kwargs):
    return {'state': state, 'failed': None, 'error_tail': None, **kwargs}

@pytest.mark.parametrize('connected, status, expected', [
    (False, None, 'OFFLINE'),
    (True, None, 'UNMANAGED'),
    (False, _status('starting'), 'STARTING'),
    # The client needs a few seconds to connect to a driver that just became ready
    (False, _status('running'), 'STARTING'),
    (True, _status('running'), 'ONLINE'),
    (False, _status('stopping'), 'STOPPING'),
    (False, _status('exited', failed=True, error_tail=['RuntimeError: broken']), 'FAILED'),
    (False, _status('exited', failed=False), 'OFFLINE'),
])
def test_states(row, connected, status, expected):
    row.client.connected = connected
    row.update_state(status)
    assert row.state == expected

def test_not_responding_after_grace_period(row):
    row.update_state(_status('running'))
    row.unreachable_since -= cp.GridRow.CONNECT_GRACE + 1
    row.update_state(_status('running'))
    assert row.state == 'NOT RESPONDING'

def test_failed_tooltip(row):
    row.update_state(_status('exited', failed=True, error_tail=['Traceback', 'RuntimeError: broken', '']))
    assert _tooltip(row) == 'RuntimeError: broken'

def test_daemon_problem(row):
    problem = ('OLD DAEMON', 'Daemon on h too old: update lclib')
    row.update_state(None, problem)
    assert row.state == 'OLD DAEMON'
    assert _tooltip(row) == problem[1]
    # Neither start nor stop button
    assert cp.GridRow.STYLES['OLD DAEMON'][1:] == (False, False)

    # A driver running anyway (e.g. started by hand) is unmanaged, with the explanation
    row.client.connected = True
    row.update_state(None, problem)
    assert row.state == 'UNMANAGED'
    assert _tooltip(row) == problem[1]

    # Start: the explanation, instead of a call to the daemon
    row.start()
    cp.ui.notify.assert_called_with(problem[1])
    row.daemon.start.assert_not_called()

def test_row_log_checkbox_and_name(row):
    # The checkbox selects the driver in the log panel
    on_change = cp.ui.checkbox.call_args.kwargs['on_change']
    on_change(mock.MagicMock(value=True))
    row.log_panel.select.assert_called_with('motor', 'h', True)

    # A click on the driver name opens the log dialog
    cp.ui.label.return_value.classes.return_value.on.assert_called_with('click', row.show_log)

#
# Log panel
#

def _line(time, level, name, message):
    return f'[28/10/2026 {time}] [{level}] [{name}] [f():1] [PID:1 TID:1] {message}'

class FakeDaemon:
    """
    A daemon whose drivers have the given log lines.
    """
    connected = True

    def __init__(self, lines):
        self.lines = lines
        self.calls = []

    def tail(self, lab, driver, n):
        self.calls.append((driver, n))
        return {'lines': self.lines[driver][-n:]}

@pytest.fixture
def panel(ui):
    daemon = FakeDaemon({'a': [_line('12:00:01.000', 'INFO', 'a', 'a one'),
                               _line('12:00:03.000', 'ERROR', 'a.proxy', 'a failed'),
                               'Traceback (most recent call last):'],
                         'bb': [_line('12:00:02.000', 'WARNING', 'bb', 'bb warning')]})
    panel = cp.LogPanel('lab', {'h': daemon}, ['a', 'bb'])
    panel.level_select.value = 'DEBUG'
    panel.daemon = daemon
    _pushed(panel)
    return panel

def _pushed(panel):
    """
    Lines added to the log since the last call, with their classes.
    """
    calls = panel.log.push.call_args_list
    panel.log.push.reset_mock()
    return [(call.args[0], call.kwargs.get('classes')) for call in calls]

def test_log_panel_merges_selected_drivers(panel):
    panel.select('a', 'h', True)
    panel.select('bb', 'h', True)
    asyncio.run(panel.update())
    indent = ' ' * (12 + 2 + 2 + 2 + 9)

    # A separator for each newly selected driver, then the entries merged by time
    assert _pushed(panel) == [
        ('--- a: last lines ---', 'text-gray-500'),
        ('--- bb: last lines ---', 'text-gray-500'),
        ('12:00:01.000  a   INFO     a one', ''),
        ('12:00:02.000  bb  WARNING  bb warning', 'text-orange-600'),
        ('12:00:03.000  a   ERROR    [a.proxy] a failed', 'text-red-600'),
        (indent + 'Traceback (most recent call last):', 'text-red-600')]
    assert panel.daemon.calls == [('a', cp.LogPanel.FIRST_LINES), ('bb', cp.LogPanel.FIRST_LINES)]

    # Next read: only what is new (here, the end of the traceback and a new entry)
    panel.daemon.lines['a'] += ['ValueError: wrong', _line('12:00:04.000', 'INFO', 'a', 'a two')]
    asyncio.run(panel.update())
    assert [text for text, _ in _pushed(panel)] == [indent + 'ValueError: wrong',
                                                    '12:00:04.000  a   INFO     a two']
    assert panel.daemon.calls[-2:] == [('a', cp.LogPanel.LINES), ('bb', cp.LogPanel.LINES)]

def test_log_panel_level_and_pause(panel):
    panel.level_select.value = 'WARNING'
    panel.select('a', 'h', True)
    panel.select('bb', 'h', True)
    asyncio.run(panel.update())
    texts = [text for text, _ in _pushed(panel)]
    assert not any('a one' in text for text in texts)
    assert any('bb warning' in text for text in texts)

    # Nothing is read while paused
    panel.toggle_pause()
    calls = len(panel.daemon.calls)
    asyncio.run(panel.update())
    assert len(panel.daemon.calls) == calls

def test_log_panel_unselect(panel):
    panel.select('a', 'h', True)
    asyncio.run(panel.update())
    _pushed(panel)

    panel.select('a', 'h', False)
    asyncio.run(panel.update())
    assert _pushed(panel) == []

    # Selected again: its last lines again
    panel.select('a', 'h', True)
    asyncio.run(panel.update())
    assert _pushed(panel)[0][0] == '--- a: last lines ---'

def test_log_panel_problem_shown_once(panel):
    panel.daemon.connected = False
    panel.select('a', 'h', True)
    asyncio.run(panel.update())
    asyncio.run(panel.update())
    assert [text for text, _ in _pushed(panel)] == ['--- a: Daemon on h not reachable. ---']

def _daemon(connected=True, version=API_VERSION, error=None):
    daemon = mock.MagicMock(connected=connected, connection_error=error)
    if isinstance(version, Exception):
        daemon.api_version.side_effect = version
    else:
        daemon.api_version.return_value = version
    return daemon

def test_daemon_problems():
    problem = cp.DeviceManagerApp._daemon_problem
    assert problem('h', _daemon()) is None
    assert problem('h', None)[0] == 'NO DAEMON'
    assert problem('h', _daemon(connected=False, error='timed out')) == \
           ('NO DAEMON', 'Daemon on h not reachable: timed out.')
    assert problem('h', _daemon(version=API_VERSION - 1))[0] == 'OLD DAEMON'
    # Daemons older than the version check
    assert problem('h', _daemon(version=AttributeError('api_version')))[0] == 'OLD DAEMON'
    # Connection lost during the call
    assert problem('h', _daemon(version=EOFError('connection closed')))[0] == 'NO DAEMON'
