"""
Tests for cleanup_builds() (molior/molior/worker.py), which runs at every molior start.

The heavy imports of worker.py (sqlalchemy models, ops, giturlparse) are replaced by stubs,
and the Build "columns" evaluate their filters against fake builds, so the filter
conditions of cleanup_builds() are really tested.
"""
import asyncio
import importlib
import sys

from unittest.mock import MagicMock, patch


class Col:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return lambda b: getattr(b, self.name) == value

    def in_(self, values):
        return lambda b: getattr(b, self.name) in values


class StubBuild:
    buildstate = Col("buildstate")
    buildtype = Col("buildtype")


class FakeBuild:
    def __init__(self, id, buildstate, buildtype="deb", buildtask=None):
        self.id = id
        self.buildstate = buildstate
        self.buildtype = buildtype
        self.buildtask = buildtask

    async def set_failed(self):
        self.buildstate = "build_failed"

    async def set_publish_failed(self):
        self.buildstate = "publish_failed"

    async def set_needs_build(self):
        self.buildstate = "needs_build"


class FakeSession:
    def __init__(self, builds):
        self.builds = builds
        self.deleted = []
        self.commits = 0

    def query(self, _model):
        return FakeQuery(self.builds)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeQuery:
    def __init__(self, builds, preds=()):
        self.builds = builds
        self.preds = preds

    def filter(self, *preds):
        return FakeQuery(self.builds, self.preds + preds)

    def all(self):
        return [b for b in self.builds if all(p(b) for p in self.preds)]


def run_cleanup(builds):
    """Runs cleanup_builds() on the given fake builds, returns the fake session."""
    session = FakeSession(builds)
    stubs = {
        "giturlparse": MagicMock(),
        "molior.logger": MagicMock(),
        "molior.ops": MagicMock(),
        "molior.molior.configuration": MagicMock(),
        "molior.molior.queues": MagicMock(),
        "molior.model.database": MagicMock(Session=lambda: session),
        "molior.model.build": MagicMock(Build=StubBuild),
        "molior.model.chroot": MagicMock(),
        "molior.model.sourcerepository": MagicMock(),
        "molior.model.sourepprover": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        sys.modules.pop("molior.molior.worker", None)
        worker = importlib.import_module("molior.molior.worker")
        asyncio.run(worker.cleanup_builds())
        sys.modules.pop("molior.molior.worker", None)
    return session


def test_needs_publish_becomes_publish_failed():
    """The aptly queue is in memory, so builds waiting in it are lost at a restart."""
    src = FakeBuild(1, "needs_publish", "source")
    deb = FakeBuild(2, "needs_publish", "deb")
    session = run_cleanup([src, deb])
    assert src.buildstate == "publish_failed"
    assert deb.buildstate == "publish_failed"
    assert session.commits == 1


def test_publishing_becomes_publish_failed():
    build = FakeBuild(1, "publishing")
    run_cleanup([build])
    assert build.buildstate == "publish_failed"


def test_buildtask_of_publish_builds_is_deleted():
    task = object()
    build = FakeBuild(1, "needs_publish", buildtask=task)
    session = run_cleanup([build])
    assert session.deleted == [task]


def test_building_becomes_build_failed():
    build = FakeBuild(1, "building")
    run_cleanup([build])
    assert build.buildstate == "build_failed"


def test_other_states_are_not_touched():
    builds = [FakeBuild(i, state, "source") for i, state in enumerate(
        ["new", "needs_build", "successful", "build_failed", "publish_failed", "already_exists"])]
    states = [b.buildstate for b in builds]
    session = run_cleanup(builds)
    assert [b.buildstate for b in builds] == states
    assert session.commits == 0


def test_scheduled_deb_goes_back_to_needs_build():
    deb = FakeBuild(1, "scheduled", "deb")
    run_cleanup([deb])
    assert deb.buildstate == "needs_build"


def test_needs_build_deb_is_not_touched():
    """Regression: the filters used Python 'and', which dropped the first condition."""
    deb = FakeBuild(1, "needs_build", "deb")
    session = run_cleanup([deb])
    assert deb.buildstate == "needs_build"
    assert session.commits == 0


def test_needs_build_chroot_becomes_build_failed():
    chroot = FakeBuild(1, "needs_build", "chroot")
    run_cleanup([chroot])
    assert chroot.buildstate == "build_failed"
