"""
/debootstrap/ of the web server (molior/fastapi/app.py): molior-deploy downloads the root file system of a base
mirror there (curl -f) and runs debootstrap itself when it gets an error. So a missing file or directory must be a
404, never the index.html of the web UI (200) or a server error.

Calls the ASGI app directly (no HTTP client needed). The app has only the files and the web UI
(mount_static_files), as create_app mounts them after the API routes; the routers need /etc/molior/molior.yml.
"""
import asyncio
import importlib.util
import sys
import types

import pytest

# fastapi is in the molior image (molior:dev), not in molior-base:dev
pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402

# molior/version.py is written by debian/rules (not in git); app.py imports it
if importlib.util.find_spec("molior.version") is None:
    sys.modules["molior.version"] = types.SimpleNamespace(MOLIOR_VERSION="0")

from molior.fastapi.app import mount_static_files  # noqa: E402


def get(app, path):
    """GET path from the ASGI app, returns (status, body)."""
    messages = []
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"", "headers": [],
             "server": ("test", 80), "client": ("test", 1)}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, body


@pytest.fixture
def web_dir(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<html><base href="./"></html>')
    return web


def make_app(monkeypatch, web_dir, debootstrap_dir):
    monkeypatch.setenv("MOLIOR_WEB_DIR", str(web_dir))
    monkeypatch.setenv("MOLIOR_DEBOOTSTRAP_DIR", str(debootstrap_dir))
    app = FastAPI()
    mount_static_files(app)
    return app


def test_existing_tarball_is_served(monkeypatch, tmp_path, web_dir):
    debootstrap = tmp_path / "debootstrap"
    debootstrap.mkdir()
    (debootstrap / "trixie_13_amd64.tar.xz").write_bytes(b"\xfd7zXZ\x00 data")
    app = make_app(monkeypatch, web_dir, debootstrap)
    assert get(app, "/debootstrap/trixie_13_amd64.tar.xz") == (200, b"\xfd7zXZ\x00 data")


def test_missing_tarball_is_404_not_the_web_ui(monkeypatch, tmp_path, web_dir):
    debootstrap = tmp_path / "debootstrap"
    debootstrap.mkdir()
    app = make_app(monkeypatch, web_dir, debootstrap)
    status, body = get(app, "/debootstrap/trixie_13_amd64.tar.xz")
    assert status == 404
    assert b"<html>" not in body


def test_missing_directory_is_404(monkeypatch, tmp_path, web_dir):
    app = make_app(monkeypatch, web_dir, tmp_path / "no-such-dir")
    assert get(app, "/debootstrap/trixie_13_amd64.tar.xz")[0] == 404


def test_directory_created_later_is_served(monkeypatch, tmp_path, web_dir):
    """The first base mirror creates the tarball after molior started."""
    debootstrap = tmp_path / "debootstrap"
    app = make_app(monkeypatch, web_dir, debootstrap)
    assert get(app, "/debootstrap/trixie_13_amd64.tar.xz")[0] == 404
    debootstrap.mkdir()
    (debootstrap / "trixie_13_amd64.tar.xz").write_bytes(b"tar")
    assert get(app, "/debootstrap/trixie_13_amd64.tar.xz") == (200, b"tar")


def test_no_path_outside_the_directory(monkeypatch, tmp_path, web_dir):
    debootstrap = tmp_path / "debootstrap"
    debootstrap.mkdir()
    (tmp_path / "secret").write_text("secret")
    app = make_app(monkeypatch, web_dir, debootstrap)
    status, body = get(app, "/debootstrap/../secret")
    assert b"secret" not in body
    assert status == 404


def test_other_paths_still_get_the_web_ui(monkeypatch, tmp_path, web_dir):
    app = make_app(monkeypatch, web_dir, tmp_path / "debootstrap")
    status, body = get(app, "/project/foo/1")
    assert status == 200
    assert b"<html>" in body
