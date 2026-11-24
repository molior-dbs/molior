"""Helpers of the system tests: the API client and the test settings. A plain module, not conftest.py, so test
modules can import it (several conftest.py files share the module name conftest)."""
import os

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
