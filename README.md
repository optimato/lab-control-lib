# LabControl-lib

LabControl lib is a suite of tools initially developed for the Optimal Imaging and Tomography group, University of Trieste/Elettra sincrotone, and based on earlier code developed in the X-ray Nano-Imaging Group, at the University of Southampton. See below for a list of contributors.

This package is a library, in the sense that it provides the tools to for laboratory management, but does not include actual drivers for any lba device. For this, a custom laboratory control package has to be be written. This control package imports the library, defines and registers the various drivers to connect to the hardware piece. 

Terminology
-----------
* **Device**: an instrument with which it is necessary to communicate for motion, detection, etc.
* **Driver**: a python object that can be instantiated to manage a device.
* **Socket Driver**: a driver that communicates with a device through a socket connection.
* **Proxy Server**: an object that manages one driver and accepts connections from proxy clients to control this driver.
* **Proxy Client**: a client that connects to a Proxy Server. It is a "proxy" because it reproduces the driver interface through method calls.

General principles
------------------
The design of this software is made to address these limitations:
- Most devices allow only one connection at a time. It is often useful to access a device through multiple clients, for instance to probe for metadata or specific signals.
- Keeping logs of a device status requires a process that runs constantly and that keep alive a connection with that device.
- A crash in a control software should not interrupt connections to all devices or require a complete reinitialization.
- Running all drivers in a single process might overload the computer resources
- Some devices must run on their own machine (Windows), so at the very least these devices need to be "remote controlled".

The solution is a distributed device management. Each device is managed by a driver that runs on a unique process, and is wrapped by a proxy server. Control and data access is done through one or more proxy clients to the proxy server. Since all communication is through TCP sockets, drivers can run on different computers, as long as they are on the same network. An "admin" status is conferred only to one client at a time to ensure that no two processes attempt at controlling a device simultaneously (all "read-only" methods are however allowed by non-admin clients).

The key components of this package are the driver base classes, and the proxy server/client architecture.

In practice, each driver can be implemented as if it is meant to be the single instance connected to the device. The base class `DriverBase` takes care of a few things (logging, configuration, metadata collection, periodic calls), while `SocketDriverBase` has all what is needed to connect to devices that have socket connections.

The client/server infrastructure is provided through decorators on the driver classes and their exposed methods. These decorators are provided by the module `proxydevice`. All drivers that can be provided as servers are decorated with `@proxydevice`, and methods are made remotely accessible with the method decorator `@proxycall`. See the module doc for more info.

Additional classes
------------------
Devices normally fall in two main categories: motion devices, and detectors. There  is therefore a high-level class `Motor` meant to provide access to the underlying device through a common interface (with methods inspired from the `spec` language). For detectors, the common interface is `CameraBase`, which is a subclass of DriverBase. The hope is to make instances of `Motor` and `CameraBase` subclasses sufficient for everyday use. 

An additional driver called `Manager` is also defined in this library. The manager is a "driver" in the sense that it is part of the classes that are accessed through proxy clients. Manager takes care of metadata collection and scan and file numbering and naming conventions. See `manager.py` for more info. 

Writing a control package
-------------------------
The init() method has to be called early to inform the library of the most important parameters for its functioning, namely
 * the name of the lab (for identification and access to configuration files)
 * the names and IP addresses of the relevant computers on the LAN, to identify the platform where the package is being run.
 * the physical path where data will be saved
 * the address of the manager driver

User Interface
--------------
The `ui` subpackage provides some tools for user interface. 

TBC
