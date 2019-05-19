"""
This module provides the molior BuildTask
database model.
"""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base
from .build import Build


class BuildTask(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a BuildTask.
    """

    __tablename__ = "buildtask"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    build_id = Column(ForeignKey("build.id"))
    build = relationship(Build)
    task_id = Column(String)
