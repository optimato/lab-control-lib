from functools import wraps
from datetime import datetime
import logging
import time
import importlib.util
from .network_conf import DATALOGGER as NET_INFO
from .util import utcnow
from .util.future import Future

DEFAULT_MAX_GAP = 30.
DEFAULT_DATABASE = 'labcontrol'

logger = logging.getLogger(__name__)

# Try to import influxdb
if importlib.util.find_spec('influxdb') is not None:
    import influxdb
else:
    logger.debug("Module influxdb unavailable on this host")
    import json
    globals().update({'influxdb': None})


class DataLogger:
    """
    A data logger client with a decorator for methods that need to be logged.

    Intended usage:

    class A:
        # The data_logger instance is a class attribute
        data_logger = DataLogger()

        def __init__(self):
            # connection to the database only at the instance creation of A
            self.data_logger.start()

        @data_logger.meta(field_name='quantity_to_log', tags={"version": "1"})
        def get_quantity(self):
            return 1

        @data_logger.meta(field_name='quantity_to_log_also_at_regular_interval', tags={"version": "1"}, interval=30)
        def get_other_quantity(self):
            return 2

    The output of each call to A.get_quantity and A.get_other_quantity will be logged, along with the parameters
    specified in the decorator. In addition A.get_other_quantity will be called (on a separate thread) every 30 seconds.
    """

    DEFAULT_ADDRESS = NET_INFO['control']

    def __init__(self, address=None, database=None):
        """

        """
        if influxdb is None:
            logger.warning('Data will not be logged in a database (influxdb unavailable but in a file!')

        self.address = address or self.DEFAULT_ADDRESS
        self.db = database or DEFAULT_DATABASE

        self.client = None
        self.schedule = []
        self.futures = []
        self._stop = False

        # Create decorator class. This needs to be done here because the decorator
        # is linked to this instance.

        class MetaDecorator:
            """
            Method decorator to declare that its output is metadate to be logged.
            """

            def __init__(her, field_name, tags, interval=None):
                """
                Gather metadata for logging

                field_name: that name attached to the output of the method
                tags: additional tags describing this method / driver
                interval: time interval in seconds for automatic logging. If None, no automatic logging.
                """
                her.field_name = field_name
                her.tags = tags
                her.interval = interval

            def __call__(her, method):
                """
                Add info to method to make it discoverable by datalog
                """
                @wraps(method)
                def logged_method(him, *args, **kwargs):
                    name = him.name
                    # Call method and get result
                    t0 = datetime.utcnow()
                    result = method(him, *args, **kwargs)

                    # Timestamp is mean between call before and call after
                    tm = t0 + .5*(datetime.utcnow()-t0)

                    timestamp = tm.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

                    # Log this data
                    self.new_entry(name=name, fields={her.field_name: result}, tags=her.tags, timeval=timestamp)

                    return result

                if her.interval:
                    # We keep track of the method name (the method itself is unbound at this point)
                    self.schedule.append((logged_method.__name__, her.interval))

                return logged_method

        self.meta = MetaDecorator

    def start(self, instance):
        """
        Connect the client to the database.
        """
        if influxdb and not self.client:
            self.client = influxdb.InfluxDBClient(host=self.address[0], port=self.address[1])
            self.client.switch_database(self.db)

        for method_name, interval in self.schedule:
            method = getattr(instance, method_name)
            self.futures.append(Future(target=self._run_periodically, args=(method, interval)))

    def stop(self):
        self._stop = True

    def _run_periodically(self, method, interval):
        """
        Call [method] every [interval] seconds. Runs forever.
        """
        while not self._stop:
            try:
                method()
            except:
                pass
            time.sleep(interval)

    def new_entry(self, name, fields, tags, timeval=None):
        """
        Add the data (a dictionary of fields) and tags as a new measurement. If timeval is None (default)
        set time of the point as now.
        """
        if timeval is None:
            timeval = utcnow()

        json_body = [
            {
              "measurement": name,
              "tags": tags,
              "time": timeval,
              "fields": fields
             }
           ]

        if influxdb:
            self.client.write_points(json_body)
        else:
            line = json.dumps(json_body) + '\n'
            open(f'{self.db}.json', 'a').write(line)
