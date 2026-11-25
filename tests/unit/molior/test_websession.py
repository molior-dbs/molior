"""
Login sessions on the server (molior/fastapi/auth.py, table websession): create, look up, expire, end.

Runs on an in-memory SQLite database with only the websession and molioruser tables.
"""
import hashlib
import importlib
import pkgutil
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# fastapi is in the molior image (molior:dev), not in molior-base:dev
pytest.importorskip("fastapi")
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from molior.fastapi import auth  # noqa: E402
import molior.model  # noqa: E402

# all models, so that the relationships between them can be set up
for _module in pkgutil.iter_modules(molior.model.__path__):
    importlib.import_module("molior.model." + _module.name)
from molior.model.user import User  # noqa: E402
from molior.model.websession import WebSession  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    WebSession.__table__.create(engine)
    User.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(username="alice", is_admin=False))
    session.add(User(username="bob", is_admin=False))
    session.commit()
    yield session
    session.close()


def test_login_stores_only_the_hash(db):
    cookie = auth.create_session(db, "alice")
    assert len(cookie) >= 43     # 32 random bytes, url safe base64
    row = db.query(WebSession).one()
    assert row.token == hashlib.sha256(cookie.encode()).hexdigest()
    assert cookie not in (row.token, row.username)
    assert row.username == "alice"


def test_session_cookie_logs_in(db):
    cookie = auth.create_session(db, "alice")
    user = auth.get_current_user(molior_session=cookie, x_molior_token=None, db=db)
    assert user.username == "alice"
    assert user.is_admin is False
    assert user.auth_token is None


def test_unknown_cookie_does_not_log_in(db):
    auth.create_session(db, "alice")
    assert auth.get_current_user(molior_session="forged", x_molior_token=None, db=db) is None
    assert auth.get_current_user(molior_session=None, x_molior_token=None, db=db) is None


def test_each_login_is_its_own_session(db):
    first, second = auth.create_session(db, "alice"), auth.create_session(db, "alice")
    assert first != second
    assert db.query(WebSession).count() == 2


def test_logout_ends_all_sessions_of_the_user(db):
    """delete_sessions: all browsers of the user, not the sessions of other users."""
    first, second = auth.create_session(db, "alice"), auth.create_session(db, "alice")
    other = auth.create_session(db, "bob")
    assert auth.delete_sessions(db, "alice") == 2
    assert auth.get_current_user(molior_session=first, x_molior_token=None, db=db) is None
    assert auth.get_current_user(molior_session=second, x_molior_token=None, db=db) is None
    assert auth.get_current_user(molior_session=other, x_molior_token=None, db=db).username == "bob"


def test_expired_session_does_not_log_in(db):
    cookie = auth.create_session(db, "alice")
    later = datetime.now(timezone.utc) + timedelta(seconds=auth.SESSION_MAX_AGE + 1)
    with patch.object(auth, "datetime") as fake:
        fake.now.return_value = later
        assert auth.get_current_user(molior_session=cookie, x_molior_token=None, db=db) is None
        assert auth.session_expiry(db, cookie) is None


def test_session_expiry(db):
    before = datetime.now(timezone.utc).timestamp()
    cookie = auth.create_session(db, "alice")
    expiry = auth.session_expiry(db, cookie)
    assert before + auth.SESSION_MAX_AGE - 1 <= expiry <= before + auth.SESSION_MAX_AGE + 5
    assert auth.session_expiry(db, "forged") is None


def test_login_removes_expired_sessions(db):
    old = auth.create_session(db, "bob")
    later = datetime.now(timezone.utc) + timedelta(seconds=auth.SESSION_MAX_AGE + 1)
    with patch.object(auth, "datetime") as fake:
        fake.now.return_value = later
        auth.create_session(db, "alice")
    assert db.query(WebSession).filter(WebSession.token == hashlib.sha256(old.encode()).hexdigest()).count() == 0
    assert db.query(WebSession).count() == 1


def test_deleted_user_does_not_log_in(db):
    """The session row alone is not enough: the user must exist."""
    cookie = auth.create_session(db, "alice")
    db.query(User).filter_by(username="alice").delete()
    db.commit()
    assert auth.get_current_user(molior_session=cookie, x_molior_token=None, db=db) is None


def test_admin_session(db):
    cookie = auth.create_session(db, "admin")
    user = auth.get_current_user(molior_session=cookie, x_molior_token=None, db=db)
    assert user.username == "admin"
    assert user.is_admin is True
