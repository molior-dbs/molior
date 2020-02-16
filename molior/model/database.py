import os
import yaml

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import QueuePool

from molior.app import logger

CONFIG_PATH = "/etc/molior/molior.yml"

Base = declarative_base()
database = None


class Session:
    def __enter__(self):
        maker = sessionmaker(bind=database.engine)
        self.session = maker()
        return self.session

    def __exit__(self, type, value, traceback):
        self.session.close()


class Database(object):
    """
    Provides the database base functions.
    """

    def __init__(self):
        self._engine = None
        self._db = ""

        self._connection = None

        if not os.path.exists(CONFIG_PATH):
            logger.error("Could not find molior database configuration: '%s'", CONFIG_PATH)

    def _connect(self):
        """
        Connects to the database.
        """

        self._engine = create_engine(
            "postgresql://{}".format(self._db),
            echo=False,
            poolclass=QueuePool,
            pool_size=200,
            max_overflow=100,
            client_encoding="utf8",
        )

    def _read_config(self):
        """
        Reads host, dbname, dbuser and dbpass from
        config file.
        """
        config_file = open(CONFIG_PATH, "r")
        config_yaml = yaml.load(config_file)
        self._db = config_yaml["database"]

    @property
    def engine(self):
        """
        Returns the database engine.
        """
        if not self._engine:
            self._read_config()
            self._connect()
        return self._engine


if not os.environ.get("IS_SPHINX", False):
    database = Database()
