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
    id = Col("id")
    buildstate = Col("buildstate")
    buildtype = Col("buildtype")


class FakeBuild:
    def __init__(self, id, buildstate, buildtype="deb", buildtask=None):
        self.id = id
        self.buildstate = buildstate
        self.buildtype = buildtype
        self.buildtask = buildtask
        self.children = []

    async def set_failed(self):
        self.buildstate = "build_failed"
        if self.buildtype == "deb" and getattr(self, "parent", None) and self.parent.parent.buildstate != "build_failed":
            await self.parent.parent.set_failed()  # as Build.set_failed: the top build fails with its deb

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

    def order_by(self, key):
        return self

    def all(self):
        return sorted((b for b in self.builds if all(p(b) for p in self.preds)), key=lambda b: b.id)


def run_worker(function, builds):
    """Runs worker.<function>() on the fake builds. Returns the fake session and the queued tasks."""
    session = FakeSession(builds)
    queued = []

    async def enqueue_aptly(task):
        queued.append(("aptly", task))

    async def enqueue_task(task):
        queued.append(("task", task))

    stubs = {
        "giturlparse": MagicMock(),
        "molior.logger": MagicMock(),
        "molior.ops": MagicMock(),
        "molior.molior.configuration": MagicMock(),
        "molior.molior.queues": MagicMock(enqueue_aptly=enqueue_aptly, enqueue_task=enqueue_task),
        "molior.model.database": MagicMock(Session=lambda: session),
        "molior.model.build": MagicMock(Build=StubBuild),
        "molior.model.chroot": MagicMock(),
        "molior.model.sourcerepository": MagicMock(),
        "molior.model.sourepprover": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        sys.modules.pop("molior.molior.worker", None)
        worker = importlib.import_module("molior.molior.worker")
        asyncio.run(getattr(worker, function)())
        sys.modules.pop("molior.molior.worker", None)
    return session, queued


def run_cleanup(builds):
    """Runs cleanup_builds() on the given fake builds, returns the fake session."""
    return run_worker("cleanup_builds", builds)[0]


def test_needs_publish_is_kept():
    """Builds waiting for their publish are not lost: they keep their state and their buildtask."""
    task = object()
    src = FakeBuild(1, "needs_publish", "source", buildtask=task)
    deb = FakeBuild(2, "needs_publish", "deb")
    session = run_cleanup([src, deb])
    assert src.buildstate == "needs_publish"
    assert deb.buildstate == "needs_publish"
    assert session.deleted == []
    assert session.commits == 0


def test_publishing_becomes_publish_failed():
    build = FakeBuild(1, "publishing")
    run_cleanup([build])
    assert build.buildstate == "publish_failed"


def test_buildtask_of_publishing_build_is_deleted():
    task = object()
    build = FakeBuild(1, "publishing", buildtask=task)
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


# ---------------------------------------------------------------- top level builds with pending work

def tree(source_state, deb_states, top_state="building"):
    """A top level build with one source build and deb builds. Returns top, source, debs."""
    top = FakeBuild(100, top_state, "build")
    source = FakeBuild(101, source_state, "source")
    debs = [FakeBuild(102 + n, state, "deb") for n, state in enumerate(deb_states)]
    top.children = [source]
    source.children = debs
    return top, source, debs


def test_top_build_with_pending_debs_is_not_failed():
    """The needs_build and needs_publish debs are continued after the start, so the top build stays building."""
    top, source, debs = tree("successful", ["needs_build", "needs_publish", "successful"])
    session = run_cleanup([top])
    assert top.buildstate == "building"
    assert session.commits == 0


def test_top_build_with_source_waiting_for_publish_is_not_failed():
    top, source, debs = tree("needs_publish", ["new"])
    run_cleanup([top, source, *debs])
    assert top.buildstate == "building"


def test_top_build_with_scheduled_deb_is_not_failed_and_deb_goes_back_to_needs_build():
    top, source, debs = tree("successful", ["scheduled"])
    run_cleanup([top, *debs])
    assert top.buildstate == "building"
    assert debs[0].buildstate == "needs_build"


def test_top_build_without_pending_work_is_failed():
    top, source, debs = tree("successful", ["successful", "build_failed", "new"])
    run_cleanup([top])
    assert top.buildstate == "build_failed"


def test_building_deb_still_fails_and_its_top_build_with_it():
    """
    A deb that was building has lost its build (no resume yet): it fails. As in the model (Build.set_failed),
    the failure of a deb fails its top build, also if another deb of it waits for its build.
    """
    top, source, debs = tree("successful", ["building", "needs_build"])
    source.parent = top
    for deb in debs:
        deb.parent = source
    run_cleanup([top, *debs])
    assert debs[0].buildstate == "build_failed"
    assert debs[1].buildstate == "needs_build"
    assert top.buildstate == "build_failed"


# ---------------------------------------------------------------- queue at the start

def test_needs_publish_builds_are_queued_in_id_order_then_the_scheduler_runs():
    builds = [
        FakeBuild(30, "needs_publish", "deb"),
        FakeBuild(10, "needs_publish", "source"),
        FakeBuild(20, "needs_publish", "deb"),
        FakeBuild(5, "needs_publish", "source"),   # old rows are queued too: no age limit
        FakeBuild(40, "successful", "deb"),
        FakeBuild(41, "needs_build", "deb"),
        FakeBuild(42, "needs_publish", "chroot"),  # chroot builds do not use the aptly queue
    ]
    session, queued = run_worker("queue_pending_builds", builds)
    assert queued == [
        ("aptly", {"src_publish": [5]}),
        ("aptly", {"src_publish": [10]}),
        ("aptly", {"publish": [20]}),
        ("aptly", {"publish": [30]}),
        ("task", {"schedule": []}),
    ]
    assert session.commits == 0
    assert all(b.buildstate in ["needs_publish", "successful", "needs_build"] for b in builds)


def test_scheduler_runs_also_if_nothing_waits_for_publishing():
    session, queued = run_worker("queue_pending_builds", [FakeBuild(1, "needs_build", "deb")])
    assert queued == [("task", {"schedule": []})]
