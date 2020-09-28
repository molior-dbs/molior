from sqlalchemy import Column, ForeignKey, Integer, String, Enum, Boolean, func, select
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from ..app import logger
from ..molior.configuration import Configuration

from .database import Base
from .project import Project
from .projectversiondependency import ProjectVersionDependency
# reeded for relations:
from . import sourcerepository    # noqa: F401

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
    # buildvariants = relationship("BuildVariant", secondary=ProVerBuiVar)
    mirror_url = Column(String)
    mirror_distribution = Column(String)
    mirror_components = Column(String)
    mirror_architectures = Column(String)
    mirror_state = Column(Enum(*MIRROR_STATES, name="mirror_stateenum"), default=None)
    mirror_with_sources = Column(Boolean, default=False)
    mirror_with_installer = Column(Boolean, default=False)
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


def get_projectversion(request):
    if "project_name" in request.match_info:
        project_name = request.match_info["project_name"]
    elif "project_id" in request.match_info:
        project_name = request.match_info["project_id"]
    if "project_version" in request.match_info:
        project_version = request.match_info["project_version"]
    elif "projectversion_id" in request.match_info:
        project_version = request.match_info["projectversion_id"]
    return request.cirrina.db_session.query(ProjectVersion).join(Project).filter(
            ProjectVersion.name == project_version,
            Project.name == project_name,
        ).first()


def get_projectversion_byname(fullname, session):
    parts = fullname.split('/')
    if len(parts) != 2:
        return None
    name, version = parts
    return session.query(ProjectVersion).join(Project).filter(
            Project.name == name,
            ProjectVersion.name == version,
        ).first()
