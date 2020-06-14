from sqlalchemy import Column, ForeignKey, String, PrimaryKeyConstraint

from .database import Base


class MirrorKey(Base):
    __tablename__ = "mirrorkey"
    __table_args__ = (PrimaryKeyConstraint('projectversion_id'), )

    projectversion_id = Column(ForeignKey("projectversion.id"))
    keyurl = Column(String)
    keyids = Column(String)
    keyserver = Column(String)
