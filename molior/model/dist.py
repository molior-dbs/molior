"""
This module provides the molior Distribution
database model.
"""
from sqlalchemy import Column, String, Integer
from .database import Base


class Distribution(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a DistRelease.
    """

    __tablename__ = "distribution"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    name = Column(String)
