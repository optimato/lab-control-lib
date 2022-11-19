import experiment
from .util.datalogger import DataLogger as DataLoggerBase
from .network_conf import DATALOGGER as NET_INFO


class DataLogger(DataLoggerBase):

    DEFAULT_ADDRESS = NET_INFO['control']

    def get_tags(self):
        """
        Add tags related to current scan
        """
        tags = {}
        tags['investigation'] = experiment.INVESTIGATION or 'undefined'
        tags['experiment'] = experiment.EXPERIMENT or 'undefined'
        if experiment.SCAN is not None:
            tags['scan_number'] = experiment.SCAN.scan_number
        return tags
