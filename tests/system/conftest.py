"""Shared fixtures of the system tests. They run in the test runner pod (test-web.Dockerfile) inside the
test cluster and talk to molior at MOLIOR_URL (default http://web:8000)."""
import os
import uuid

import pytest
import requests

MOLIOR_URL = os.environ.get("MOLIOR_URL", "http://web:8000").rstrip("/")
ADMIN_PASSWORD = os.environ["MOLIOR_ADMIN_PASSWORD"]


class Api:
    """Small HTTP client with a cookie session."""

    def __init__(self, base=MOLIOR_URL, headers=None):
        self.base = base
        self.session = requests.Session()
        if headers:
            self.session.headers.update(headers)

    def request(self, method, path, **kwargs):
        kwargs.setdefault("timeout", 30)
        return self.session.request(method, self.base + path, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def login(self, username, password):
        r = self.post("/api/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return self


@pytest.fixture
def public():
    return Api()


@pytest.fixture
def admin():
    return Api().login("admin", ADMIN_PASSWORD)


@pytest.fixture
def unique():
    """A unique, valid molior name (letters, digits, dashes)."""
    return lambda prefix: f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Keeps the result of each phase on the test item (rep_call), so fixtures can take a screenshot on failure."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)
