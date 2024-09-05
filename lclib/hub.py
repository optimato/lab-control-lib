"""
Master hub and metadata management

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import time
import threading

from . import (get_config,
               HUB_ADDRESS,
               _driver_classes,
               client_or_None,
               register_driver,
               proxycall,
               proxydevice)
from .util import Future, now
from .base import DriverBase
from .logs import logging_muted

_client = []


def getHub():
    """
    A convenience function to return the current client (or a new one) for the Manager daemon.
    """
    if _client and _client[0]:
        return _client[0]
    d = client_or_None('manager', admin=False, client_name=f'client-{get_config()["this_host"]}')
    _client.clear()
    _client.append(d)
    return d


@register_driver
@proxydevice(address=HUB_ADDRESS)
class Hub(DriverBase):
    """
    Device supervisor and metadata collector.
    """

    DEFAULT_CONFIG = DriverBase.DEFAULT_CONFIG.copy()

    CLIENT_PING_INTERVAL = 10

    def __init__(self, lab_name):
        """
        Device supervisor and metadata collector.

        The Hub driver keeps clients connected to all available devices, and attempts
        periodically to connect to those that are known but unavailable.
        The Hub can request and collect metadata *concurrently* from all available drivers.
        See `request_meta` and `return_meta` for an explanation of the metadata collection
        mechanism.

        The Hub also has the capability to spawn and kill drivers.
        """
        super().__init__()

        self.requests = {}      # Dictionary to accumulate requests in case many are made before returning
        self.stop_flag = threading.Event()
        self.clients = {}

        # HACK (kind of): On the process where this class is instantiated, getHub must return this instance, not a client.
        global _client
        _client.clear()
        _client.append(self)

        # self also instead of "client to self"
        self.clients['hub'] = self

        # Start client monitoring loop
        self.clients_loop_future = Future(self.clients_loop)

    def clients_loop(self):
        """
        A loop running on a thread monitoring the health of the driver connections
        """
        while True:
            # Stop if asked
            if self.stop_flag.is_set():
                break

            # Loop through all registered driver classes
            for name in _driver_classes.keys():

                # Skip self
                if name.lower() == self.name.lower():
                    continue

                # If client does not exist
                if name not in self.clients:

                    # Attempt client instantiation
                    with logging_muted():
                        client = client_or_None(name, admin=False, client_name='hub_loop', keep_trying=True)

                        # Store client
                        self.clients[name] = client
                else:
                    try:
                        cl = self.clients[name]
                        cl.conn.ping()
                    except (EOFError, TimeoutError):
                        # Client is disconnected but will keep trying to reconnect
                        self.logger.warning(f'Ping to client {name} failed.')
                        pass

            # Wait a bit for the next pings
            if self.stop_flag.wait(self.CLIENT_PING_INTERVAL):
                break

        self.logger.info('Exiting client connection loop.')

    def fetch_meta(self, name):
        """
        Method run on a short-lived thread just the time to fetch metadata.
        """
        client = self.clients.get(name)
        if client is None or not client.connected:
            self.logger.warning(f'Client {name}: no metadata available.')
            return None
        t0 = time.time()
        meta = client.get_meta()
        dt = time.time() - t0
        self.logger.debug(f'{name} : metadata collection completed in {dt * 1000:.3g} ms')
        return {'meta':meta, 'time': dt}

    @proxycall()
    def request_meta(self, request_ID=None, exclude_list=[]):
        """
        Request metadata from all connected clients.

        This method starts one thread (`Future` per client) and returns immediately. The metadata itself will be
        obtained when calling return_meta.

        Args:
            request_ID: a (hopefully unique) ID to tag and store the request until self.return_meta is called. It can be None.
            exclude_list: a list of clients to exclude for the metadata requests.
        Returns:
            None
        """
        # Check for duplicate
        duplicate = self.requests.get(request_ID, None)
        if duplicate is not None:
            self.logger.warning(f'Requests ID {request_ID} has not been claimed and will be overwritten.')

        # Fetch metadata on separate threads
        self.requests[request_ID] = {name:Future(self.fetch_meta, (name,)) for name in self.clients.keys() if name not in exclude_list}
        return

    @proxycall()
    def return_meta(self, request_ID=None):
        """
        Return the metadata that has been accumulated since the last call to request_meta.

        Args:
            request_ID: The ID of the request made.

        Returns:
            A dictionary with all metadata.
        """
        if request_ID not in self.requests:
            self.logger.error(f'Unknown request ID {request_ID}!')

        # Pop the request
        request = self.requests.pop(request_ID, {})
        if not request:
            self.logger.warning(f'Empty request: {request_ID}!')

        # Grab all available metadata
        meta = {}
        times = {}
        for name, future in request.items():
            if not future.done():
                self.logger.warning(f'{name}: metadata collection not completed in time.')
            else:
                result = future.result()
                if result is not None:
                    # TODO: some diagnostics using the times dictionary
                    meta[name] = result['meta']
                    times[name] = result['time']

        return meta

    @proxycall(admin=True)
    def killall(self, components=None):
        """
        Kill all servers - except self!

        Args:
            components: if not None, kill only listed components. Default is None - kill all.
        """
        if components is None:
            components = self.clients.keys()

        for name in components:
            try:
                c = self.clients.pop(name)
            except KeyError:
                self.logger.error(f'Unknown component {name}!')
                continue
            if name == self.name:
                # We don't kill ourselves
                continue
            c.ask_admin(True, True)
            c.kill_server()
            del c
            self.logger.info(f'{name} killed.')

    def shutdown(self):
        """
        Clean up
        """
        self.stop_flag.set()
        m =  getHub()
        if m:
            del m
        self.clients_loop_future.join()

    @proxycall()
    def status(self):
        """
        Current status of the system.
        """
        # Number of connected clients
        Ntotal = len(self.clients)
        Nconnected = len([c for n, c in self.clients.items if c.connected])
        stats = self.get_stats()
        return {'clients': Ntotal, 'connected': Nconnected, 'stats': stats}

    @proxycall()
    def get_stats(self):
        """
        Compute and return communication statistics for currently connected clients.
        """
        stats = {}
        for name, c in self.clients.items():
            try:
                if not c.connected:
                    continue
                raw_stats = c.stats
            except AttributeError:
                # c could be self
                continue
            N = raw_stats['reply_number']
            if N == 0:
                # No stats
                stats[name] = {'avg': None,
                            'var': None,
                            'min': None,
                            'max': None,
                            'N': 0}
                continue
            avg = raw_stats['total_reply_time']/N
            var = raw_stats['total_reply_time2']/N - avg**2
            client_stats = {'avg': avg,
                            'var': var,
                            'min': raw_stats['min_reply_time'],
                            'max': raw_stats['max_reply_time'],
                            'N': N}
            stats[name] = client_stats
        return stats
