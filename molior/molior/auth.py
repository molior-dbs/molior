import importlib

from .logger import get_logger
from .configuration import Configuration

logger = get_logger()
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
