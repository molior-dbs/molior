import importlib

from functools import wraps
from aiohttp import web

from molior.app import logger
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion
from molior.tools import check_admin, check_user_role, parse_int

from molior.molior.configuration import Configuration

auth_backend = None


class Auth:

    def init(self):
        global auth_backend
        if auth_backend:
            return True
        cfg = Configuration()
        try:
            plugin = cfg.auth_backend
        except Exception as exc:
            logger.error("please define 'auth_backend' in config")
            logger.exception(exc)
            return False

        logger.info("loading auth_backend: %s", plugin)
        try:
            module = importlib.import_module(".auth.%s" % plugin, package="molior")
            auth_backend = module.AuthBackend()
        except Exception as exc:
            logger.error("error loading auth_backend plugin '%s'", plugin)
            logger.exception(exc)
            return False
        return True

    def login(self, user, password):
        global auth_backend
        if not auth_backend:
            return False
        return auth_backend.login(user, password)

    def add_user(self, user, password):
        global auth_backend
        if not auth_backend:
            return False
        if not hasattr(auth_backend, "add_user"):
            return False
        return auth_backend.add_user(user, password)


def req_admin(func):
    """
    Decorator to enforce admin privilege for a function

    Example :

        @app.http_get("/some/path")
        @app.req_admin
        def function(request):
            pass
    """

    @wraps(func)
    async def _wrapper(request):
        """Wrapper func for req_admin decorator."""
        if check_admin(request.cirrina.web_session, request.cirrina.db_session):
            return await func(request)

        return web.Response(status=403)

    return _wrapper


class req_role(object):
    """
    Decorator to enforce a role for a function concerning project.

    The url must contain {project_id} or {projectversion_id}.

    Example :

        @app.http_get("/projects/{project_id}/")
        @app.req_role("owner")
        def function(request):
            pass

    Another example where admin is admitted:

        @app.http_get("/projects/{project_id}/")
        @app.req_role("owner", False)
        def function(request):
            pass
    """

    def __init__(self, role, allow_admin=True):
        self.role = role
        self.allow_admin = allow_admin

    def __call__(self, func):
        """Wrapper func for req_admin decorator."""

        @wraps(func)
        async def _wrapper(request):
            maintenance_mode = False
            query = "SELECT value from metadata where name = :key"
            result = request.cirrina.db_session.execute(
                query, {"key": "maintenance_mode"}
            )
            for value in result:
                if value[0] == "true":
                    maintenance_mode = True
                break

            if maintenance_mode:
                return web.Response(status=503, text="Maintenance Mode")

            project_id = request.match_info.get("project_id")
            projectversion_id = request.match_info.get("projectversion_id")

            if not project_id and not projectversion_id:
                return web.Response(status=403)

            if not project_id and projectversion_id:
                pv = request.cirrina.db_session.query(ProjectVersion).filter(
                                    ProjectVersion.id == parse_int(projectversion_id)).first()
                if pv:
                    project_id = pv.project.id
            else:
                # try finting project by name
                p = request.cirrina.db_session.query(Project).filter(
                                    Project.name == project_id).first()
                if p:
                    project_id = p.id
                else:
                    # try finting project by id
                    p = request.cirrina.db_session.query(Project).filter(
                                        Project.id == parse_int(project_id)).first()
                    if p:
                        project_id = p.id
                    else:
                        return web.Response(status=403)

            if check_user_role(request.cirrina.web_session,
                               request.cirrina.db_session,
                               project_id,
                               self.role,
                               self.allow_admin):
                return await func(request)

            return web.Response(status=403)

        return _wrapper
