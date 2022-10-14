"""
Proxy Device: decorators that expose a class and chose methods/properties
trough network.

Example code:

@proxydevice(address=('127.0.0.1', 5055))
class A:
    def __init__(self, x=1):
        self.x = x
        self.a = 'abc'

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
    @proxycall(block=False)
    def long_task(self):
        time.sleep(10)

    # Declaring the abort call, to be sent when ctrl-C is hit during a long call.
    @proxycall(interrupt=true)
    def abort(self):
        print('I would abort the long call!)

    # An exposed property
    @proxycall()
    @property
    def x_value(self):
        return self.x

    @x_value.setter
    def x_value(self, v):
        self.x = v

# On one computer:
server = A.server()

# On another computer:
a = A.client()
# now a has all methods that have been exposed by the proxycall decorator
a.get_multiple(5)
 -> 5

"""

import logging
import zmq
import time
import atexit
import threading
import inspect

from .future import Future


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

logger = logging.getLogger(__name__)


class ProxyClientError(Exception):
    pass


class ServerBase:
    """
    Server for a wrapped class.
    """

    PING_INTERVAL = 1
    PING_TIMEOUT = 30
    POLL_TIMEOUT = 10
    ESCAPE_STRING = '^'

    def __init__(self, cls, API, address):
        """
        Base class for server proxy

        cls: The class being wrapped
        API: a dictionary listing all methods to be exposed (collected through the proxycall decorator)
        address: (IP, port) to listen on.

        Note that this is not really an abstract class. The proxydevice decorator produces a subclass
        of this class, but only to assign a different name for clearer documentation.
        """
        # Store input parameters for later
        self.cls = cls
        self.API = API
        self.address = address

        self.logger = logging.getLogger(self.__class__.__name__)
        self.name = self.__class__.__name__.lower()

        # instance of the class cls once we have received the initialization parameters from the first client.
        self.instance = None

        # Client management
        self.clients = {}
        self.stats = {}
        self.counters = {}
        self.IDcounter = 1

        # Futures for the listening and heartbeat (ping) threads
        self.server_future = None
        self.ping_future = None
        self.ping_lock = threading.Lock()
        self.awaiting_result = None
        self._awaiting_result = None   # For lingering result, after cancellation

        self.interrupt_method = None

        # To be assigned in self.activate
        self.context = None
        self.socket = None

        self.admin = None
        self._stopping = False
        atexit.register(self.stop)

        self.activate()

    def activate(self):
        """
        Activate (or reactivate) the server, and start (or restart) the listening and ping threads.
        """

        try:
            if not self.server_future.done():
                self.logger.warning('Server was still running. Restarting.')
                self.stop()
                self.server_future.result()
                self.ping_future.result()
        except:
            pass
        self.server_future = Future(self._run)
        self.ping_future = Future(self._ping_counter)

    def stop(self):
        """
        Stop the server. This signals both listening and ping threads to terminate.
        """
        self._stopping = True

    def _ping_counter(self):
        """
        Manages the presence of clients by monitoring the amount of time since each client
        has sent a ping command.
        """
        while True:
            if self._stopping:
                return
            with self.ping_lock:
                for ID in list(self.counters.keys()):
                    self.counters[ID] -= self.PING_INTERVAL
                    if self.counters[ID] <= 0:
                        self.disconnect(ID)
            time.sleep(self.PING_INTERVAL)

    def _run(self):
        """
        Prepare the server and start listening for connections.
        (runs on the separate thread)
        """
        self._stopping = False

        # Initialize socket for entry point
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        full_address = f'tcp://{self.address[0]}:{self.address[1]}'
        self.socket.bind(full_address)

        self.logger.info(f'Server bound to {full_address}')

        # Initialize poller
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)

        self._activated = True
        try:
            self._listen()
        finally:
            self.logger.info('Stop listening')
            self.socket.unbind(full_address)
            self.socket.close()

    def _listen(self):
        """
        Listen for connections and process requests.
        """
        self.logger.info('Now listening')

        while not self._stopping:
            # Check for new requests
            if self.poller.poll(self.POLL_TIMEOUT):

                # Get new command
                message = self.socket.recv_json()
                ID = message[0]
                cmd = message[1]
                self.logger.debug(f'{ID} sent command {cmd}')

                if ID == 0:
                    # ID == 0 is a request from a new client
                    reply = self.new_connection(message)
                    self.socket.send_json(reply)
                    continue
                if ID not in self.clients:
                    # Unknown ID
                    reply = {'status': 'error', 'msg': f'Client with ID {ID} not recognised'}
                    self.socket.send_json(reply)
                    continue

                # Parse command
                t0 = time.time()
                reply = self._parse_message(message)
                self.logger.debug(f'Reply: {reply}')

                # Compute some statistics
                # Disconnect might have happened, so we need to check
                if ID in self.clients:
                    dt = time.time() - t0
                    self.clients[ID]['reply_number'] += 1
                    self.clients[ID]['total_reply_time'] += dt
                    self.clients[ID]['total_reply_time2'] += dt * dt
                    minr = self.clients[ID]['min_reply_time']
                    maxr = self.clients[ID]['max_reply_time']
                    self.clients[ID]['min_reply_time'] = min(dt, minr)
                    self.clients[ID]['max_reply_time'] = max(dt, maxr)
                    self.clients[ID]['last_reply_time'] = t0

                # Send reply to client
                try:
                    self.socket.send_json(reply)
                except TypeError as e:
                    # We just tried to send a non-serializable reply
                    reply = {'status': 'error', 'msg': repr(e)}
                    self.socket.send_json(reply)

    def _parse_message(self, message):
        """
        Parse the message sent by the bound client.

        There are multiple cases to consider (method / property, blocking / non-blocking)

        message is a 4-tuple of the form (ID, cmd, args, kwargs)
        """
        # Unpack command and arguments
        ID, cmd, args, kwargs = message

        self.logger.debug(f'Received command "{cmd}" from client "{ID}"')

        # Manage escaped command
        if cmd.startswith(self.ESCAPE_STRING):
            cmd = cmd.lstrip(self.ESCAPE_STRING)
            return self._parse_escaped(ID, cmd, args, kwargs)

        # Manage API command
        self.logger.debug(f'Running command "{cmd}"')

        # Manage property get / set
        if self.API[cmd]['property']:
            self.logger.debug(f'{cmd} is a property.')

            # Special case! if args is not empty, interpreted as a setter!
            if args:

                # If the command requires admin rights, check that the client is allowed to run it.
                if self.API[cmd]['admin'] and self.admin != ID:
                    return {'status': 'error', 'msg': f'Non-admin clients cannot set property "{cmd}"'}

                # Try call property setter
                try:
                    setattr(self.instance, cmd, args[0])
                    reply = {'status': 'ok', 'value': None}
                except BaseException as error:
                    reply = {'status': 'error', 'msg': repr(error)}
            else:
                # Try to call property getter
                try:
                    v = getattr(self.instance, cmd)
                    reply = {'status': 'ok', 'value': v}
                except BaseException as error:
                    reply = {'status': 'error', 'msg': repr(error)}
        else:
            if self.API[cmd]['admin'] and self.admin != ID:
                return {'status': 'error', 'msg': f'Command "{cmd}" cannot be run by non-admin clients.'}

            # Normal method call
            if self.API[cmd]['block']:
                # Blocking: call the method, wait for result before sending reply
                try:
                    result = getattr(self.instance, cmd)(*args, **kwargs)
                    # Special hack: bytes are not json-serializable
                    if type(result) is bytes:
                        result = result.decode()
                    reply = {'value': result, 'status': 'ok'}
                except BaseException as error:
                    reply = {'status': 'error', 'msg': repr(error)}
            else:
                # Non-blocking
                if self.awaiting_result is not None:
                    # Can't run two nested non-blocking calls
                    reply = {'status': 'error', 'msg': 'Current or past non-blocking command has not been cleared.'}
                else:
                    # Get the method, start the thread wrapper (meant to catch exceptions), send acknowledgement
                    try:
                        method = getattr(self.instance, cmd)
                        self.awaiting_result = Future(self._run_awaiting, args=(method,), kwargs={'args':args, 'kwargs':kwargs})
                        reply = {'status': 'ok', 'value': None, 'msg': 'Non-block call started'}
                    except BaseException as error:
                        reply = {'status': 'error', 'msg': repr(error)}

        return reply

    def _run_awaiting(self, method, **kwargs):
        """
        Wrapper to catch errors in non-blocking method call.
        """
        try:
            result = method(*kwargs['args'], **kwargs['kwargs'])
            return result
        except BaseException as error:
            return 'Error: ' + repr(error)

    def new_connection(self, message):
        """
        Manage new client.
        """
        _, _, args, kwargs = message

        if self.instance is None:
            # First connection! We create the class instance
            # Using the passed parameters.
            try:
                # Instantiate the wrapped object
                self.instance = self.cls(*args, **kwargs)

                # Look for an interrupt method (will be called with an ^abort command)
                self.interrupt_method = None
                for cmd, api_info in self.API.items():
                    if api_info.get('interrupt'):
                        self.interrupt_method = getattr(self.instance, cmd)
                        self.logger.info(f'Method {cmd} is the abort call.')
            except BaseException as error:
                reply = {'status': 'error', 'msg': repr(error)}
                return reply
            self.logger.info('Created instance of wrapped class.')

        # Prepare client-specific info
        ID = self.IDcounter + 0
        self.IDcounter += 1

        # Add ping time
        with self.ping_lock:
            self.counters[ID] = self.PING_INTERVAL

        # Set statistics
        self.clients[ID] = {'startup': time.time(),
                            'reply_number': 0,
                            'total_reply_time': 0.,
                            'total_reply_time2': 0.,
                            'min_reply_time': 100.,
                            'max_reply_time': 0.,
                            'last_reply_time': 0.}

        reply = {'status': 'ok', 'value': {'ID':ID}}
        self.logger.info(f'Client #{ID} connected.')
        return reply

    def disconnect(self, ID):
        """
        Disconnect the client ID. This is not really a disconnection, but we "forget" the ID, so the client
        with this ID won't be allowed to do anything.
        """
        try:
            self.clients.pop(ID)
            self.counters.pop(ID)
            if ID == self.admin:
                self.admin = None
        except KeyError:
            return {'status': 'error', 'msg': f'{ID} not recognised'}
        self.logger.info(f'Client #{ID} disconnected.')
        return {'status': 'ok'}

    def _parse_escaped(self, ID, cmd, args, kwargs):
        """
        Escaped commands.
        """
        #
        # PING
        #
        if cmd.lower() == 'ping':
            try:
                self.counters[ID] = self.PING_TIMEOUT
                return {'status': 'ok'}
            except BaseException as error:
                return {'status': 'error', 'msg': repr(error)}

        #
        # DISCONNECT
        #
        if cmd.lower() == 'disconnect':
            return self.disconnect(ID)
        #
        # ADMIN
        #
        if cmd.lower() == 'admin':
            return self.ask_admin(ID, *args, **kwargs)

        #
        # STATS
        #
        if cmd.lower() == 'stats':
            return {'status': 'ok', 'value': self.clients[ID]}

        #
        # RESULT
        #
        if cmd.lower() == 'result':
            # Get awaiting result or possibly the lingering one.
            awaiting_result = self.awaiting_result if self.awaiting_result is not None else self._awaiting_result
            if awaiting_result is None:
                return {'status': 'error', 'msg': 'No awaiting result found.'}
            elif not awaiting_result.done():
                return {'status': 'waiting', 'msg': 'Task is still running'}
            try:
                result = awaiting_result.result()
            except BaseException as error:
                return {'status': 'error', 'msg': repr(error)}
            finally:
                self.awaiting_result = None
                self._awaiting_result = None
            return {'status': 'ok', 'value': result}

        #
        # ABORT
        #
        if cmd.lower() == 'abort':
            if self.awaiting_result is None:
                self.logger.warning('ABORT signal received but nothing to abort')
                return {'status': 'error', 'msg': 'No task to abort.'}
            elif self.awaiting_result.done():
                try:
                    result = self.awaiting_result.result()
                except BaseException as error:
                    return {'status': 'error', 'msg': repr(error)}
                finally:
                    self.awaiting_result = None
                self.logger.warning('ABORT signal received but task was complete')
                return {'status': 'ok', 'value': result, 'msg': 'Task complete'}
            else:
                if self.interrupt_method:
                    try:
                        result = self.interrupt_method()
                    except BaseException as error:
                        return {'status': 'error', 'msg': repr(error)}
                    self.logger.warning('ABORT signal received, and interrupt method called.')
                    reply = {'status': 'ok', 'value': result}
                else:
                    self.logger.warning('ABORT signal received but no abort method is known.')
                    reply = {'status': 'error', 'msg': 'No interrupt method has been defined.'}

                # Not sure what to do with awaiting result... store in temporary attribute...?
                self._awaiting_result = self.awaiting_result
                self.awaiting_result = None
                return reply

    def ask_admin(self, ID, admin=None, force=False):
        """
        Manage admin requests.
        """
        if admin is None:
            if self.admin is None:
                return {'status': 'ok', 'value': None}
            return {'status': 'ok', 'value': ID == self.admin}
        if admin:
            if self.admin is None:
                self.admin = ID
                return {'status': 'ok'}
            elif self.admin == ID:
                return {'status': 'ok', 'msg': f'{ID} already admin'}
            elif force:
                self.admin = ID
                return {'status': 'ok', 'msg': 'Forced admin'}
            else:
                return {'status': 'error', 'msg': 'Another client is already admin'}
        else:
            if self.admin != ID:
                return {'status': 'error', 'msg': 'Already not admin'}
            self.admin = None
            return {'status': 'ok'}


class ClientProxy:

    PING_INTERVAL = 10.
    REQUEST_TIMEOUT = 10.
    NUM_RECONNECT = 3

    def __init__(self, address, API, clean=True):
        """
        Client whose instance will be hidden in the proxy class.
        address: (IP, port) to connect to
        clean: return only values and not full message (default True)
        """
        self.address = address
        self.full_address = f'tcp://{self.address[0]}:{self.address[1]}'
        self.clean = clean
        self.API = API
        self.name = self.__class__.__name__.lower()
        self.logger = logging.getLogger(self.__class__.__name__)

        # Flag for eventual lost connection
        self.connected = False
        # Flag to bootstrap the initial connection
        self.connecting = False

        # ZMQ socket
        self.socket = None

        # Unique ID assigned by server
        self.ID = None

        # This will hold the ping thread
        self.future_ping = None
        # Flag to kill the ping thread
        self._stopping = False

        atexit.register(self.shutdown)

        # zmq context
        self.context = zmq.Context()

    def connect(self, *args, admin=True, **kwargs):
        """
        Connect (or reconnect) client.
        For a first connection, the constructor parameters are sent to the server.
        """
        try:
            self.socket.close()
        except:
            pass
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(self.full_address)

        # Establish connection with the server with ID=0
        self.connecting = True
        reply = self.send_recv([0, '', args, kwargs], clean=False)
        self.connecting = False

        if reply['status'] != 'ok':
            raise RuntimeError(f'{reply["status"]} - {reply["msg"]}')

        self.connected = True

        # Connection was successful. Prepare the data pipe
        self.ID = reply['value']['ID']
        self.logger.debug(f'Connected to server as ID={self.ID}')

        # Request admin rights if needed
        reply = self.ask_admin(admin)
        if reply['status'] != 'ok':
            self.logger.warning(f'{reply["msg"]}')

        # Start ping process
        self.future_ping = Future(self._ping)

    def send_recv(self, cmd_seq, clean=None):
        """
        Send command and wait for reply.
        cmd_seq: command of the form (ID, cmd, args, kwargs)
        clean: if not None, override self.clean.
        """
        _, cmd, _, _ = cmd_seq

        retries_left = self.NUM_RECONNECT
        if not self.connecting and not self.connected:
            raise ProxyClientError('Client is not connected.')
        try:
            self.socket.send_json(cmd_seq)
        except AttributeError:
            if self.socket is None:
                # This may happen at shutdown - ignore.
                return
            else:
                raise
        except Exception as e:
            # Connection problems (e.g. the server shut down) are managed here
            self.logger.warning('Could not send command to server.')
            return {'status': 'error', 'msg': repr(e)}

        # Manage possible difficulties connecting
        poll_timeout = 1000 * self.REQUEST_TIMEOUT
        if not self.connected:
            poll_timeout /= 10
        while True:
            if (self.socket.poll(poll_timeout) & zmq.POLLIN) != 0:
                reply = self.socket.recv_json()
                break

            # If not even connected - give up
            if not self.connected:
                self.socket.setsockopt(zmq.LINGER, 0)
                self.socket.close()
                self.connecting = False
                raise ProxyClientError(f'Could not connect to server at {self.full_address}')

            self.logger.warning("No response from server")

            self.socket.setsockopt(zmq.LINGER, 0)
            self.socket.close()
            if retries_left == 0:
                self.logger.error("Server seems to be offline.")
                raise ProxyClientError(f'Could not connect to server at {self.full_address}')

            self.logger.info("Reconnecting to server")
            retries_left -= 1

            # Reconnect and send again
            self.socket = self.context.socket(zmq.REQ)
            self.socket.connect(self.full_address)
            self.socket.send_json(cmd_seq)

        if ((clean is not None) and clean) or ((clean is None) and self.clean):
            # In clean mode, we reproduce the behaviour of the remote class
            if reply['status'] == 'error':
                # Raise error if there was one
                raise RuntimeError(f'Server error: {reply["msg"]}')
            elif cmd in self.API and (not self.API[cmd]['block']):
                # Wait for non-blocking calls
                try:
                    while True:
                        reply = self.send_recv((self.ID, '^result', [], {}), clean=False)
                        if reply['status'] == 'error':
                            raise RuntimeError(reply['msg'])
                        elif reply['status'] == 'ok':
                            value = reply.get('value')
                            return value
                        time.sleep(.1)
                except KeyboardInterrupt:
                    reply = self.send_recv((self.ID, '^abort', [], {}), clean=False)
                    if reply['status'] != 'ok':
                        raise RuntimeError(reply['msg'])
            else:
                value = reply.get('value')
                return value
        return reply

    def _ping(self):
        """
        Periodic ping.
        """
        while not self._stopping:
            try:
                reply = self.send_recv([self.ID, '^ping', [], {}])
            except BaseException as error:
                self.logger.error(repr(error))
            time.sleep(self.PING_INTERVAL)

    def disconnect(self):
        """
        Inform the server that we are leaving.
        """
        try:
            self.send_recv([self.ID, '^disconnect', [], {}])
        except ProxyClientError:
            pass
        self.connected = False

    def shutdown(self):
        """
        Terminate ping thread and close socket.
        """
        self.disconnect()
        self._stopping = True
        if self.socket and not self.socket.closed:
            self.socket.close()

    def get_stats(self):
        return self.send_recv([self.ID, '^stats', [], {}])

    def get_result(self):
        return self.send_recv([self.ID, '^result', [], {}])

    def ask_admin(self, admin=None):
        """
        Send a request for admin rights.
        """
        return self.send_recv([self.ID, '^admin', [], {'admin': admin}], clean=False)


class ClientBase:

    _proxy = None

    def __init__(self, *args, admin=True, **kwargs):
        """
        Mostly empty class that will be subclassed and filled with the methods and properties identified by the
        proxycall decorators.
        The initialization parameters are used to instantiate the remote class. They are ignored if an instance already exists.
        """
        if not self._proxy:
            raise RuntimeError('Something wrong. A ClientProxy instance should be present!')
        self._proxy.connect(*args, admin=admin, **kwargs)
        self.ask_admin = self._proxy.ask_admin
        self.get_result = self._proxy.get_result
        self.get_stats = self._proxy.get_stats


class proxycall:
    """
    Decorator to tag a method or property to be exposed for remote access.
    """
    def __init__(self, admin=False, block=True, interrupt=False, **kwargs):
        """
        Decorator to tag a method or property to be exposed for remote access.
        admin: whether admin rights are required to execute command.
        block: Wait for the function to return.
        interrupt: if True, declare this method as the method to call when SIG_INT is caught on client side.
        kwargs: anything else that might be needed in the future.
        """
        self.admin = admin
        self.block = block
        self.interrupt = interrupt
        self.kwargs = kwargs

    def __call__(self, f):
        """
        Decorator call.
        This attaches a dictionary called api_call to methods and properties, which are then scanned by the proxydevice decorator.
        """
        api_info = {'admin': self.admin, 'block': self.block, 'interrupt': self.interrupt}
        api_info.update(self.kwargs)
        if type(f) is property:
            api_info['property'] = True
            f.fget.api_info = api_info
        else:
            api_info['property'] = False
            f.api_info = api_info
        return f


class proxydevice:
    """
    Decorator that does the main magic.
    """
    def __init__(self, address, clean=True):
        """
        Decorator initialization.
        address: (IP, port) of the serving address
        clean: whether the client side should receive replies in the same format as for the native class. If false,
        all methods return a dict that contain a 'status', 'value' and possibly 'msg' entry.
        """
        self.address = address
        self.clean = clean

    def __call__(self, cls):
        """
        Decorator call. This creates a ServerBase and a ClientBase subclass. The latter gets populated with all fake
        methods and properties that make calls to the server through the ClientProxy instance attached to the class as
        self._proxy.
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

        # Define server and client subclasses
        Server = type(f'{cls.__name__}ProxyServer', (ServerBase,), {})
        Client = type(f'{cls.__name__}ProxyClient', (ClientBase,), {})

        # Instantiate the client proxy and attach it to the client class
        proxy = ClientProxy(address=self.address, API=API, clean=self.clean)
        Client._proxy = proxy

        # Create all fake methods and properties for Client
        for k, api_info in API.items():
            v = getattr(cls, k)
            try:
                if type(v) is property:
                    api_info = v.fget.api_info
                    self.make_property(Client, k, v)
                    logger.debug(f'Added property {k} to client proxy.')
                else:
                    api_info = v.api_info
                    self.make_method(Client, k, v)
                    logger.debug(f'Added method {k} to client proxy.')
            except AttributeError:
                continue

        # Attach server and client objects to decorated class
        cls.Server = lambda: Server(cls=cls, API=API, address=self.address)
        cls.Client = Client
        return cls

    @staticmethod
    def make_method(obj, name, ref_method):
        """
        Adds a method called `name` to class obj. The method body forwards the request
        to the server. Information is drawn from the reference method (signature, doc).
        """

        def new_method(self, *args, **kwargs):
            return self._proxy.send_recv([self._proxy.ID, name, args, kwargs])

        new_method.__name__ = name

        s = str(inspect.signature(ref_method))
        doc = f"{name}{s}\n"
        if ref_method.__doc__ is not None:
            doc += ref_method.__doc__
        new_method.__doc__ = doc
        setattr(obj, name, new_method)

    @staticmethod
    def make_property(obj, name, ref_method):
        """
        Like make_method, but creates a property instead.
        """
        def fget(self):
            return self._proxy.send_recv([self._proxy.ID, name, [], {}])

        def fset(self, value):
            return self._proxy.send_recv([self._proxy.ID, name, [value], {}])

        fget.__name__ = name
        fset.__name__ = name
        new_prop = property(fget, fset, None, doc=ref_method.__doc__)
        setattr(obj, name, new_prop)
