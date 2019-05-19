"""
This module provides the molior ProjectVersion BuildVariant
database model.
"""

from sqlalchemy import Column, Integer, ForeignKey, Table, UniqueConstraint
from .database import Base

ProVerBuiVar = Table(  # pylint: disable=invalid-name
    "projectversionbuildvariant",
    Base.metadata,
    Column("buildvariant_id", Integer, ForeignKey("buildvariant.id")),
    Column("projectversion_id", Integer, ForeignKey("projectversion.id")),
    UniqueConstraint(
        "buildvariant_id", "projectversion_id", name="unique_buildvariantprojectversion"
    ),
)
