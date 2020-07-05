from sqlalchemy import Column, String, Integer, Boolean
from sqlalchemy.orm import relationship

from .database import Base


class Project(Base):
    __tablename__ = "project"

    id = Column(Integer, primary_key=True)
    is_mirror = Column(Boolean, default=False)
    is_basemirror = Column(Boolean, default=False)
    name = Column(String, unique=True, index=True, nullable=False)
    projectversions = relationship("ProjectVersion", back_populates="project")
    description = Column(String)
