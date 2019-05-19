"""
Provides the molior web app.
"""
from functools import wraps

import cirrina
from aiohttp import web

from molior.model.projectversion import ProjectVersion

from .userrolehelper import check_admin, check_user_role
from .inputparser import parse_int

__title__ = "Molior REST API Documentation"
__description__ = "Documentation of the molior REST API."
__api_version__ = 1
__contact__ = ""


class MoliorApp(cirrina.Server):  # pylint: disable=too-few-public-methods
    """
    Molior web/REST application
    """

    @staticmethod
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

                project_id = parse_int(project_id)
                projectversion_id = parse_int(projectversion_id)

                if not project_id and not projectversion_id:
                    return web.Response(status=403)

                if not project_id and projectversion_id:
                    pversion = (
                        request.cirrina.db_session.query(ProjectVersion)
                        .filter(  # pylint: disable=no-member
                            ProjectVersion.id == projectversion_id
                        )
                        .first()
                    )
                    project_id = pversion.project.id

                if check_user_role(
                    request.cirrina.web_session,
                    request.cirrina.db_session,
                    project_id,
                    self.role,
                    self.allow_admin,
                ):
                    return await func(request)

                return web.Response(status=403)

            return _wrapper


app = MoliorApp()  # pylint: disable=invalid-name
app.title = __title__
app.description = __description__
app.api_version = __api_version__
app.contact = __contact__
