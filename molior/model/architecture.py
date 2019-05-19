"""
This module provides the molior Architecture database model.
"""

from sqlalchemy import Column, String, Integer
from .database import Base


class Architecture(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for an architecture.
    """

    __tablename__ = "architecture"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    name = Column(String)
