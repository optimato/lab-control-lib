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

  This will work only if all daemon services are running. To start the driver without the use of
  the daemon, use instead the ``lstart`` command (standing for "local start"): 
  
  ``python -m lclib labname lstart [driver]``

  In this case the command must be executed on the correct host, and the process will continue
  to run in the shell. The benefit for this usage is that it is easy to ctrl-C.

  Either ways, once the driver is started, it will be available for normal usage.

* Show all currently running proxy drivers:

  ``python -m lclib labname running``

* Kill one proxy driver:

  ``python -m lclab labname kill [driver]``

* Kill all drivers:

  ``python -m lclib labname killall``

