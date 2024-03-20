"""
Data logging module

The object DataLogger provides the functionality to all drivers to add time-stamped data points
to an influxdb database (this backend could be changed easily if needed)

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""

from functools import wraps
from datetime import datetime
import logging
import importlib.util
from . import utcnow

DEFAULT_BUCKET = 'labcontrol'

logger = logging.getLogger(__name__)

# Try to import influxdb
if importlib.util.find_spec('influxdb_client') is not None:
    import influxdb_client
else:
    logger.debug("Module influxdb_client unavailable on this host")
    import json
    globals().update({'influxdb_client': None})


class DataLogger:
    """
    A data logger client with a decorator for methods that need to be logged.

    Intended usage:

    # Single instance created at module load.
    data_logger = DataLogger()

    # In a module
    from ??? import data_logger
    class A:

        @data_logger.meta(field_name='quantity_to_log', tags={"version": "1"})
        def get_quantity(self):
            return 1

        @property
        @data_logger.meta(field_name='parameter_to_log', tags={"version": "1"})
        def parameter(self):
            return self.some_parameter


    The output of each call to A.get_quantity and A.get_other_quantity will be logged, along with the parameters
    specified in the decorator.
    """

    DEFAULT_ADDRESS = None

    def __init__(self, token, address=None, bucket=None):
        """

        """
        if influxdb_client is None:
            logger.warning('Data will not be logged in a database (influxdb unavailable but in a file!')

        self.token = token
        self.address = address or self.DEFAULT_ADDRESS
        self.url = f'http://{self.address[0]}:{self.address[1]}'
        self.bucket = bucket or DEFAULT_BUCKET

        self.client = None
        self.write_api = None
        self._stop = False
        self.start()

    def meta(self, field_name, tags):
        """
        Method decorator to declare that its output is metadate to be logged.
        """

        def meta_decorator(method):
            """
            Add info to method to make it discoverable by datalog
            """

            @wraps(method)
            def logged_method(self1, *args, **kwargs):
                name = self1.name

                # Call method and get result
                t0 = datetime.utcnow()
                result = method(self1, *args, **kwargs)

                # Timestamp is mean between call before and call after
                tm = t0 + .5 * (datetime.utcnow() - t0)

                timestamp = tm.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

                all_tags = self.get_tags()
                all_tags.update(tags)

                # If result is dict, build field from this
                if type(result) is dict:
                    fields = {f'{field_name}.{k}': v for k, v in result.items()}
                else:
                    fields = {field_name: result}

                # Log this data
                self.new_entry(name=name, fields=fields, tags=all_tags, timeval=timestamp)

                return result

            return logged_method

        return meta_decorator

    def start(self):
        """
        Connect the client to the database.
        """
        if influxdb_client and not self.client:
            self.client = influxdb_client.InfluxDBClient(url=self.url, org='optimato', token=self.token)
            self.write_api = self.client.write_api(write_options=influxdb_client.client.write_api.SYNCHRONOUS)

    def get_tags(self):
        """
        To be overridden
        """
        return {}

    def new_entry(self, name, fields, tags, timeval=None):
        """
        Add the data (a dictionary of fields) and tags as a new measurement. If timeval is None (default)
        set time of the point as now.
        """
        if timeval is None:
            timeval = utcnow()

        pt = {
            "measurement": name,
            "tags": tags,
            "time": timeval,
            "fields": fields
        }

        if influxdb_client:
            self.write_api.write(bucket=self.bucket, record=influxdb_client.Point.from_dict(pt))
        else:
            line = json.dumps(pt) + '\n'
            open(f'{self.bucket}.json', 'a').write(line)