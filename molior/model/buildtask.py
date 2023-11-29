from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class BuildTask(Base):
    __tablename__ = "buildtask"

    id = Column(Integer, primary_key=True)
    build_id = Column(ForeignKey("build.id"), index=True)
    build = relationship("Build", back_populates="buildtask")
    task_id = Column(String)
