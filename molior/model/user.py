from sqlalchemy import Column, String, Integer, Boolean

from .database import Base


class User(Base):
    """
    Database model for a User.
    """

    __tablename__ = "molioruser"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    password = Column(String)
    email = Column(String)
    is_admin = Column(Boolean, default=False)
