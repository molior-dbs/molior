"""
This module provides the molior BuildOrder
relation table.
"""

from sqlalchemy import Column, Integer, ForeignKey, Table, UniqueConstraint
from .database import Base

BuildOrder = Table(  # pylint: disable=invalid-name
    "buildorder",
    Base.metadata,
    Column("build_id", Integer, ForeignKey("build.id")),
    Column("sourcerepository", Integer, ForeignKey("sourcerepository.id")),
    Column("dependency", Integer, ForeignKey("sourcerepository.id")),
    UniqueConstraint("sourcerepository", "dependency", name="unique_buildorder"),
)
