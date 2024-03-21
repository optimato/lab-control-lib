"""
Proxy Device: decorators that expose a class and chose methods/properties
through network, using RpyC backend for communication.

Example code:

@proxydevice(address=("127.0.0.1", 5055))
class A:
    def __init__(self, x=1):
        self.x = x
        self.a = "abc"
        self.stop = False

    # A non-exposed call
    def do_something(self, y):
        self.x += y

    # An exposed call
    @proxycall()
    def get_multiple(self, y):
        return self.x * y

    # An exposed call allowed only for the client with admin rights
    @proxycall(admin=True)
    def set_a(self, a):
        self.a = a

    # A long task. Must be made non-blocking otherwise the sever will wait for return value
    @proxycall(admin=True, block=False)
    def long_task(self):
        for i in range(10):
            print(chr(i + 65))
            time.sleep(1)
            if self.stop:
                self.stop = False
                break
        return 1

    # Declaring the abort call, to be sent when ctrl-C is hit during a long call.
    @proxycall(interrupt=True)
    def abort(self):
        print("Aborting the long call!")
        self.stop = True

    # An exposed property
    @proxycall()
    @property
    def x_value(self):
        return self.x

    @x_value.setter
    def x_value(self, v):
        self.x = v

# Create a normal instance:
a = A()

# OR

# On one computer:
server = A.Server()

# On another computer:
a = A.Client()
# now a has all methods that have been exposed by the proxycall decorator
a.get_multiple(5)
 -> 5

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

import logging
import rpyc
import atexit
import threading
import inspect
import time
import sys
import traceback
import builtins
import pickle

from .util import Future
from .logs import logger as rootlogger

__all__ = ['proxydevice', 'proxycall', 'ProxyDeviceError']

logger = logging.getLogger(__name__)


def _m(obj):
    """
    Marshaller to avoid rpyc netrefs.
    """
    return pickle.dumps(obj)

def _um(s):
    """
    Unmarshaller.
    """
    return pickle.loads(s)


class ProxyDeviceError(Exception):
    pass


# Register custom error
rpyc.core.vinegar._generic_exceptions_cache[
    "lclib.util.proxydevice.ProxyDeviceError"] = ProxyDeviceError


class ThreadedServer(rpyc.ThreadedServer):
    """
    Minimal subclass that adds a callback for disconnect events.
    """

    def __init__(self, *args, **kwargs):
        self._disconnect_callback = kwargs.pop("disconnect_callback", None)
        super().__init__(*args, **kwargs)

    def _handle_connection(self, conn):
        super()._handle_connection(conn)
        if self._disconnect_callback:
            self._disconnect_callback(conn)


class WrapServiceBase(rpyc.Service):
    """
    Base class (dynamically augmented with other methods for the rpyc service.
    """

    # To be replaced by server instance in the dynamically generated subclass
    server = None

    def on_connect(self, conn):
        """
        Manage new client connection
        """
        # Store client connection object
        self.conn = conn

        # Thread id is used as unique id for this service (and this client)
        self.id = threading.get_ident()

        # Notify server of new connection
        self.server.new_client(self.id, self.conn)

        # Call parent class connect
        super().on_connect(conn)

    def exposed_create_instance(self, args, kwargs):
        """
        Attempt to create instance
        """
        return self.server.create_instance(args=args, kwargs=kwargs)

    def exposed_ask_admin(self, admin=None, force=None):
        """
        Request to become admin
        """
        return self.server.ask_admin(admin=admin, force=force)

    def exposed_kill(self):
        """
        Kill the server.
        """
        self.server.stop()

    def exposed_abort(self):
        """
        Abort call.
        """
        if self.server.interrupt_method is None:
            self.server.logger.error("Abort requested but no interrupt method exists!")
            return
        return self.server.interrupt_method()

    @classmethod
    def _new_exposed_method(cls, name, admin, block):
        """
        Add an "exposed" method to the server service class. The resulting
        method can be called by the client.

        Parameters:
        name (str): The name of the instance method
        admin (bool): If True, admin rights are required
        block (bool): If False, call instance method on a separate thread and
                      return immediately
        """
        if block:
            # Normal case: a method that grabs the lock and run the method
            def method(service_self, args, kwargs):
                # Check if admin rights are required
                if admin and not service_self.server.is_admin:
                    raise ProxyDeviceError(
                        f"Non-admin clients cannot run method {name}."
                    )

                # Find the method to call in the object instance
                instance_method = getattr(service_self.server.instance, name)

                # Call the instance method
                with service_self.server.lock:
                    result = instance_method(*_um(args), **_um(kwargs))
                return _m({"result": result})

        else:
            # Non-blocking call: we need to call the method on a separate thread and return
            def method(service_self, args, kwargs):
                # Check if admin rights are required
                if admin and not service_self.server.is_admin:
                    raise ProxyDeviceError(
                        f"Non-admin clients cannot run method {name}."
                    )

                # Find the method to call in the object instance
                instance_method = getattr(service_self.server.instance, name)

                # Check if another non-blocking call is already running
                if service_self.server.awaiting_result is not None:
                    raise ProxyDeviceError(
                        f"Current of past non-blocking call still pending."
                    )

                # Grab the lock: better making sure that no-one else is toying
                # with the server for the next steps
                with service_self.server.lock:
                    # Grab client connection to send result as a callback
                    c = service_self.server.this_conn()

                    # Define callback function
                    def callback(result, error):
                        # Send result or error to client
                        result_and_error = _m({"result": result, "error": error})
                        try:
                            c.root.notify_result(result_and_error)
                        except EOFError:
                            # This happens if keyboard interrupt killed the client
                            pass

                        # Either way we are done with this call so we reset the
                        # attribute holding the thread.
                        service_self.server.awaiting_result = None

                    # Create the thread and start it
                    service_self.server.awaiting_result = Future(
                        instance_method,
                        args=_um(args),
                        kwargs=_um(kwargs),
                        callback=callback,
                    )
                return _m({"result": None})

        # Attach the method to the service with "exposed_" prefix as per rpyc
        setattr(cls, f"exposed_{name}", method)

    @classmethod
    def _new_exposed_property(cls, name, admin):
        """
        Add "exposed" property getter and setter to the server service class.
        The resulting method will be called by the client through usual
        property interaction.

        Parameters:
        name (str): The name of the property
        admin (bool): If True, admin rights are required
        """

        # Getter
        def get_method(service_self):
            # Call getattr on the instance
            with service_self.server.lock:
                result = getattr(service_self.server.instance, name)

            return _m({"result": result})

        # Setter
        def set_method(service_self, value):
            # Check if admin rights are required
            if admin and not service_self.server.is_admin:
                raise ProxyDeviceError(f"Non-admin clients cannot set property {name}.")

            # Call setattr on the instance
            with service_self.server.lock:
                setattr(service_self.server.instance, name, _um(value))
            return _m({"result": None})

        # Attach the two methods to the service.
        setattr(cls, f"exposed__get_{name}", get_method)
        setattr(cls, f"exposed__set_{name}", set_method)


class ClientServiceBase(rpyc.Service):
    """
    The base class for the client service exposed to the server.
    """

    # To be replaced by the actual client object when subclassed
    client = None

    # To be replaced by a real logger when the object is subclassed
    exposed_logger = None

    def on_connect(self, conn):
        """
        Manage new connection

        This is the service exposed by the client to the remote server
        """
        # Store server connection object
        self.conn = conn

        # Call parent class connect
        super().on_connect(conn)

    def exposed_print(self, *objects, sep=' ', end='\n', file=sys.stdout, flush=False):
        """
        Print string locally
        """
        builtins.print(*objects, sep=sep, end=end, file=file, flush=flush)

    def exposed_input(self, prompt=None):
        """
        Get input locally
        """
        return input(prompt)

    def exposed_notify_result(self, result_and_error):
        """
        Called by server's "awaiting_result" thread when done.
        """
        self.client.logger.debug("Non-blocking call finished.")
        self.client.awaited_result = _um(result_and_error)
        self.client.result_flag.set()


class ProxyClientBase:
    """
    Base class for Proxy Client.
    """

    # These class attributes are set in subclasses created by the proxydevice decorator
    ADDRESS = None
    API = None

    SERVE_INTERVAL = 0.0
    SLEEP_INTERVAL = 0.1
    RECONNECT_INTERVAL = 3.0

    def __init__(self, admin=True, name=None, args=None, kwargs=None, clean=True, reconnect=True):
        """
        Base class for client proxy. Subclasses are created dynamically by the
        `proxydevice` decorator.

        Parameters:
        admin (bool): Whether admin rights should be requested
        name (str): an optional name for this client
        args (tuple): args to pass to the server if the remote object has not
                      been instantiated
        kwargs (dicts): same as args above
        clean (bool): If false, non-blocking calls will not "fake block"
                      awaiting result.
        reconnect(bool): If true, keep trying to reconnect when the server is lost.
        """
        self.name = self.__class__.__name__
        self.client_name = name or self.name
        self.clean = clean
        self.reconnect = reconnect

        # Statistics
        self.stats = {'startup': time.time(),
                      'reply_number': 0,
                      'total_reply_time': 0.,
                      'total_reply_time2': 0.,
                      'min_reply_time': 100.,
                      'max_reply_time': 0.,
                      'last_reply_time': 0.}

        # Create logger
        self.logger = rootlogger.getChild(self.__class__.__name__)

        # rpyc connection
        self.conn = None
        self.serving_thread = None
        self._connection_failed = False
        self.first_connect = True
        self._active = False
        self._terminate = False
        self.connect()

        # Result-ready-flag
        self.result_flag = threading.Event()
        self.awaited_result = None

        # Instantiate remote object if needed
        if args is not None or kwargs is not None:
            self.conn.root.create_instance(args, kwargs)

        # Ask for admin
        self.conn.root.ask_admin(admin=admin)

        # For thread clean up
        atexit.register(self._stop)

    def connect(self):
        """
        Initial connection. Will return only when the connection is established
        to continue initialization.
        """
        def catch_result(r, e):
            if e is None:
                return
            self._connection_failed = True

        self.serving_thread = Future(self._serve, callback=catch_result)

        # Wait for connection to be established.
        while True:
            if self.conn is not None:
                return
            if self._connection_failed:
                raise ProxyDeviceError('Connection failed')
            time.sleep(0.05)

    def disconnect(self):
        """
        Disconnect from server
        """
        self._stop()
        self._terminate = True

    def kill_server(self):
        self.conn.root.kill()

    def _serve(self):
        """
        Serve rpyc incoming connections. This replaces rpyc.BgServingThread, which
        is not robust enough to disconnect events.
        All exceptions have to be caught because this is running on a separate thread.
        """
        # Wrap everything in a loop for reconnect.
        while not self._terminate:
            try:
                # rpyc connection
                self.conn = rpyc.connect(
                    service=self._create_service(),
                    host=self.ADDRESS[0],
                    port=self.ADDRESS[1],
                )
            except ConnectionRefusedError:
                # No server present
                if self.first_connect or not self.reconnect:
                    self.logger.error(f"Connection to {self.ADDRESS} refused. Is the server running?")
                    raise

                # Try reconnecting
                self.logger.info(f"Connection to {self.ADDRESS} is lost. Reconnecting...")
                time.sleep(self.RECONNECT_INTERVAL)
                continue

            # Connected!
            if self.first_connect:
                self.logger.info(f"Connected to {self.ADDRESS}.")
                self.first_connect = False
            else:
                self.logger.info(f"Reconnected.")

            # Start serving
            self._active = True
            try:
                while self._active:
                    self.conn.serve(self.SERVE_INTERVAL)
                    time.sleep(self.SLEEP_INTERVAL)  # to reduce contention
                break
            except EOFError:
                # Connection closed!
                self.logger.warning("Connection lost.")
                if self.reconnect:
                    continue
                raise
        try:
            self.conn.close()
        except Exception:
            pass
        self.logger.info("Connection closed.")

    def ask_admin(self, admin=None, force=None):
        """
        Query or request admin status
        ask_admin() -> current admin status (True or False)
        ask_admin(admin=True) -> request admin status
        ask_admin(admin=False) -> rescind admin status
        ask_admin(admin=True, force=True) -> force admin status
        """
        return self.conn.root.ask_admin(admin=admin, force=force)

    def abort(self):
        """
        Call the remote interrupt method.
        """
        self.conn.root.abort()

    def _stop(self):
        """
        Close connections
        """
        self._active = False

    def _create_service(self):
        """
        Create a service subclass with appropriate class attributes.
        """

        class ClientService(ClientServiceBase):
            client = self
            exposed_logger = rpyc.restricted(
                self.logger, ["debug", "info", "warning", "error", "critical"]
            )

        return ClientService

    def _update_stats(self, t0, t1):
        """
        Update internal timing statistics.
        """
        dt = t1 - t0
        self.stats['reply_number'] += 1
        self.stats['total_reply_time'] += dt
        self.stats['total_reply_time2'] += dt * dt
        minr = self.stats['min_reply_time']
        maxr = self.stats['max_reply_time']
        self.stats['min_reply_time'] = min(dt, minr)
        self.stats['max_reply_time'] = max(dt, maxr)
        self.stats['last_reply_time'] = t0

    @classmethod
    def _new_property(cls, name, doc):
        """
        Add property to subclass, connected to remote object call.

        Parameters:
        name (str): property name
        doc (str): doc string
        """

        # Create getter
        def fget(client_self):
            t0 = time.time()
            method = getattr(client_self.conn.root, f"_get_{name}")
            reply = _um(method())
            client_self._update_stats(t0, time.time())
            return reply["result"]

        # Create setter
        def fset(client_self, value):
            t0 = time.time()
            method = getattr(client_self.conn.root, f"_set_{name}")
            method(_m(value))
            client_self._update_stats(t0, time.time())

        # Set name
        fget.__name__ = name
        fset.__name__ = name

        # Create property
        new_prop = property(fget, fset, None, doc=doc)
        setattr(cls, name, new_prop)

    @classmethod
    def _new_method(cls, name, doc, signature, block=True):
        """
        Add method to subclass, connected to remote object call.

        Parameters:
        name (str): property name
        doc (str): doc string
        signature (str): method signature. Used for documentation
        block (bool): whether the call will be blocking on server side.
        """
        # Create method that calls the remote method
        if block:
            # In blocking mode, we just request the result and wait
            def method(client_self, *args, **kwargs):
                t0 = time.time()
                service_method = getattr(client_self.conn.root, name)
                reply = _um(service_method(_m(args), _m(kwargs)))
                client_self._update_stats(t0, time.time())
                return reply["result"]

        else:
            # In non-blocking mode, we have to wait for result
            # and catch keyboard interrupts to try and abort the command
            def method(client_self, *args, **kwargs):
                # Find remote method to call
                service_method = getattr(client_self.conn.root, name)

                # This calls the remote method, but since it is non-blocking it returns immediately
                reply = _um(service_method(_m(args), _m(kwargs)))

                # Reset awaited result
                client_self.awaited_result = None
                client_self.result_flag.clear()

                if not client_self.clean:
                    # clean is False, do not "fake-block"
                    return reply

                # Wait for result. This loop catches keyboard interrupts
                emergency_stop = False
                while True:
                    if emergency_stop:
                        # We are here because a keyboard interrupt was set
                        client_self.abort()
                        return
                    try:
                        # Wait for result_flag to be set
                        if client_self.result_flag.wait(1):
                            # result_flag has been set. Clear it
                            client_self.result_flag.clear()
                            # Grab the result
                            reply = client_self.awaited_result
                            error = reply.pop("error", None)
                            if error:
                                raise error

                            # return the result
                            return reply["result"]
                    except KeyboardInterrupt:
                        # Set switch and continue to call abort.
                        emergency_stop = True
                        continue

        # Set method name and documentation
        method.__name__ = name
        doc = f"{name}{signature}\n" + doc
        method.__doc__ = doc

        # Attach method to subclass
        setattr(cls, name, method)


class ProxyServerBase:
    """
    Holding the device instance and serving clients.
    """

    # These class attributes are set in subclasses created by the proxydevice decorator
    ADDRESS = None
    API = None
    CLS = None

    def __init__(self, instantiate=True, instance_args=None, instance_kwargs=None):
        """
        Base class for server proxy. Subclasses are created dynamically by the
        proxydevice decorator and attaches the defaults ADDRESS, API and CLS as
        class attributes.

        Parameters:
        instantiate (bool): if True, create immediately the internal instance
                            of self.cls, using the provided args/kwargs. If
                            False, instantiation will proceed with the first
                            client connection.
        instance_args/kwargs: args, kwargs to pass for class instantiation.
        """
        # Create logger
        self.logger = rootlogger.getChild(self.__class__.__name__)
        self.name = self.__class__.__name__.lower()

        # instance of the class cls once we have received the initialization
        # parameters from the first client (or provided here at construction)
        self.instance = None

        # The instance method that gets called when an emergency stop is requested
        self.interrupt_method = None

        # The non-blocking thread
        self.awaiting_result = None

        # Dict of connected clients
        self.clients = {}

        # Lock to ensure instance is accessed synchronously
        self.lock = threading.Lock()

        # The rpyc server runs itself on a thread
        self.serving_thread = None
        self.rpyc_server = None

        # A variable telling who is admin
        self.admin = None

        atexit.register(self.stop)

        if instantiate:
            self.create_instance(args=instance_args, kwargs=instance_kwargs)

        # Create the service from API
        self.service = self._create_service()

        # Start serving
        self.activate()

    def activate(self):
        """
        Start serving
        """
        # Create rpyc threaded server
        self.rpyc_server = ThreadedServer(
            service=self.service,
            port=self.ADDRESS[1],
            protocol_config={
                "allow_all_attrs": True,
                "allow_setattr": True,
                "allow_delattr": True,
            },
            disconnect_callback=self.del_client,
        )

        # Replace print and input
        sys.modules[self.instance.__class__.__module__].print = self._proxy_print
        sys.modules[self.instance.__class__.__module__].input = self._proxy_input

        # Start server on separate thread
        self.serving_thread = threading.Thread(
            target=self.rpyc_server.start, daemon=True
        )
        self.serving_thread.start()

    def wait(self):
        """
        Wait until the server stops.
        """
        if self.serving_thread is not None and self.serving_thread.is_alive():
            self.serving_thread.join()

    def stop(self):
        """
        Stop serving.
        """
        try:
            self.rpyc_server.close()
        except AttributeError:
            # rpyc_server might already be None
            pass

        # Clean up
        sys.modules[self.instance.__class__.__module__].print = builtins.print
        sys.modules[self.instance.__class__.__module__].input = builtins.input

    def _create_service(self):
        """
        Factory for rpyc Service class based on API.

        This looks complicated because of the dynamically generated
        methods.
        """
        # Create subclass for the rpyc service
        WrapService = type("WrapService", (WrapServiceBase,), {})

        # Attach this instance of the server
        WrapService.server = self

        # Create exposed methods for all elements of the API
        for name, api_info in self.API.items():
            if api_info["property"]:
                WrapService._new_exposed_property(name, api_info["admin"])
            else:
                WrapService._new_exposed_method(
                    name, api_info["admin"], block=api_info["block"]
                )

        return WrapService

    @property
    def this_id(self):
        return threading.get_ident()

    def this_conn(self):
        """
        Return the connection object for this thread
        """
        # The id of the calling client
        id = self.this_id
        c = self.clients.get(id, None)
        if c is None:
            raise ProxyDeviceError(f"Thread {id} has no associated connected client!")
        return c

    def ask_admin(self, admin, force):
        """
        Manage admin requests
        """
        # This is the proxy for the remote (client) logger
        rlogger = self.this_conn().root.logger
        id = self.this_id

        if admin is None:
            if self.admin is None:
                rlogger.warning("No client is currently admin")
                return False
            is_admin = self.admin == id
            if is_admin:
                rlogger.info("Client is admin")
            else:
                rlogger.info("Client is not admin")
            return is_admin
        if admin:
            if self.admin is None:
                self.admin = id
                return True
            elif self.admin == id:
                rlogger.warning("Client aldeady admin")
                return True
            elif force:
                self.admin = id
                rlogger.info("Client now admin (forced)")
                return True
            else:
                return False
        else:
            if self.admin != id:
                rlogger.warning("Client was not admin")
                return None
            self.admin = None
            rlogger.info("Client not admin anymore")
            return True

    @property
    def is_admin(self):
        """
        True only if current client is admin.
        """
        return self.admin == self.this_id

    def _proxy_print(self, *objects, sep=' ', end='\n', file=None, flush=False):
        """
        Print locally and on client.
        """
        # Print to stdout
        builtins.print(*objects, sep=sep, end=end, file=file, flush=flush)

        # Print to client stdout
        cl_conn = self.clients.get(self.admin, None)
        if cl_conn is not None:
            try:
                cl_conn.root.print(*objects, sep=sep, end=end, file=file, flush=flush)
            except:
                builtins.print(traceback.format_exc())
                self.logger.error('Remote printing failed.')

    def _proxy_input(self, prompt=None):
        """
        Input through client.
        """
        cl_conn = self.clients.get(self.admin, None)
        if cl_conn is None:
            raise ProxyDeviceError("Cannot use input without admin client!")

        return cl_conn.root.input(prompt=prompt)

    def new_client(self, id, conn):
        """
        Called by a service on a new client connection, from it's own thread. Stores
        the rpyc connection object for future interactions.
        """
        self.clients[id] = conn

    def del_client(self, conn):
        """
        Called by the ThreadedServer instance upon disconnect.
        """
        id = self.this_id
        if not self.clients.pop(id, None):
            self.logger.error("Disconnecting client not found!")
        elif id == self.admin:
            self.logger.info(f"Admin client {id} disconnected")
            self.admin = None
        else:
            self.logger.info(f"Client {id} disconnected")

    def create_instance(self, args=None, kwargs=None):
        """
        Create the instance of the wrapped class, using args and kwargs as initialization parameters
        """
        args = args or ()
        kwargs = kwargs or {}

        # Raise error if instance already exists
        if self.instance is not None:
            raise RuntimeError(
                f"Instance of class {self.instance.__class__.__name__} already exists."
            )

        # Instantiate the wrapped object
        try:
            self.instance = self.CLS(*args, **kwargs)
        except BaseException as error:
            self.logger.critical("Class instantiation failed!", exc_info=True)
            self._stopping = True
            self.instance = None
            raise

        # Look for interrupt call
        self.interrupt_method = None
        for method_name, api_info in self.API.items():
            if api_info.get("interrupt"):
                self.interrupt_method = getattr(self.instance, method_name)
                self.logger.info(f"Method {method_name} is the abort call.")

        self.logger.info("Created instance of wrapped class.")


class proxycall:
    """
    Decorator to tag a method or property to be exposed for remote access.
    """

    def __init__(self, admin=False, block=True, interrupt=False, **kwargs):
        """
        Decorator to tag a method or property to be exposed for remote access.

        Parameters:
        admin (bool): whether admin rights are required to execute command.
        block (bool): Wait for the function to return.
        interrupt (bool): if True, declare this method as the method to call
                          when SIG_INT is caught on client side.
        kwargs: anything else that might be needed in the future.
        """
        self.admin = admin
        self.block = block
        self.interrupt = interrupt
        self.kwargs = kwargs

    def __call__(self, f):
        """
        Decorator call.
        This attaches a dictionary called api_call to methods and properties,
        which are then scanned by the proxydevice decorator.
        """
        api_info = {
            "admin": self.admin,
            "block": self.block,
            "interrupt": self.interrupt,
        }
        api_info.update(self.kwargs)
        if type(f) is property:
            api_info["property"] = True
            api_info["doc"] = f.fget.__doc__
            api_info["name"] = f.fget.__name__
            api_info["signature"] = None
            f.fget.api_info = api_info
        else:
            api_info["property"] = False
            api_info["doc"] = f.__doc__
            api_info["name"] = f.__name__
            api_info["signature"] = str(inspect.signature(f))
            f.api_info = api_info
        return f


class proxydevice:
    """
    Decorator that does the main magic.
    """

    def __init__(self, address=None, clean=True, stream=True, **kwargs):
        """
        Decorator initialization.

        Parameters:
        address (str, int): (IP, port)of the serving address. If None, will
                            have to be provided as an argument.
        clean (bool): whether the client side should receive replies in the
                      same format as for the native class. If false, blocking
                      calls return immediately.
        stream (bool): If True, mirror locally device's stdout and stderr
        kwargs: kept for compatibility
        """
        self.address = address
        self.clean = clean
        self.stream = stream

    def __call__(self, cls):
        """
        Decorator call. This creates a ServerBase and a ClientBase subclass.
        The latter gets populated with all fake methods and properties that
        make calls to the server through the rpyc connection.
        """

        # Extract API info
        API = {}
        # Looping through __dict__ misses all methods of parent class(es)
        # So we need to do it with getattr
        for k in dir(cls):
            try:
                v = getattr(cls, k)
                if type(v) is property:
                    api_info = v.fget.api_info
                else:
                    api_info = v.api_info
            except AttributeError:
                continue
            API[k] = api_info

        # Define server subclass and set default values
        Server = type(f"{cls.__name__}ProxyServer", (ProxyServerBase,), {})
        Server.ADDRESS = self.address
        Server.API = API
        Server.CLS = cls

        # Define client subclass
        Client = type(f"{cls.__name__}ProxyClient", (ProxyClientBase,), {})
        Client.ADDRESS = self.address
        Client.API = API

        # Create all fake methods and properties for Client
        for name, api_info in API.items():
            signature = api_info["signature"] or "(*args, **kwargs)"
            doc = api_info["doc"] or ""
            try:
                if api_info["property"]:
                    Client._new_property(name, doc)
                    logger.debug(f"Added property {name} to client proxy.")
                else:
                    Client._new_method(name, doc, signature, block=api_info["block"])
                    logger.debug(f"Added method {name} to client proxy.")
                    if api_info["interrupt"]:
                        logger.debug(f"Method {name} is the abort call.")

            except AttributeError:
                continue

        # Attach server and client objects to decorated class
        cls.Server = Server
        cls.Client = Client
        return cls
