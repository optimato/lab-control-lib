=====
Usage
=====

Command line uses
=================

 (WARNING: incomplete and subject to change!)

In the following we assume that the custom lab package is called `labname`:

* List all proxy drivers that can be started on the current host:

  ``python -m lclib labname list``

* Start one proxy driver. 

  ``python -m lclib labname start [driver]``

  This will work only if ran from the correct host, and the process will continue to run in the shell.
  The benefit for this usage is that it is easy to ctrl-C.

* Show all currently running proxy drivers:

  ``python -m lclib labname running``

* Kill one proxy driver:

  ``python -m lclab labname kill [driver]``

* Kill all drivers:

  ``python -m lclib labname killall``

