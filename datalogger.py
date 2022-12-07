from . import workflow
from .util.datalogger import DataLogger as DataLoggerBase
from .network_conf import DATALOGGER as NET_INFO


class DataLogger(DataLoggerBase):

    DEFAULT_ADDRESS = NET_INFO['control']

    def get_tags(self):
        """
        Add tags related to current scan
        """
        workflow.connect()

        tags = {}
        tags['investigation'] = workflow.experiment.investigation or 'undefined'
        tags['experiment'] = workflow.experiment.experiment or 'undefined'
        tags['scan_name'] = workflow.experiment.scan_name or 'undefined'
        return tags
