"""
Tests of the control panel logic (lclib/ui/driver_control_panel.py), with stand-ins for the
NiceGUI widgets, the daemons and the driver clients.
"""
from unittest import mock

import pytest

import lclib.ui.driver_control_panel as cp
from lclib.daemon import API_VERSION


@pytest.fixture
def row(monkeypatch):
    """
    A row of the panel, with stand-in widgets, client to the driver and daemon.
    """
    ui = mock.MagicMock()
    ui.tooltip.side_effect = lambda *args, **kwargs: mock.MagicMock()
    monkeypatch.setattr(cp, 'ui', ui)
    client = mock.MagicMock(connected=False)
    monkeypatch.setattr(cp, 'client_or_None', lambda *args, **kwargs: client)
    daemon = mock.MagicMock(connected=True)
    return cp.GridRow({'name': 'motor', 'labname': 'lab', 'daemon': daemon, 'hostname': 'h'})

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
