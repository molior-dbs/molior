"""
This module provides the molior Source Repository Project Version
relation table.
"""

from sqlalchemy import Column, Integer, ForeignKey, Table, UniqueConstraint
from .database import Base

SouRepProVer = Table(  # pylint: disable=invalid-name
    "sourcerepositoryprojectversion",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("sourcerepository_id", Integer, ForeignKey("sourcerepository.id")),
    Column("projectversion_id", Integer, ForeignKey("projectversion.id")),
    UniqueConstraint(
        "sourcerepository_id",
        "projectversion_id",
        name="unique_sourcerepositoryprojectversion",
    ),
)
