from sqlalchemy import Column, Integer, ForeignKey, Boolean, String
from sqlalchemy.orm import relationship

from .database import Base


class Chroot(Base):
    __tablename__ = "chroot"

    id = Column(Integer, primary_key=True)
    build_id = Column(ForeignKey("build.id"))
    basemirror_id = Column(ForeignKey("projectversion.id"))
    basemirror = relationship("ProjectVersion")
    architecture = Column(String)
    ready = Column(Boolean)
