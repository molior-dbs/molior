from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base


class PostBuildHook(Base):
    __tablename__ = "postbuildhook"

    id = Column(Integer, primary_key=True)
    sourcerepositoryprojectversion_id = Column(ForeignKey("sourcerepositoryprojectversion.id"))
    hook_id = Column(ForeignKey("hook.id"))
    hook = relationship("Hook")
    UniqueConstraint("sourcerepositoryprojectversion_id", "hook_id", name="unique_sourcerepositoryhook")
