"""
Tests for the retry of a failed mirror build (PUT /api2/build/{id}, molior/fastapi/routers/v2/build.py).

Case: a mirror build (trixie/13.8) failed because its arm64 and armhf chroot builds failed. The retry of the
mirror build retries the failed chroot builds; without failed chroot builds it updates the mirror.
"""
import asyncio

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# fastapi is in the molior image (molior:dev), not in molior-base:dev
fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException
from molior.fastapi.routers.v2 import build as build_router  # noqa: E402


class FakeBuild:
    def __init__(self, id, buildtype, buildstate, children=(), projectversion=None):
        self.id = id
        self.buildtype = buildtype
        self.buildstate = buildstate
        self.children = list(children)
        self.projectversion = projectversion

    async def set_needs_build(self):
        self.buildstate = "needs_build"

    async def set_building(self):
        self.buildstate = "building"


def mirror_build(mirror_state="error", chroot_states=("successful", "successful", "build_failed", "build_failed"),
                 is_locked=False):
    mirror = SimpleNamespace(id=30879, mirror_state=mirror_state, is_locked=is_locked)
    chroots = [FakeBuild(101 + i, "chroot", state) for i, state in enumerate(chroot_states)]
    return FakeBuild(100, "mirror", "build_failed", chroots, mirror)


def retry(build, is_admin=True):
    user = SimpleNamespace(is_admin=is_admin)
    db = MagicMock()
    enqueue_task = AsyncMock()
    enqueue_aptly = AsyncMock()
    with patch.object(build_router, "enqueue_task", enqueue_task), \
            patch.object(build_router, "enqueue_aptly", enqueue_aptly):
        result = asyncio.run(build_router._retry_mirror_build(build, user, db))
    return result, enqueue_task, enqueue_aptly, db


def test_retry_restarts_only_the_failed_chroots():
    build = mirror_build()
    result, enqueue_task, enqueue_aptly, db = retry(build)
    assert result == "Rebuild triggered"
    assert [c.args[0] for c in enqueue_task.call_args_list] == [
        {"rebuild": [103, "build_failed"]}, {"rebuild": [104, "build_failed"]}]
    assert [c.buildstate for c in build.children] == ["successful", "successful", "needs_build", "needs_build"]
    assert build.buildstate == "building"
    enqueue_aptly.assert_not_called()
    db.commit.assert_called_once()


def test_retry_publish_failed_chroot():
    build = mirror_build(chroot_states=("publish_failed", "successful"))
    _, enqueue_task, _, _ = retry(build)
    enqueue_task.assert_called_once_with({"rebuild": [101, "publish_failed"]})


@pytest.mark.parametrize("mirror_state,task", [("error", "update_mirror"), ("init_error", "init_mirror"),
                                               ("new", "init_mirror")])
def test_retry_without_failed_chroots_starts_the_mirror_update(mirror_state, task):
    build = mirror_build(mirror_state=mirror_state, chroot_states=())
    result, enqueue_task, enqueue_aptly, _ = retry(build)
    assert result == "Mirror update started"
    enqueue_aptly.assert_called_once_with({task: [30879]})
    enqueue_task.assert_not_called()


def test_retry_locked_mirror_update_is_refused():
    build = mirror_build(chroot_states=(), is_locked=True)
    with pytest.raises(HTTPException) as exc:
        retry(build)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("mirror_state", ["ready", "updating", "publishing", "created"])
def test_retry_nothing_to_retry(mirror_state):
    build = mirror_build(mirror_state=mirror_state, chroot_states=("successful",))
    with pytest.raises(HTTPException) as exc:
        retry(build)
    assert exc.value.status_code == 400


def test_retry_needs_admin():
    with pytest.raises(HTTPException) as exc:
        retry(mirror_build(), is_admin=False)
    assert exc.value.status_code == 403


def test_rebuild_endpoint_uses_the_mirror_retry():
    """PUT /api2/build/{id} on a mirror build goes to the mirror retry, not to the worker's rebuild task."""
    build = mirror_build()
    build.can_rebuild = MagicMock(return_value=True)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = build
    user = SimpleNamespace(is_admin=True)
    with patch.object(build_router, "enqueue_task", AsyncMock()) as enqueue_task, \
            patch.object(build_router, "enqueue_aptly", AsyncMock()):
        asyncio.run(build_router.rebuild_build(100, user, db))
    assert {"rebuild": [100, "build_failed"]} not in [c.args[0] for c in enqueue_task.call_args_list]
    assert enqueue_task.call_count == 2
