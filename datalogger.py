"""
Data logging

This file is part of labcontrol
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
from . import manager
from .util import datalogger as dl
from .network_conf import DATALOGGER as NET_INFO
from . import config, THIS_HOST

__all__ = ['datalogger']


class DataLogger(dl.DataLogger):

    DEFAULT_ADDRESS = NET_INFO['control']

    def __init__(self, address=None):
        """
        Initilization
        """
        influxdb_token = config.get('influxdb_token')
        if influxdb_token is None:
            dl.logger.error('Influxdb token not found.')
        super().__init__(address=address, token=influxdb_token)

    def get_tags(self):
        """
        Add tags related to current scan
        """
        from . import manager
        man = manager.getManager()

        if man is None:
            tags = {'host': THIS_HOST}
        else:
            tags = {'investigation': man.investigation or 'undefined',
                    'experiment': man.experiment or 'undefined',
                    'scan_name': man.scan_name or 'undefined',
                    'host': THIS_HOST}
        return tags


datalogger = DataLogger()
