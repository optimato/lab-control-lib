from . import workflow
from .util.datalogger import DataLogger as DataLoggerBase
from .network_conf import DATALOGGER as NET_INFO
from . import config

class DataLogger(DataLoggerBase):

    DEFAULT_ADDRESS = NET_INFO['control']

    def __init__(self, address=None):
        """
        Initilization
        """
        super().__init__(address=address, token=config['influxdb_token'])

    def get_tags(self):
        """
        Add tags related to current scan
        """
        workflow.connect()

        tags = {'investigation': workflow.experiment.investigation or 'undefined',
                'experiment': workflow.experiment.experiment or 'undefined',
                'scan_name': workflow.experiment.scan_name or 'undefined'}
        return tags
