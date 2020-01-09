"""
Various helper to manager and check user roles
"""
import logging

from molior.model.project import Project

from molior.model.user import User
from molior.model.userrole import UserRole

from .inputparser import parse_int

logger = logging.getLogger("molior")  # pylint: disable=invalid-name


def check_admin(web_session, db_session):
    """
    Helper to check current user is admin
    """
    if "username" in web_session:
        res = (
            db_session.query(User)  # pylint: disable=no-member
            .filter_by(username=web_session["username"])
            .first()
        )
        if not res:
            return False
        return res.is_admin


def check_user_role(web_session, db_session, project_id, role, allow_admin=True):
    """
    Helper to enforce the current user as a certain role for a given project

    Input :
        * session <multiDict>
        * project_id <int>
        * role <str> or [<str>,<str>,...] : one or multiple role or "any"
        * allow_admin <bool> : allow admin to bypass

    Output : return a boolean
        * True : the use

    Examples :

        if( not check_user_role( ThisProject, ThisRole)):
            return web.Response(status=401, text="permission denied")

        if( not check_user_role( ThisProject, "any")):
            return web.Response(status=401,
                                text="You need a role on the project")

        if( not check_user_role( ThisProject, "owner")):
            return web.Response(status=401,
                                text="Only project owner can do this")

    """
    project_id = parse_int(project_id)
    if not project_id:
        return False

    if "username" not in web_session:
        return False  # no session

    user = (
        db_session.query(User)
        .filter_by(username=web_session["username"])  # pylint: disable=no-member
        .first()
    )
    if not user:
        return False  # no user in database

    if allow_admin and user.is_admin:
        return True

    project = (
        db_session.query(Project)
        .filter_by(id=project_id)  # pylint: disable=no-member
        .first()
    )
    if not project:
        return False  # no project in database

    logger.debug("searching role for user %d and project %d", user.id, project.id)
    role_rec = (
        db_session.query(UserRole)
        .filter_by(user=user, project=project)  # pylint: disable=no-member
        .first()
    )
    if not role_rec:
        return False  # no role in database

    roles = [role] if isinstance(role, str) else role

    if "any" in roles or role_rec.role in roles:
        return True

    return False
