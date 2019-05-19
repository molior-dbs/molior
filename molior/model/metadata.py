"""
This module provides the molior MetaData
database model.
"""
from sqlalchemy import Column, String, Integer
from .database import Base


class MetaData(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for MetaData.
    """

    __tablename__ = "metadata"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    name = Column(String)
    value = Column(String)
