"""
Shared helpers for v2 routers.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from ....model.project import Project
from ....model.projectversion import ProjectVersion
from ....tools import parse_int


def resolve_projectversion(
    project_id: str,
    projectversion_id: str,
    db: Session,
    is_mirror: bool = False,
):
    """
    Resolve a ProjectVersion from path parameters.

    Accepts either name/name or id/id combinations, matching the behaviour of
    the original get_projectversion() helper in model/projectversion.py.
    """
    pv = db.query(ProjectVersion).join(Project).filter(
        func.lower(Project.name) == project_id.lower(),
        func.lower(ProjectVersion.name) == projectversion_id.lower(),
        Project.is_mirror.is_(is_mirror),
    ).first()
    if pv:
        return pv

    # Fall back to integer IDs
    pid = parse_int(project_id)
    pvid = parse_int(projectversion_id)
    if pid and pvid:
        pv = db.query(ProjectVersion).join(Project).filter(
            Project.id == pid,
            ProjectVersion.id == pvid,
            Project.is_mirror.is_(is_mirror),
        ).first()
    return pv
