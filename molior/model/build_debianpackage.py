from sqlalchemy import Column, Integer, ForeignKey, Table

from .database import Base

BuildDebianpackage = Table(
    "build_debianpackage",
    Base.metadata,
    Column("build_id", Integer, ForeignKey("build.id")),
    Column("debianpackage_id", Integer, ForeignKey("debianpackage.id")),
)
