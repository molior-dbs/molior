from sqlalchemy import Column, String, Integer

from .database import Base


class Debianpackage(Base):
    __tablename__ = "debianpackage"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    suffix = Column(String)
