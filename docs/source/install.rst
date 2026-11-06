=======
Install
=======


Installing from source
======================
  
Clone the `lab-control-lib <https://github.com/optimato/lab-control-lib>`_  
from GitHub::

    git clone https://github.com/optimato/lab-control-lib.git

then::

    $ cd lab-control-lib
    $ pip install .

After the first installation, install the daemon as a service, from the Python environment it
should use (e.g. the conda environment of the lab)::

    $ lc --install-daemon

This writes the installation scripts for the current user and Python interpreter in
``~/.lclib/scripts``, runs the one of this platform, and starts the daemon: a systemd service on
Linux (the script uses ``sudo``), a scheduled task on Windows. The service starts automatically
at system startup. ``lc --remove-daemon`` removes it.

When updating the library, the service does not need to be installed again, only restarted::

    $ lc -r

Under Windows, if the daemon was installed with an earlier version of the scripts, Windows stops it
after 3 days (and when the computer runs on battery power). Running ``lc --install-daemon`` again
replaces the scheduled task with one that runs indefinitely.

Network access
==============

The daemon and the drivers accept connections from any computer that can reach them, without
authentication: anyone on the network can start, stop and control the drivers. (The daemon only
reads the log and output files of the drivers, given by driver name, never other files.) Keep
the lab computers on a private network, or behind a firewall that lets only the lab computers
reach the daemon port (9998 by default, set by the environment variable ``LCLIB_DAEMON_PORT``)
and the ports of the drivers.
