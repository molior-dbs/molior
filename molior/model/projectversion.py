from sqlalchemy import Column, ForeignKey, Integer, String, Enum, Boolean, func, select
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from ..app import logger
from ..molior.configuration import Configuration
from ..tools import db2array

from .database import Base
from .project import Project
from .projectversiondependency import ProjectVersionDependency
# reeded for relations:
from . import sourcerepository    # noqa: F401
from . import mirrorkey    # noqa: F401

MIRROR_STATES = ["undefined", "new", "created", "updating", "publishing", "init_error", "error", "ready"]
DEPENDENCY_POLICIES = ["strict", "distribution", "any"]


class ProjectVersion(Base):
    __tablename__ = "projectversion"

    id = Column(Integer, primary_key=True)
    project_id = Column(ForeignKey("project.id"))
    project = relationship(Project, back_populates="projectversions")
    name = Column(String, index=True, nullable=False)
    description = Column(String)
    sourcerepositories = relationship("SourceRepository", secondary="sourcerepositoryprojectversion")
    basemirror_id = Column(ForeignKey("projectversion.id"))
    basemirror = relationship("ProjectVersion", uselist=False,
                              remote_side=[id],
                              foreign_keys=basemirror_id)
    external_repo = Column(Boolean, default=False)
    dependencies = relationship("ProjectVersion",
                                secondary=ProjectVersionDependency.__table__,
                                primaryjoin=id == ProjectVersionDependency.projectversion_id,
                                secondaryjoin=id == ProjectVersionDependency.dependency_id,
                                )
    dependents = relationship("ProjectVersion",
                              secondary=ProjectVersionDependency.__table__,
                              primaryjoin=id == ProjectVersionDependency.dependency_id,
                              secondaryjoin=id == ProjectVersionDependency.projectversion_id,
                              )
    mirror_url = Column(String)
    mirror_distribution = Column(String)
    mirror_components = Column(String)
    mirror_architectures = Column(String)
    mirror_state = Column(Enum(*MIRROR_STATES, name="mirror_stateenum"), default=None)
    mirror_with_sources = Column(Boolean, default=False)
    mirror_with_installer = Column(Boolean, default=False)
    mirror_keys = relationship("MirrorKey", back_populates="mirrors")
    is_locked = Column(Boolean, default=False)
    ci_builds_enabled = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    dependency_policy = Column(Enum(*DEPENDENCY_POLICIES, name="dependencypolicy_enum"), default="strict")

    @hybrid_property
    def fullname(self):
        """
        Returns the project name and the version name
        """
        return "{project}/{version}".format(
            project=self.project.name, version=self.name
        )

    @fullname.expression
    def fullname(cls):
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
        if self.project.is_mirror and self.external_repo:
            url = self.mirror_url
            full = "deb {0} {1} {2}".format(url, self.mirror_distribution,
                                            self.mirror_components.replace(",", " "))
            return url if url_only else full

        cfg = Configuration()
        base_url = cfg.aptly.get("apt_url")

        if self.project.is_basemirror:
            url = "{0}/{1}/{2}".format(base_url, self.project.name, self.name)
            # Workaround for aptly ('/' not supported as mirror dist)
            full = "deb {0} {1} {2}".format(url, self.mirror_distribution.replace("/", "_-"),
                                            self.mirror_components.replace(",", " "))
            return url if url_only else full

        if not self.basemirror:
            logger.error("projectversion without basemirror: {}".format(self.id))
            return ""

        base_mirror = "{}/{}".format(self.basemirror.project.name, self.basemirror.name)

        if self.project.is_mirror:
            url = "{0}/{1}/mirrors/{2}/{3}".format(base_url, base_mirror, self.project.name, self.name)
            # Workaround for aptly ('/' not supported as mirror dist)
            full = "deb {0} {1} {2}".format(url, self.mirror_distribution.replace("/", "_-"),
                                            self.mirror_components.replace(",", " "))
            return url if url_only else full

        url = "{0}/{1}/repos/{2}/{3}".format(base_url, base_mirror, self.project.name, self.name)
        full = "deb {0} {1} {2}".format(url, dist, "main")
        return url if url_only else full

    def mirror_changed(self):
        pass
        # await app.websocket_broadcast(
        #    {
        #        "event": Event.changed.value,
        #        "subject": Subject.mirror.value,
        #        "data": {},
        #    }
        # )

    def data(self):
        """
        Returns the given projectversion object
        as dist, which can be processed by
        json_response
        ---
        Args:
            projectversion (object): The projectversion from the database
                provided by SQLAlchemy.
        Returns:
            dict: The dict which can be processed by json_response

        """
        dependency_ids = []
        for d in self.dependencies:
            dependency_ids.append(d.id)
        dependent_ids = []
        for d in self.dependents:
            dependent_ids.append(d.id)
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "project_name": self.project.name,
            "apt_url": self.get_apt_repo(url_only=True),
            "is_mirror": self.project.is_mirror,
            "architectures": db2array(self.mirror_architectures),
            "is_locked": self.is_locked,
            "ci_builds_enabled": self.ci_builds_enabled,
            "dependency_policy": self.dependency_policy,
            "dependency_ids": dependency_ids,
            "dependent_ids": dependent_ids
        }
        if self.basemirror:
            data.update({"basemirror": self.basemirror.fullname})

        return data


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
        SELECT projectversion_id, dependency_id, use_cibuilds
        FROM projectversiondependency
        WHERE projectversion_id = :projectversion_id

        UNION ALL

        SELECT s2.projectversion_id, s2.dependency_id, s2.use_cibuilds
        FROM projectversiondependency s2, getparents s1
        WHERE s2.projectversion_id = s1.dependency_id
    )
    SELECT projectversion_id, dependency_id, use_cibuilds FROM getparents;
    """
    result = session.execute(query, {"projectversion_id": projectversion_id})

    projectversion_ids = []
    for row in result:
        projectversion_ids.append((row[1], row[2]))
    return projectversion_ids


def get_projectversion(request):
    if "project_name" in request.match_info:
        project_name = request.match_info["project_name"]
    elif "project_id" in request.match_info:
        project_name = request.match_info["project_id"]
    if "project_version" in request.match_info:
        project_version = request.match_info["project_version"]
    elif "projectversion_id" in request.match_info:
        project_version = request.match_info["projectversion_id"]
    projectversion = request.cirrina.db_session.query(ProjectVersion).join(Project).filter(
            ProjectVersion.name == project_version,
            Project.name == project_name,
        ).first()
    if not projectversion:
        logger.warning("projectversion not found: %s/%s" % (project_name, project_version))
    return projectversion


def get_projectversion_byname(fullname, session):
    parts = fullname.split('/')
    if len(parts) != 2:
        return None
    name, version = parts
    return session.query(ProjectVersion).join(Project).filter(
            Project.name == name,
            ProjectVersion.name == version,
        ).first()


def get_mirror(request):
    if "mirror_name" not in request.match_info:
        return None
    if "mirror_version" not in request.match_info:
        return None
    mirror_name = request.match_info["mirror_name"]
    mirror_version = request.match_info["mirror_version"]

    return request.cirrina.db_session.query(ProjectVersion).join(Project).filter(
            ProjectVersion.name == mirror_version,
            Project.name == mirror_name,
            Project.is_mirror.is_(True),
            ProjectVersion.is_deleted.is_(False)
        ).first()
