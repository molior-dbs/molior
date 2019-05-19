"""
This module provides user for Molior database models
"""

from sqlalchemy import Column, String, Integer, Boolean
from .database import Base


class User(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a User.
    """

    __tablename__ = "molioruser"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    username = Column(String, nullable=False, unique=True)
    password = Column(String)
    is_admin = Column(Boolean, default=False)
