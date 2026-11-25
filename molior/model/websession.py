from sqlalchemy import Column, String, Integer, DateTime

from .database import Base


class WebSession(Base):
    """
    A login session of the web UI or the API.

    The session cookie holds a random value; only its sha256 is stored, so the
    database does not contain values that log in. Logout deletes the rows.
    """

    __tablename__ = "websession"

    id = Column(Integer, primary_key=True)
    token = Column(String, nullable=False, unique=True)     # sha256 of the cookie value
    username = Column(String, nullable=False, index=True)   # not a foreign key: admin is not always in molioruser
    created = Column(DateTime(timezone=True), nullable=False)
    expires = Column(DateTime(timezone=True), nullable=False)
