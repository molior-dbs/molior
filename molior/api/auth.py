from aiohttp import web
from sqlalchemy.sql import func

from ..app import app
from ..molior.configuration import Configuration
from ..logger import logger
from ..auth.auth import Auth, load_user, setup_token

from ..model.user import User
from ..model.project import Project
from ..model.authtoken import Authtoken
from ..model.authtoken_project import Authtoken_Project


@app.auth_handler
async def auth_admin(request, user, passwd):
    """
    Authenticates admin user

    Args:
        user (str): The user's name.
        passwd (str): The user's password.

    Returns:
        bool: True if successfully authenticated, otherwise False.
    """
    if not user:
        return False
    user = user.lower()
    if user == "admin":
        config = Configuration()
        admin_pass = config.admin.get("pass")
        if not admin_pass:
            logger.info("admin password is not set in configuration")
            return False
        if passwd == admin_pass:
            load_user("admin", request.cirrina.db_session)
            return True
    return False


@app.auth_handler
async def authenticate(request, user, passwd):
    """
    Authenticates a user.

    Args:
        user (str): The user's name.
        passwd (str): The user's password.

    Returns:
        bool: True if successfully authenticated, otherwise False.
    """
    if not user:
        return False
    user = user.lower().strip()  # FIXME: move to cirrina
    if user == "admin":
        logger.error("admin account not allowed via auth plugin")
        return False

    return Auth().login(user, passwd)


@app.http_get("/api/userinfo")
@app.authenticated
async def get_userinfo(request):
    username = request.cirrina.web_session.get("username")
    if username:
        user = request.cirrina.db_session.query(User).filter_by(username=username.lower()).first()
        if user:
            return web.json_response({"username": username, "user_id": user.id, "is_admin": user.is_admin})
    return web.json_response({"username": username, "user_id": -1, "is_admin": False})


@app.auth_handler
async def authenticate_token(request, *kw):
    setup_token(request)
    auth_token = None
    if hasattr(request.cirrina.web_session, "auth_token"):
        auth_token = request.cirrina.web_session.auth_token
    if not auth_token:
        return False
    token = None
    project_name = request.match_info.get("project_name")
    if project_name:
        p = request.cirrina.db_session.query(Project).filter(func.lower(Project.name) == project_name.lower()).first()
        if p:
            project_id = p.id
        query = request.cirrina.db_session.query(Authtoken).join(Authtoken_Project)
        query = query.filter(Authtoken_Project.project_id == project_id, Authtoken.token == auth_token)
        token = query.first()
    else:
        query = request.cirrina.db_session.query(Authtoken)
        query = query.filter(Authtoken.token == auth_token)
        token = query.first()

    return token is not None
