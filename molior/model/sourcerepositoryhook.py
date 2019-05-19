"""
This module provides the molior SourceRepositoryHook
relation table.
"""

from sqlalchemy import Column, Integer, ForeignKey, Table, UniqueConstraint
from .database import Base

SourceRepositoryHook = Table(  # pylint: disable=invalid-name
    "sourcerepositoryhook",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("sourcerepository_id", Integer, ForeignKey("sourcerepository.id")),
    Column("hook_id", Integer, ForeignKey("hook.id")),
    UniqueConstraint(
        "sourcerepository_id", "hook_id", name="unique_sourcerepositoryhook"
    ),
)
