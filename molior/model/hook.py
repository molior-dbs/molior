from sqlalchemy import Column, String, Integer, Enum, Boolean
from sqlalchemy.orm import relationship

from .database import Base
from .sourcerepositoryhook import SourceRepositoryHook

HTTP_METHODS = ["post", "put", "get"]


class Hook(Base):
    __tablename__ = "hook"

    id = Column(Integer, primary_key=True)
    method = Column("method", Enum(*HTTP_METHODS, name="http_method_enum"), default="undefined")
    body = Column(String)
    url = Column(String)
    skip_ssl = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    sourcerepositories = relationship("SourceRepository", secondary=SourceRepositoryHook)
    notify_src = Column(Boolean, default=True)
    notify_deb = Column(Boolean, default=True)
    notify_overall = Column(Boolean, default=True)
