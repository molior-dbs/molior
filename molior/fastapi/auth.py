"""
Authentication and authorisation dependencies for FastAPI.

Replaces:
  - @app.authenticated      ->  Depends(authenticated)
  - @req_admin              ->  Depends(require_admin)
  - @req_role("owner")      ->  Depends(require_role("owner"))
  - @req_role(["m","o"])    ->  Depends(require_role(["member", "owner"]))

Session is carried in a signed cookie (itsdangerous) under the key
MOLIOR_SESSION.  The cookie is set on login and cleared on logout.
Token auth via the X-MoliorToken header is also supported, matching the
existing authenticate_token behaviour.

Current user is exposed as a CurrentUser dataclass injected via Depends.
"""

import hashlib
from dataclasses import dataclass
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from .db import get_db
from ..molior.configuration import Configuration
from ..model.user import User
from ..model.project import Project
from ..model.projectversion import ProjectVersion
from ..model.authtoken import Authtoken
from ..model.authtoken_project import Authtoken_Project
from ..model.userrole import UserRole
from ..tools import parse_int, db2array


# ---------------------------------------------------------------------------
# Session serialiser — secret comes from molior.yml
# ---------------------------------------------------------------------------

def _get_serializer() -> URLSafeTimedSerializer:
    secret = Configuration().admin.get("admin_password")
    if not secret:
        raise RuntimeError("admin_password is not set in molior.yml")
    return URLSafeTimedSerializer(secret)


def assert_secret_configured() -> None:
    """
    Call once at startup. Raises RuntimeError if admin_password is missing
    from molior.yml so the server refuses to start with no signing secret.
    """
    from ..logger import logger
    secret = Configuration().admin.get("admin_password")
    if not secret:
        raise RuntimeError(
            "admin_password is not set in molior.yml — "
            "cannot sign session cookies. Server will not start."
        )
    logger.debug("auth: session secret loaded from admin_password")


def create_session_cookie(username: str) -> str:
    """Sign and return a session cookie value for the given username."""
    return _get_serializer().dumps({"username": username})


def decode_session_cookie(cookie: str) -> Optional[dict]:
    """Decode and verify the session cookie. Returns None if invalid/expired."""
    try:
        # max_age: 302400 seconds = 1 week (matching existing behaviour)
        return _get_serializer().loads(cookie, max_age=302400)
    except BadSignature:
        return None


# ---------------------------------------------------------------------------
# CurrentUser — injected into every authenticated handler
# ---------------------------------------------------------------------------

@dataclass
class CurrentUser:
    username: str
    user_id: int
    is_admin: bool
    auth_token: Optional[str] = None   # hashed token, if token-authenticated


# ---------------------------------------------------------------------------
# Core dependency: resolve caller identity from cookie or token header
# ---------------------------------------------------------------------------

def get_current_user(
    molior_session: Optional[str] = Cookie(default=None),
    x_molior_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[CurrentUser]:
    """
    Resolves the current caller.  Returns None when unauthenticated.
    Handlers that require auth use authenticated() / require_admin() /
    require_role() which raise 401/403 as appropriate.
    """
    # --- Token auth (X-MoliorToken header) ---
    if x_molior_token:
        hashed = hashlib.sha256(x_molior_token.encode()).hexdigest()
        token = db.query(Authtoken).filter(Authtoken.token == hashed).first()
        if token:
            # Tokens are not tied to a specific user; represent as a pseudo-admin
            # with the roles embedded in the token record.
            is_admin = "project_create" in db2array(token.roles)
            return CurrentUser(
                username="__token__",
                user_id=0,
                is_admin=is_admin,
                auth_token=hashed,
            )

    # --- Cookie / session auth ---
    if molior_session:
        data = decode_session_cookie(molior_session)
        if data and "username" in data:
            username = data["username"]

            # Admin user is authenticated against config, not DB
            if username == "admin":
                return CurrentUser(username="admin", user_id=0, is_admin=True)

            user = db.query(User).filter_by(username=username).first()
            if user:
                return CurrentUser(
                    username=user.username,
                    user_id=user.id,
                    is_admin=bool(user.is_admin),
                )

    return None


# ---------------------------------------------------------------------------
# Public authenticated() dependency — raises 401 if not logged in
# ---------------------------------------------------------------------------

def authenticated(
    current_user: Optional[CurrentUser] = Depends(get_current_user),
) -> CurrentUser:
    """Require any authenticated caller. Replaces @app.authenticated."""
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return current_user


# ---------------------------------------------------------------------------
# require_admin() dependency — raises 403 if not admin
# ---------------------------------------------------------------------------

def require_admin(
    current_user: CurrentUser = Depends(authenticated),
) -> CurrentUser:
    """Require admin privilege. Replaces @req_admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


# ---------------------------------------------------------------------------
# require_role() — returns a dependency factory for project-scoped roles
# ---------------------------------------------------------------------------

def _check_token_project(db: Session, auth_token: str, project_id: int) -> bool:
    """Check whether a token is associated with the given project."""
    return db.query(Authtoken).join(Authtoken_Project).filter(
        Authtoken_Project.project_id == project_id,
        Authtoken.token == auth_token,
    ).first() is not None


def _check_user_role(db: Session, user_id: int, project_id: int, roles: list[str]) -> bool:
    """Check whether the user holds one of the given roles on the project."""
    role_rec = db.query(UserRole).filter_by(user_id=user_id, project_id=project_id).first()
    if not role_rec:
        return False
    return "any" in roles or role_rec.role in roles


def _resolve_project_id(
    db: Session,
    project_id_param: Optional[str],
    project_name_param: Optional[str],
    projectversion_id_param: Optional[str],
) -> Optional[int]:
    """Resolve a project id from whichever path param is available."""
    # Try projectversion_id first
    if not project_id_param and not project_name_param and projectversion_id_param:
        pv_id = parse_int(projectversion_id_param)
        if pv_id:
            pv = db.query(ProjectVersion).filter(ProjectVersion.id == pv_id).first()
            if pv:
                return pv.project_id
        return None

    raw = project_id_param or project_name_param
    if not raw:
        return None

    # Try by name first
    project = db.query(Project).filter(func.lower(Project.name) == raw.lower()).first()
    if project:
        return project.id

    # Fall back to integer id
    pid = parse_int(raw)
    if pid:
        project = db.query(Project).filter(Project.id == pid).first()
        if project:
            return project.id

    return None


def require_role(role):
    """
    Dependency factory for project-scoped role checks.

    Replaces @req_role("owner") / @req_role(["member", "owner"]).

    Usage:

        @router.post("/api2/project/{project_id}/{projectversion_id}/copy")
        def copy(
            project_id: str,
            projectversion_id: str,
            _: CurrentUser = Depends(require_role("owner")),
            db: Session = Depends(get_db),
        ):
            ...
    """
    roles = [role] if isinstance(role, str) else list(role)

    def _dependency(
        # Path params — all optional so the same factory works across routes
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        projectversion_id: Optional[str] = None,
        current_user: Optional[CurrentUser] = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        if not current_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

        # Admins bypass role checks
        if current_user.is_admin:
            return current_user

        pid = _resolve_project_id(db, project_id, project_name, projectversion_id)
        if pid is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project privileges required")

        # Token with project association
        if current_user.auth_token and _check_token_project(db, current_user.auth_token, pid):
            return current_user

        # User role check
        if _check_user_role(db, current_user.user_id, pid, roles):
            return current_user

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project privileges required")

    return _dependency


# ---------------------------------------------------------------------------
# Maintenance mode guard — used by write endpoints
# ---------------------------------------------------------------------------

def check_maintenance(db: Session = Depends(get_db)) -> None:
    """
    Raises HTTP 503 if maintenance mode is active.
    Use as a dependency on any write endpoint that should be blocked during
    maintenance (POST /api/build, extbuild, etc.).
    """
    result = db.execute(text("SELECT value FROM metadata WHERE name = :k"), {"k": "maintenance_mode"})
    row = result.fetchone()
    if row and row[0] == "true":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Maintenance mode active")
