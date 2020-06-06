"""
This module provides the molior BuildTask
database model.
"""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class BuildTask(Base):
    """
    Database model for a BuildTask.
    """

    __tablename__ = "buildtask"

    id = Column(Integer, primary_key=True)
    build_id = Column(ForeignKey("build.id"))
    build = relationship("Build")
    task_id = Column(String)
