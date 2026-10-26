=====
Usage
=====

Command line uses
=================

In the following we assume that the custom lab package is called `labname`:

* List all proxy drivers:

  ``python -m lclib labname list``

* List proxy drivers available on the current host:

  ``python -m lclib labname llist``

* Start one proxy driver.

  ``python -m lclib labname start [driver]``

  This will work only if all daemon services are running. The command waits until the driver
  is ready (at most 60 s, see the ``--timeout`` option) and prints ``RUNNING``, or ``FAILED``
  followed by the end of the driver output, which usually shows the error that prevented the
  driver from starting.

  To start the driver without the use of the daemon, use instead the ``lstart`` command
  (standing for "local start"):

  ``python -m lclib labname lstart [driver]``

  In this case the command must be executed on the correct host, and the process will continue
  to run in the shell. The benefit for this usage is that it is easy to ctrl-C.

  Either ways, once the driver is started, it will be available for normal usage.

* Show the status of all drivers, according to the daemons:

  ``python -m lclib labname status``

  The states are ``STARTING``, ``RUNNING``, ``STOPPING``, ``EXITED`` (stopped on request) and
  ``FAILED`` (failed to start, or stopped unexpectedly). ``-`` means that the driver was not
  started by the daemon: it may still be running if it was started with ``lstart``.

* Show the end of the log of a driver (from any host):

  ``python -m lclib labname log [driver]``

  The option ``-n`` sets the number of lines (50 by default), and ``--out`` shows the process
  output (stdout and stderr) instead of the log file. For a driver that never became ready, the
  process output is shown, since it contains the error.

* Show all currently running proxy drivers (started by the daemon or not):

  ``python -m lclib labname running``

* Kill one proxy driver:

  ``python -m lclib labname kill [driver]``

* Stop the process of a driver through the daemon of its host:

  ``python -m lclib labname forcekill [driver]``

  The driver is first asked to shut down, and terminated if it is still running after 10 s.
  This also works for a driver that is still starting or does not respond.

* Kill all drivers:

  ``python -m lclib labname killall``

* Start a viewer

  ``python -m lclib labname viewer [driver]``

  This will start a viewer for the specified driver. The driver must be a `Camera` subclass.

* Start the driver control panel

  ``python -m lclib labname cp``

  This will start the driver control panel on a browser. It shows the state of all drivers,
  and allows to start and stop them and to read their log (log button). Hovering over a
  ``FAILED`` state shows the error.

Log files
=========

Each host keeps the following files (``~`` is the home directory, ``%USERPROFILE%`` on Windows):

* ``~/.lclib/lclib-daemon.log``: the daemon log. It records the drivers started and stopped,
  and the unexpected exits, with the end of the driver output.
* ``~/.lclib/run/<lab>_<driver>/``: the files of the drivers started by the daemon. For each
  run, a ``.out`` file holds the process output (warnings, errors, and anything printed). The
  files of the last 10 runs are kept.
* ``~/.<lab>-lclib/logs/``: the complete log of each driver.

The ``status`` and ``log`` commands, and the control panel, read these files through the daemon:
they do not need to be run on the host of the driver.
