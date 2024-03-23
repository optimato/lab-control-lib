=====
Usage
=====

Command line uses
=================

 (TODO: Currently broken)

* List all proxy drivers that can be started on the current host:

  ``python -m labcontrol list``

* Start one proxy driver. 

  ``python -m labcontrol start [driver]``

  This will work only if ran from the correct host, and the process will continue to run in the shell.
  The benefit for this usage is that it is easy to ctrl-C.

* To start all proxy drivers:

  ``python -m labcontrol startall``

  This spawns independent processes, so there is no way to interrupt running servers once running.
  Only proxy servers that match the current host will be spawned.

* Kill one proxy driver:

  ``python -m labcontrol kill [driver]``

* Kill all proxies:

  ``python -m labcontrol killall``

