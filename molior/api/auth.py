from aiohttp import web

from molior.app import app, logger
from molior.molior.configuration import Configuration
from molior.model.user import User
from molior.auth import Auth


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
    Authenticates a user using locuples.

    Args:
        user (str): The user's name.
        passwd (str): The user's password.

    Returns:
        bool: True if successfully authenticated, otherwise False.
    """
    if not user:
        return False
    user = user.lower()  # FIXME: move to cirrina
    if user == "admin":
        logger.error("admin account not allowed via auth plugin")
        return False

    return Auth().login(user, passwd)


def load_user(user, db_session):
    """
    Load user from the database
    """
    res = (
        db_session.query(User)
        .filter_by(username=user)  # pylint: disable=no-member
        .first()
    )
    if not res:  # add user to DB
        db_user = User(username=user)

        # make first user admin
        if db_session.query(User).count() < 2:  # pylint: disable=no-member
            db_user.is_admin = True

        db_session.add(db_user)  # pylint: disable=no-member
        db_session.commit()  # pylint: disable=no-member


@app.http_get("/api/userinfo")
@app.authenticated
async def get_userinfo(request):
    """
    Return a dict with session informations

    {
        "username" <Std>
        "user_id" <Int>
        "is_admin" <Bool>
    }

    """
    username = request.cirrina.web_session.get("username")
    if username:
        user = (
            request.cirrina.db_session.query(User)
            .filter_by(username=username.lower())  # pylint: disable=no-member
            .first()
        )

        if user:
            return web.json_response(
                {"username": username, "user_id": user.id, "is_admin": user.is_admin}
            )

    return web.json_response({"username": username, "user_id": -1, "is_admin": False})
