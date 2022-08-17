from datetime import datetime, timedelta
import os
import gzip
import shutil
import logging


class DataLogger:
    """
    Store data in a json "database". A new file is created every day, and the
    previous one is gzipped.
    """

    DB_FILE_FORMAT = '{0}/{1.year}_{1.month:02d}_{1.day:02d}.db'

    def __init__(self, db_path):
        """
        Manage log database.
        """
        self.db_path = db_path
        self.logger = logging.getLogger(self.__class__.__name__)

    def log(self, entry):
        """
        Add entry to log.
        """
        # add timestamp
        entry['datetime'] = datetime.now().isoformat(timespec='milliseconds')
        db_filename = self.db_filename()
        with open(db_filename, 'a') as f:
            f.write(json.dumps(entry))
        self.logger.debug(f'Added {entry}')

    def db_filename(self):
        """
        Get file name (new or old) to dump log data.
        """
        today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
        db_file = self.DB_FILE_FORMAT.format(self.db_path, today)
        if not os.path.exists(db_file):
            # A new day!
            # Zip previous one.
            yesterday = today-timedelta(days=1)
            db_yesterday = self.DB_FILE_FORMAT.format(self.db_path, yesterday)
            if not os.path.exists(db_yesterday):
                self.logger.warning(
                    f'Yesterday log file {db_yesterday} does not exist!')
            else:
                with open(db_yesterday, 'rb') as f_in:
                    with gzip.open(db_yesterday + '.gz', 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(db_yesterday)
                self.logger.info(f'File {db_yesterday} gzipped.')
        return db_file
