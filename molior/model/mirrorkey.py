from sqlalchemy import Column, ForeignKey, String, PrimaryKeyConstraint
from sqlalchemy.orm import relationship

from .database import Base


class MirrorKey(Base):
    __tablename__ = "mirrorkey"
    __table_args__ = (PrimaryKeyConstraint('projectversion_id'), )

    projectversion_id = Column(ForeignKey("projectversion.id"))
    mirrors = relationship("ProjectVersion", back_populates="mirror_keys")
    keyurl = Column(String)
    keyids = Column(String)
    keyserver = Column(String)
