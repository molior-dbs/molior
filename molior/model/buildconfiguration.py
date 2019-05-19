"""
This module provides the molior BuildConfiguration
database model.
"""

from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

import molior.model.projectversion  # noqa: F401, pylint: disable=unused-import
from .database import Base
from .buildvariant import BuildVariant
from .sourepprover import SouRepProVer


class BuildConfiguration(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a BuildConfiguration.
    """

    __tablename__ = "buildconfiguration"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    sourcerepositoryprojectversion_id = Column(  # pylint: disable=invalid-name
        ForeignKey("sourcerepositoryprojectversion.id")
    )
    sourcerepositories = relationship("SourceRepository", secondary=SouRepProVer)
    projectversions = relationship("ProjectVersion", secondary=SouRepProVer)
    buildvariant_id = Column(ForeignKey("buildvariant.id"))
    buildvariant = relationship(BuildVariant)
    UniqueConstraint(
        "sourcerepositoryprojectversion_id",
        "buildvariant_id",
        name="unique_buildconfiguration",
    )
