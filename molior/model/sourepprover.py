from sqlalchemy import Column, Integer, String, ForeignKey, Boolean

from .database import Base


class SouRepProVer(Base):
    __tablename__ = "sourcerepositoryprojectversion"

    id = Column(Integer, primary_key=True)
    sourcerepository_id = Column(ForeignKey("sourcerepository.id"))
    projectversion_id = Column(ForeignKey("projectversion.id"))
    architectures = Column(String)
    run_lintian = Column(Boolean, default=False)
