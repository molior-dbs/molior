"""
This module provides the molior ProjectVersion
database model.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Enum, Boolean, func, select
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

import molior.model.buildconfiguration  # pylint: disable=unused-import
import molior.model.sourcerepository  # noqa: F401 pylint: disable=unused-import
from molior.molior.configuration import Configuration
from molior.molior.logger import get_logger

from .project import Project
from .sourepprover import SouRepProVer
from .projectversiondependency import ProjectVersionDependency
from .proverbuivar import ProVerBuiVar
from .database import Base

MIRROR_STATES = ["undefined", "created", "updating", "publishing", "error", "ready"]

logger = get_logger()


class ProjectVersion(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a ProjectVersion.
    """

    __tablename__ = "projectversion"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    project_id = Column(ForeignKey("project.id"))
    project = relationship(Project, back_populates="projectversions")
    name = Column(String, index=True, nullable=False)
    sourcerepositories = relationship("SourceRepository", secondary=SouRepProVer)
    buildconfiguration = relationship("BuildConfiguration", secondary=SouRepProVer)
    dependencies = relationship("ProjectVersion",
                                secondary=ProjectVersionDependency,
                                primaryjoin=id == ProjectVersionDependency.c.projectversion_id,
                                secondaryjoin=id == ProjectVersionDependency.c.dependency_id,
                                )
    dependents = relationship("ProjectVersion",
                              secondary=ProjectVersionDependency,
                              primaryjoin=id == ProjectVersionDependency.c.dependency_id,
                              secondaryjoin=id == ProjectVersionDependency.c.projectversion_id,
                              )
    buildvariants = relationship("BuildVariant", secondary=ProVerBuiVar)
    mirror_url = Column(String)
    mirror_distribution = Column(String)
    mirror_components = Column(String)
    mirror_architectures = Column(String)
    mirror_state = Column(Enum(*MIRROR_STATES, name="mirror_stateenum"), default="undefined")
    mirror_with_sources = Column(Boolean, default=False)
    mirror_with_installer = Column(Boolean, default=False)
    is_locked = Column(Boolean, default=False)
    ci_builds_enabled = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)

    @hybrid_property
    def fullname(self):
        """
        Returns the project name and the version name
        """
        return "{project}/{version}".format(
            project=self.project.name, version=self.name
        )

    @fullname.expression
    def fullname(cls):  # pylint: disable=no-self-argument
        """
        Returns the project name and the version name
        """
        return func.concat(
            (select([Project.name]).where(Project.id == cls.project_id).as_scalar()),
            " ",
            cls.name,
        )

    def get_apt_repo(self, url_only=False, dist="stable"):
        """
        Returns the apt sources url string of the projectversion.
        """
        cfg = Configuration()
        base_url = cfg.aptly.get("apt_url")

        if self.project.is_basemirror:
            url = "{0}/{1}/{2}".format(base_url, self.project.name, self.name)
            full = "deb {0} {1} {2}".format(url, self.mirror_distribution, self.mirror_components.replace(",", " "))
            return url if url_only else full

        if not self.buildvariants:
            logger.error("project version '%s' has no basemirror", self.fullname)
            return str()

        b_mirror = self.buildvariants[0].base_mirror
        base_mirror = "{}/{}".format(b_mirror.project.name, b_mirror.name)

        if self.project.is_mirror:
            url = "{0}/{1}/mirrors/{2}/{3}".format(base_url, base_mirror, self.project.name, self.name)
            full = "deb {0} {1} {2}".format(url, self.mirror_distribution, self.mirror_components.replace(",", " "))
            return url if url_only else full

        url = "{0}/{1}/repos/{2}/{3}".format(base_url, base_mirror, self.project.name, self.name)
        full = "deb {0} {1} {2}".format(url, dist, "main")
        return url if url_only else full


def get_projectversion_deps(projectversion_id, session):
    """
    Gets a list of projectversions which are recursive
    dependencies of the given projectversion.

    Note:
        Plain sql is used because of performance reasons and
        complexity of the statements.
        The given projectversion will be included in the result.

    Args:
        projectversion (ProjectVersion): The projectversion to get the
            dependencies for.

    Returns:
        list: A list of ProjectVersions.
    """
    query = """
    WITH RECURSIVE getparents(projectversion_id, dependency_id) AS (
        SELECT projectversion_id, dependency_id
        FROM projectversiondependency
        WHERE projectversion_id = :projectversion_id

        UNION ALL

        SELECT s2.projectversion_id, s2.dependency_id
        FROM projectversiondependency s2, getparents s1
        WHERE s2.projectversion_id = s1.dependency_id
    )
    SELECT projectversion_id, dependency_id FROM getparents;
    """
    result = session.execute(query, {"projectversion_id": projectversion_id})

    projectversion_ids = []

    for row in result:
        projectversion_ids.append(row[1])

    return projectversion_ids
