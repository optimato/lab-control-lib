from . import workflow
from .util import datalogger
from .network_conf import DATALOGGER as NET_INFO
from . import config, THIS_HOST

__all__ = ['datalogger']


class DataLogger(datalogger.DataLogger):

    DEFAULT_ADDRESS = NET_INFO['control']

    def __init__(self, address=None):
        """
        Initilization
        """
        influxdb_token = config.get('influxdb_token')
        if influxdb_token is None:
            datalogger.logger.error('Influxdb token not found.')
        super().__init__(address=address, token=influxdb_token)

    def get_tags(self):
        """
        Add tags related to current scan
        """
        workflow.connect()

        tags = {'investigation': workflow.experiment.investigation or 'undefined',
                'experiment': workflow.experiment.experiment or 'undefined',
                'scan_name': workflow.experiment.scan_name or 'undefined',
                'host': THIS_HOST}
        return tags


datalogger = DataLogger()