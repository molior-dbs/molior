"""
This module provides the molior BuildVariant
database model.
"""
from sqlalchemy import Column, ForeignKey, Integer, func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from .database import Base
from .architecture import Architecture
from .proverbuivar import ProVerBuiVar
from .project import Project


class BuildVariant(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a BuildVariant.
    """

    __tablename__ = "buildvariant"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    architecture_id = Column(ForeignKey("architecture.id"))
    architecture = relationship(Architecture)
    base_mirror_id = Column(ForeignKey("projectversion.id"))
    base_mirror = relationship("ProjectVersion")
    projectversions = relationship("ProjectVersion", secondary=ProVerBuiVar)

    @hybrid_property
    def name(self):
        """
        Returns the name of the buildvariant,
        combined by base mirror and architecture
        """
        return "{base_mirror}-{basemirror_version}/{architecture}".format(
            base_mirror=self.base_mirror.project.name,
            basemirror_version=self.base_mirror.name,
            architecture=self.architecture.name,
        )

    @name.expression
    def name(cls):  # pylint: disable=no-self-argument
        """
        Returns the name of the buildvariant,
        combined by base mirror and architecture
        """
        # FIXME: ProjectVersion circular import
        from .projectversion import ProjectVersion

        return func.concat(
            Project.name, "-", ProjectVersion.name, "/", Architecture.name
        )
