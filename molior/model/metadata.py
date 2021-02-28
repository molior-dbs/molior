from sqlalchemy import Column, String, Integer
from .database import Base


class MetaData(Base):
    __tablename__ = "metadata"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    value = Column(String)
