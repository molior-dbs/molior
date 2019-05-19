"""
This module provides the molior ProjectVersionDependency
database model.
"""
from sqlalchemy import Column, Integer, ForeignKey, Table, UniqueConstraint
from .database import Base

ProjectVersionDependency = Table(  # pylint: disable=invalid-name
    "projectversiondependency",
    Base.metadata,
    Column("projectversion_id", Integer, ForeignKey("projectversion.id")),
    Column("dependency_id", Integer, ForeignKey("projectversion.id")),
    UniqueConstraint(
        "projectversion_id", "dependency_id", name="unique_projectversiondepedency"
    ),
)
