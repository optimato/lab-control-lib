"""
Proxy Device: decorators that expose a class and chose methods/properties
through network.

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

"""

import logging
import traceback
import sys

import zmq
import time
import atexit
import threading
import inspect

from .future import Future
from .logs import logger as rootlogger

logger = logging.getLogger(__name__)

class ProxyClientError(Exception):
    pass


class SocketStream:
    def __init__(self, address, to_stdout=True):
        """
        A stream-like object that published through a zmq socket.
        address: a tuple (IP, port)
        to_stdout: if True, self.write will also call stdout.write
        """
        self.address = address
        self.to_stdout = to_stdout

        self.full_address = f'tcp://*:{self.address[1]}'

        # Prepare socket
        self.stream_context = zmq.Context()
        self.stream_socket = self.stream_context.socket(zmq.PUB)
        self.stream_socket.setsockopt(zmq.LINGER, 0)
        self.stream_socket.bind(self.full_address)

    def write(self, string):
        """
        Replacement for stream.write.
        """
        self.stream_socket.send_json(string)
        if self.to_stdout:
            sys.stdout.write(string)

    def flush(self):
        if self.to_stdout:
            sys.stdout.flush()

    def __del__(self):
        try:
            self.stream_socket.unbind(self.full_address)
            self.stream_socket.close()
            self.stream_context.term()
        except:
            pass

class ProxyPrint:
    def __init__(self, stream):
        """
        A possible replacement for print that *also* prints to a given stream
        """
        self.stream = stream

    def __call__(self, *objects, sep=' ', end='\n', file=None, flush=False):

        # Print on stream
        print(*objects, sep=sep, end=end, file=self.stream, flush=flush)

        if file is not None:
            print(*objects, sep=sep, end=end, file=file, flush=flush)


class ServerBase:
    """
    Server for a wrapped class.
    """

    POLL_TIMEOUT = 100
    ESCAPE_STRING = '^'
    ADDRESS = None
    STREAM_ADDRESS = None
    API = None
    CLS = None
    RESULT_TIMEOUT = .2  # Wait time for completion of a blocking task before
                         # notifying the client that it is still running.
                         # This should not be too short to avoid rapid-fire
                         # back and forth, but should not be too long to allow
                         # for emergency stops to be requested fast enough.

    def __init__(self,
                 cls=None,
                 API=None,
                 address=None,
                 instantiate=False,
                 instance_args=None,
                 instance_kwargs=None,
                 stream_address=None):
        """
        Base class for server proxy

        Note that this is not really an abstract class. The proxydevice decorator produces a subclass
        of this class to assign a different name for clearer documentation, and attaches the defaults
        ADDRESS, API and CLS as class attributes.

        cls: The class being wrapped (defaults to self.CLS)
        API: a dictionary listing all methods to be exposed (collected through the proxycall decorator)
             defaults to self.API
        address: (IP, port) to listen on. Defaults to self.ADDRESS
        instantiate: if True, create immediately the internal instance of self.cls, using the provided args/kwargs.
        If False, instantiation will proceed with the first client connection.
        instance_args, instance_kwargs: args, kwargs to pass for class instantiation.
        stream_address: address used to send stream writes.
        """
        # This is a mechanism to give a default values to subclasses without having to pass the argument.
        self.cls = cls or self.CLS
        self.API = API or self.API
        self.address = address or self.ADDRESS
        self.stream_address = stream_address or self.STREAM_ADDRESS

        self.logger = rootlogger.getChild(self.__class__.__name__)
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
        self.awaiting_result = None
        self._awaiting_result = None   # For lingering result, after cancellation

        self.interrupt_method = None

        # To be assigned in self.activate
        self.context = None
        self.socket = None

        # Stream that can be used to pass strings asynchronously to clients.
        self.stream = None

        self.admin = None
        self._stopping = None
        atexit.register(self.stop)

        if instantiate:
            self.create_instance(args=instance_args, kwargs=instance_kwargs)

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
        except:
            pass
        self.server_future = Future(self._run)

        if self.stream_address:
            # Create the socket stream
            self.stream = SocketStream(self.stream_address)

            if self.instance is not None:
                # Replace built-in print with a print function that will also send through stream
                sys.modules[self.instance.__class__.__module__].print = ProxyPrint(self.stream)

            self.logger.info(f'Streaming on {self.stream.full_address}')

    def wait(self):
        """
        Wait until the server stops.
        """
        if self.server_future is not None and not self.server_future.done():
            self.server_future.join()

    def stop(self):
        """
        Stop the server. This signals both listening and ping threads to terminate.
        """
        del self.instance
        self._stopping = True

    def _run(self):
        """
        Prepare the server and start listening for connections.
        (runs on the separate thread)
        """
        # _stopping might have been set to True already because of instantiation failure.
        if self._stopping:
            self.logger.info('Shutting down')
            return

        self._stopping = False

        # Initialize socket for entry point
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)

        # Apparently this is needed for a clean shutdown
        self.socket.setsockopt(zmq.LINGER, 0)

        full_address = f'tcp://{self.address[0]}:{self.address[1]}'
        try:
            self.socket.bind(full_address)
        except zmq.error.ZMQError as e:
            self.logger.exception(f'Connection failed (full address: {full_address})')
            return

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
            self.context.term()

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

                if (ID == 0) or (ID not in self.clients):
                    # ID == 0 is a request from a new client and cmd is the name to identify the client.
                    reply = self.new_connection(message, ID=ID, name=cmd)
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
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
                    self.socket.send_json(reply)

        # This should delete the running instance, assuming that there are no other references to it.
        self.instance = None

    def _parse_message(self, message):
        """
        Parse the message sent by the bound client.

        There are multiple cases to consider (method / property, blocking / non-blocking)

        message is a 4-tuple of the form (ID, cmd, args, kwargs)
        """
        # Unpack command and arguments
        ID, cmd, args, kwargs = message

        self.logger.debug(f'Received command "{cmd}" from client "{self.clients[ID]["name"]}" ({ID})')

        # Manage escaped command
        if cmd.startswith(self.ESCAPE_STRING):
            cmd = cmd.lstrip(self.ESCAPE_STRING)
            return self._parse_escaped(ID, cmd, args, kwargs)

        # Manage API command
        self.logger.debug(f'Running command "{cmd}"')

        if self.instance is None:
            return {'status': 'error', 'msg': 'Instance not yet initialized'}

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
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
            else:
                # Try to call property getter
                try:
                    v = getattr(self.instance, cmd)
                    reply = {'status': 'ok', 'value': v}
                except BaseException as error:
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
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
                    reply = {'status': 'error', 'msg': traceback.format_exc()}
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
                        reply = {'status': 'error', 'msg': traceback.format_exc()}

        return reply

    def _run_awaiting(self, method, **kwargs):
        """
        Wrapper to catch errors in non-blocking method call.
        """
        try:
            result = method(*kwargs['args'], **kwargs['kwargs'])
            return result
        except BaseException as error:
            return 'Error: ' + traceback.format_exc()

    def create_instance(self, args=None, kwargs=None):
        """
        Create the instance of the wrapped class, using args and kwargs as initialization parameters
        """
        args = args or ()
        kwargs = kwargs or {}

        # Instantiate the wrapped object
        try:
            self.instance = self.cls(*args, **kwargs)
        except BaseException as error:
            self.logger.critical('Class instantiation failed!', exc_info=True)
            self._stopping = True
            self.instance = None
            raise

        if self.stream is not None:
            # Replace built-in print with a print function that will also send through stream
            print(self.instance.__class__.__module__)
            sys.modules[self.instance.__class__.__module__].print = ProxyPrint(self.stream)

        # Look for an interrupt method (will be called with an ^abort command)
        self.interrupt_method = None
        for cmd, api_info in self.API.items():
            if api_info.get('interrupt'):
                self.interrupt_method = getattr(self.instance, cmd)
                self.logger.info(f'Method {cmd} is the abort call.')
        self.logger.info('Created instance of wrapped class.')

    def new_connection(self, message, ID, name=None):
        """
        Manage new client.
        """
        name = name or f'#{ID}'
        _, _, args, kwargs = message

        if ID == 0:
            # Find smallest free ID
            ID = 1
            while ID in self.clients:
                ID += 1

        # Set statistics
        self.clients[ID] = {'name': name,
                            'startup': time.time(),
                            'reply_number': 0,
                            'total_reply_time': 0.,
                            'total_reply_time2': 0.,
                            'min_reply_time': 100.,
                            'max_reply_time': 0.,
                            'last_reply_time': 0.}

        if self.instance is None:
            # First connection! We create the class instance
            # Using the passed parameters.
            Future(target=self.create_instance, args=args, kwargs=kwargs)

        reply = {'status': 'ok', 'value': {'ID': ID}}
        self.logger.info(f'Client #{ID} ({name}) connected.')
        return reply

    def _parse_escaped(self, ID, cmd, args, kwargs):
        """
        Escaped commands.
        """
        #
        # PING
        #
        if cmd.lower() == 'ping':
            return {'status': 'ok'}

        #
        # DISCONNECT
        #
        if cmd.lower() == 'disconnect':
            if self.admin == ID:
                self.admin = None
            return {'status': 'ok'}

        #
        # KILL
        #
        if cmd.lower() == 'kill':
            if ID != self.admin:
                return {'status': 'error', 'msg': 'Only admin can kill the server.'}

            def will_stop():
                time.sleep(.5)
                self.stop()

            Future(target=will_stop)
            return {'status': 'ok'}

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
        # LOGLEVEL
        #
        if cmd.lower() =='loglevel':
            try:
                self.logger.setLevel(kwargs['level'])
            except BaseException as error:
                return {'status': 'error', 'msg': traceback.format_exc()}
            return {'status': 'ok'}

        #
        # RESULT
        #
        if cmd.lower() == 'result':
            # Get awaiting result or possibly the lingering one.
            awaiting_result = self.awaiting_result if self.awaiting_result is not None else self._awaiting_result
            if awaiting_result is None:
                return {'status': 'error', 'msg': 'No awaiting result found.'}
            else:
                try:
                    result = awaiting_result.result(timeout=self.RESULT_TIMEOUT)
                except TimeoutError:
                    return {'status': 'waiting', 'msg': 'Task is still running'}
                except BaseException as error:
                    return {'status': 'error', 'msg': traceback.format_exc()}
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
                    return {'status': 'error', 'msg': traceback.format_exc()}
                finally:
                    self.awaiting_result = None
                self.logger.warning('ABORT signal received but task was complete')
                return {'status': 'ok', 'value': result, 'msg': 'Task complete'}
            else:
                if self.interrupt_method:
                    try:
                        result = self.interrupt_method()
                    except BaseException as error:
                        return {'status': 'error', 'msg': traceback.format_exc()}
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
                return {'status': 'ok', 'msg': 'Already not admin'}
            self.admin = None
            return {'status': 'ok'}


class ClientProxy:

    PING_INTERVAL = 10.
    REQUEST_TIMEOUT = 10.
    NUM_RECONNECT = 1000000 # ~= infinity

    def __init__(self,
                 address,
                 API,
                 name=None,
                 clean=True,
                 cls_name=None,
                 stream_address=None):
        """
        Client whose instance will be hidden in the proxy class.
        address: (IP, port) to connect to
        API: the list of proxycalls
        name: identifier for this proxy
        clean: return only values and not full message (default True)
        cls_name:
        stream_address: address of the stream to subscribe if needed.
        """
        self.address = address
        if address is not None:
            self.full_address = f'tcp://{self.address[0]}:{self.address[1]}'
        else:
            self.full_address = None
        self.clean = clean
        self.API = API
        self.cls_name = cls_name
        self.stream_address = stream_address
        self.name = name or self.__class__.__name__.lower()
        # self.logger = rootlogger.getChild(self.__class__.__name__)
        self.logger = rootlogger.getChild('.'.join([self.cls_name, self.__class__.__name__]))

        # Flag for eventual lost connection
        self.connected = False
        # Flag to bootstrap the initial connection
        self.connecting = False

        # ZMQ socket
        self.socket = None

        # Unique ID assigned by server
        self.ID = None

        # A lock for thread-safe send-recv
        self.send_recv_lock = threading.Lock()

        # This will hold the ping thread
        self.future_ping = None
        self._last_ping = 0.

        # This will hold the stream subscription thread
        self.future_streams = None

        # Flag to kill the ping and streaming threads
        self._stopping = threading.Event()

        atexit.register(self.shutdown)

        # zmq context
        self.context = zmq.Context()

    def connect(self, args, kwargs, address=None, admin=True):
        """
        Connect (or reconnect) client.
        For a first connection, the constructor parameters args and kwargs are sent to the server.
        """
        self.address = address or self.address
        self.full_address = f'tcp://{self.address[0]}:{self.address[1]}'

        try:
            self.socket.close()
        except:
            pass
        self.socket = self.context.socket(zmq.REQ)

        # Apparently this is needed for a clean shutdown
        self.socket.setsockopt(zmq.LINGER, 0)

        self.socket.connect(self.full_address)

        # Establish connection with the server with ID=0
        self.connecting = True
        try:
            reply = self.send_recv([0, self.name, args, kwargs], clean=False)
        except ProxyClientError:
            self._stopping.set()
            if self.future_ping:
                self.future_ping.join()
            self.socket.close()
            self.context.term()
            raise

        self.connecting = False

        if reply['status'] != 'ok':
            raise RuntimeError(f'{reply["status"]} - {reply["msg"]}')

        self.connected = True

        # Connection was successful. Prepare the data pipe
        self.ID = reply['value']['ID']
        self.logger.info(f'Connected to {self.cls_name} proxy (client name={self.name}, ID={self.ID})')

        # Request admin rights if needed
        reply = self.ask_admin(admin)
        if reply['status'] != 'ok':
            self.logger.warning(f'{reply["msg"]}')

        # Start ping process
        self.future_ping = Future(self._ping)

        # Starting stream subscriber
        if self.stream_address:
            self.future_streams = Future(self._subscribe_to_stream)
        else:
            self.future_streams = None

    def send_recv(self, cmd_seq, clean=None):
        """
        Send command and wait for reply.
        cmd_seq: command of the form (ID, cmd, args, kwargs)
        clean: if not None, override self.clean.
        """
        _, cmd, _, _ = cmd_seq

        ###################
        # Send command
        ###################
        with self.send_recv_lock:

            if not self.connecting and not self.connected:
                raise ProxyClientError('Client is not connected.')
            try:
                # Many things can happen here:
                # 1) Sending worked and reply (below) also -> fine
                # 2) Sending "worked" but there won't be a reply -> the while loop will take over
                # 3) The socket doesn't even exist: we're probably shutting down
                # 4) Sending otherwise didn't work -> hopefully this won't happen
                self.logger.debug(f'Sending command {cmd_seq}')
                self.socket.send_json(cmd_seq)
            except AttributeError:
                # We are here if self.socket is None

                if self.socket is None:
                    # This may happen at shutdown - ignore.
                    return
                else:
                    # This should never happen
                    raise
            except Exception as e:
                # We are here if the socket cannot send. Probably because we already
                # send something and we are waiting for the reply.

                self.logger.debug(f'Exception (socket state)')

                if cmd == '^ping':
                    # Most likely no big deal.
                    return {'status': 'ok', 'msg': 'probably waiting for another call.'}
                elif cmd == '^disconnect':
                    # Server might have shut down - just leave.
                    return {'status': 'ok', 'msg': 'probably server has shut down.'}
                elif cmd == '^abort':
                    # Emergency, we need to try harder. We wait for the reply and send
                    # immediately the abort request.
                    self.logger.warning('Abort call: waiting for server to reply.')
                    for i in range(100):
                        if (self.socket.poll(500) & zmq.POLLIN) != 0:
                            reply = self.socket.recv_json()
                            break
                    self.logger.warning('Abort call: server replied. Now sending.')
                    self.socket.send_json(cmd_seq)
                else:
                    # Connection problems (e.g. the server shut down) are managed here
                    self.logger.exception(f'Could not send command "{cmd_seq}" to server at {self.full_address}.')
                    return {'status': 'error', 'msg': traceback.format_exc()}

            ###################
            # Receive reply
            ###################

            retries = 0
            poll_timeout = 1000 * self.REQUEST_TIMEOUT

            # Poll faster for the first connection attempt
            if not self.connected:
                poll_timeout /= 10

            while True:

                if self._stopping.is_set():
                    return

                # Ideal case: there's a reply
                if (self.socket.poll(poll_timeout) & zmq.POLLIN) != 0:
                    reply = self.socket.recv_json()
                    self.logger.debug(f'Received reply {reply}')
                    if retries > 0:
                        retries = 0
                        self.logger.info(f"Reconnected to server")
                    break

                # We get here because polling failed.

                # If not even connected - give up
                if not self.connected:
                    self.socket.setsockopt(zmq.LINGER, 0)
                    self.socket.close()
                    self.connecting = False
                    raise ProxyClientError(f'Could not connect to server at {self.full_address}')

                if cmd == '^disconnect':
                    # No point trying, server might be already dead
                    return

                # We were connected but there was no reply. We need to keep trying
                self.socket.setsockopt(zmq.LINGER, 0)
                self.socket.close()
                if retries == self.NUM_RECONNECT:
                    self.logger.error("Server seems to be offline.")
                    self.shutdown()
                    raise ProxyClientError(f'Could not connect to server at {self.full_address}')

                retries += 1
                self.logger.info(f"Trying to reconnect to server (attempt {retries})")
                self.logger.debug(f"Full address: {self.full_address}, client ID {self.ID}")

                # Reconnect and send again
                self.socket = self.context.socket(zmq.REQ)
                self.socket.connect(self.full_address)
                self.socket.send_json(cmd_seq)

        ###################
        # Manage reply
        ###################

        if ((clean is not None) and clean) or ((clean is None) and self.clean):
            self.logger.debug(f'Managing reply in clean mode.')
            if reply['status'] == 'error':
            # In clean mode, we reproduce the behaviour of the remote class
                # Raise error if there was one
                raise RuntimeError(f'Server error: {reply["msg"]}')
            elif (cmd in self.API) and (not self.API[cmd]['block']):
                # Wait for non-blocking calls (cmd == '' corresponds to the case where object instantiation
                # might take a lot of time)
                emergency_stop = False
                self.logger.debug(f'Managing blocking command.')
                while True:
                    # The flag is set to true if a keyboard interrupt was caught
                    # during the previous iteration of the loop.
                    if emergency_stop:
                        reply = self.send_recv((self.ID, '^abort', [], {}), clean=False)
                        if reply['status'] != 'ok':
                            raise RuntimeError(reply['msg'])
                        return reply
                    try:
                        # The call will return after Server.RESULT_TIMEOUT seconds.
                        # or before if the result is available.
                        self.logger.debug(f'Sending result request.')
                        reply = self.send_recv((self.ID, '^result', [], {}), clean=False)
                        self.logger.debug(f'Result is {reply}')
                    except KeyboardInterrupt:
                        emergency_stop = True
                        continue
                    if reply['status'] == 'error':
                        raise RuntimeError(reply['msg'])
                    elif reply['status'] == 'ok':
                        value = reply.get('value')
                        self.logger.debug(f'We are out of blocking loop')
                        return value
            else:
                value = reply.get('value')
                return value
        return reply

    def _ping(self):
        """
        Periodic ping.
        """
        while True:
            if self._stopping.wait(self.PING_INTERVAL):
                return
            try:
                reply = self.send_recv([self.ID, '^ping', [], {}], clean=False)
                if reply['status'] == 'ok':
                    self._last_ping = time.time()
            except BaseException as error:
                self.logger.exception('Ping error.')

    def _subscribe_to_stream(self):
        """
        Printing out stdout and stdin form the server asynchronously.
        """
        if not self.stream_address:
            self.logger.info('Will not stream from server: stream_address is None.')
            return
        full_address = 'tcp://{0}:{1}'.format(*self.stream_address)
        stream_context = zmq.Context()
        stream_socket = stream_context.socket(zmq.SUB)
        stream_socket.setsockopt(zmq.SUBSCRIBE, b'')
        stream_socket.connect(full_address)

        while not self._stopping.is_set():
            try:
                if (stream_socket.poll(500.) & zmq.POLLIN) == 0:
                    continue
                string = stream_socket.recv_json()
                sys.stdout.write(string)
                sys.stdout.flush()
            except BaseException as error:
                self.logger.exception('Streaming error.')

        try:
            stream_socket.close()
            stream_context.term()
        except:
            pass

    def disconnect(self):
        """
        Inform the server that we are leaving.
        """
        try:
            self.send_recv([self.ID, '^disconnect', [], {}])
        except ProxyClientError:
            pass
        self.connected = False

    def kill(self):
        """
        Ask the server to shut itself down.
        """
        self.send_recv([self.ID, '^kill', [], {}])
        try:
            self.shutdown()
        except ProxyClientError:
            pass

    def shutdown(self):
        """
        Terminate ping thread and close socket.
        """
        self.disconnect()
        self._stopping.set()
        if self.future_ping:
            self.future_ping.join()
        self.socket.close()
        self.context.destroy()

    def get_stats(self):
        return self.send_recv([self.ID, '^stats', [], {}])

    def get_result(self):
        return self.send_recv([self.ID, '^result', [], {}])

    def ask_admin(self, admin=None, force=False):
        """
        Send a request for admin rights.
        """
        return self.send_recv([self.ID, '^admin', [], {'admin': admin, 'force': force}], clean=False)

    def set_log_level(self, level):
        """
        Set the log level of the proxy server.
        """
        return self.send_recv([self.ID, '^loglevel', [], {'level': level}], clean=False)

    @property
    def running(self):
        return (self._last_ping + self.PING_INTERVAL) > time.time()


class ClientBase:

    _proxy = None
    _address = None
    _API = None
    _clean = None
    _cls_name = None
    _stream_address = None

    def __init__(self, address=None, admin=True, name=None, args=None, kwargs=None, stream_address=None):
        """
        Mostly empty class that will be subclassed and filled with the methods and properties identified by the
        proxycall decorators.
        The initialization parameters are used to instantiate the remote class. They are ignored if an instance already exists.
        """
        args = args or ()
        kwargs = kwargs or {}
        stream_address = stream_address or self._stream_address
        self.name = self.__class__.__name__
        self.client_name = name or self.name
        self._proxy = ClientProxy(address=self._address, API=self._API, name=self.client_name,
                                  clean=self._clean, cls_name=self._cls_name, stream_address=stream_address)
        self._proxy.connect(args, kwargs, address=address, admin=admin)
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
    def __init__(self, address=None, clean=True, stream_address=None):
        """
        Decorator initialization.
        address: (IP, port) of the serving address. If None, will have to be provided as an argument
        clean: whether the client side should receive replies in the same format as for the native class. If false,
        all methods return a dict that contain a 'status', 'value' and possibly 'msg' entry.
        stream_address is the address to publish captured stdout and stderr
        """
        self.address = address
        self.clean = clean
        self.stream_address = stream_address

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

        # Define server subclass and set default values
        Server = type(f'{cls.__name__}ProxyServer', (ServerBase,), {})
        Server.ADDRESS = self.address
        Server.STREAM_ADDRESS = self.stream_address
        Server.API = API
        Server.CLS = cls

        # Define client subclass
        Client = type(f'{cls.__name__}ProxyClient', (ClientBase,), {})

        # Attach parameters needed for proxy instantiation.
        Client._address = self.address
        Client._API = API
        Client._clean = self.clean
        Client._cls_name = cls.__name__
        Client._stream_address = self.stream_address

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
        cls.Server = Server
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
