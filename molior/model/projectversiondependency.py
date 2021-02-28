from sqlalchemy import Column, Integer, Boolean, ForeignKey, UniqueConstraint

from .database import Base


class ProjectVersionDependency(Base):
    __tablename__ = "projectversiondependency"
    __table_args__ = (UniqueConstraint("projectversion_id", "dependency_id", name="unique_projectversiondepedency"),
                      {'extend_existing': True})

    id = Column(Integer, primary_key=True)
    projectversion_id = Column(Integer, ForeignKey("projectversion.id"))
    dependency_id = Column(Integer, ForeignKey("projectversion.id"))
    use_cibuilds = Column(Boolean)
    # __mapper_args__ = {"primary_key": [projectversion_id, dependency_id]}
