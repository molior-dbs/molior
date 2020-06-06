import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import QueuePool

from ..molior.configuration import Configuration

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

    @property
    def engine(self):
        """
        Returns the database engine.
        """
        if not self._engine:
            self._db = Configuration().database
            self._engine = create_engine("postgresql://{}".format(self._db), echo=False, poolclass=QueuePool,
                                         pool_size=200, max_overflow=100, client_encoding="utf8")
        return self._engine


if not os.environ.get("IS_SPHINX", False):
    database = Database()
