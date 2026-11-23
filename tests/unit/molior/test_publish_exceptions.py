"""
Tests for AptlyWorker._publish / _src_publish (molior/molior/worker_aptly.py):
an exception while publishing (for example in retention_cleanup) must not leave the
build in "publishing", because every build depending on it would wait for it.

The heavy imports are replaced by stubs, the real source file is loaded.
"""
import asyncio
import importlib.util
import sys
import types

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3] / "molior"


class FakeBuild:
    def __init__(self, id, buildstate, buildtype="deb"):
        self.id = id
        self.buildstate = buildstate
        self.buildtype = buildtype
        self.parent_id = id - 1
        self.log = []

    async def set_publish_failed(self):
        self.buildstate = "publish_failed"

    async def set_publishing(self):
        self.buildstate = "publishing"

    async def set_failed(self):
        self.buildstate = "build_failed"

    async def set_successful(self):
        self.buildstate = "successful"


class Col:
    def __eq__(self, value):
        return value


class StubBuildModel:
    id = Col()


class FakeSession:
    def __init__(self, builds):
        self.builds = builds
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, *args):
        return self

    def filter(self, build_id):
        self.build_id = build_id
        return self

    def first(self):
        return self.builds.get(self.build_id)

    def commit(self):
        self.commits += 1


@pytest.fixture
def env():
    """The module molior.molior.worker_aptly with stubbed dependencies."""
    state = SimpleState()

    def coro_mock(name):
        async def func(*args, **kwargs):
            state.calls.append((name,) + args)
        return func

    queues = MagicMock(
        enqueue_task=coro_mock("enqueue_task"), buildlog=coro_mock("buildlog"),
        buildlogtitle=coro_mock("buildlogtitle"), buildlogdone=coro_mock("buildlogdone"),
        enqueue_backend=coro_mock("enqueue_backend"))
    session = FakeSession(state.builds)
    stubs = {
        "sqlalchemy": MagicMock(),
        "molior.logger": MagicMock(),
        "molior.tools": MagicMock(),
        "molior.ops": MagicMock(),
        "molior.aptly": MagicMock(),
        "molior.aptly.errors": MagicMock(),
        "molior.molior.debianrepository": MagicMock(),
        "molior.molior.notifier": MagicMock(),
        "molior.molior.queues": queues,
        "molior.molior.configuration": MagicMock(),
        "molior.model.database": MagicMock(Session=lambda: session),
        "molior.model.build": MagicMock(Build=StubBuildModel),
        "molior.model.project": MagicMock(),
        "molior.model.projectversion": MagicMock(),
        "molior.model.chroot": MagicMock(),
        "molior.model.mirrorkey": MagicMock(),
        "molior.model.buildtask": MagicMock(),
        "molior.model.sourepprover": MagicMock(),
        "molior.model.metadata": MagicMock(),
    }
    molior_pkg = types.ModuleType("molior.molior")
    molior_pkg.__path__ = [str(ROOT / "molior")]
    stubs["molior.molior"] = molior_pkg
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("molior.molior.worker_aptly", ROOT / "molior" / "worker_aptly.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["molior.molior.worker_aptly"] = module
        spec.loader.exec_module(module)
        state.worker = module.AptlyWorker()
        state.session = session
        state.module = module
        yield state


class SimpleState:
    def __init__(self):
        self.builds = {}
        self.calls = []

    def names(self):
        return [c[0] for c in self.calls]


def raising(exc):
    async def func(*args, **kwargs):
        raise exc
    return func


# ---------------------------------------------------------------- deb

def test_exception_in_publish_sets_publish_failed(env):
    """An exception after set_publishing() (e.g. retention_cleanup) must end in publish_failed."""
    env.builds[10] = FakeBuild(10, "publishing", "deb")
    env.worker._do_publish = raising(RuntimeError("retention broke"))

    asyncio.run(env.worker._publish([10]))

    assert env.builds[10].buildstate == "publish_failed"
    assert env.session.commits == 1
    # the reason is in the build log, the log is closed, the dependants get a new schedule run
    assert any(c[0] == "buildlog" and c[1] == 10 and "retention broke" in c[2] for c in env.calls)
    assert ("buildlogdone", 10) in env.calls
    assert ("enqueue_task", {"schedule": []}) in env.calls


def test_exception_while_needs_publish_sets_publish_failed(env):
    """An exception before set_publishing() (e.g. while reading the build) is covered too."""
    env.builds[10] = FakeBuild(10, "needs_publish", "deb")
    env.worker._do_publish = raising(RuntimeError("boom"))
    asyncio.run(env.worker._publish([10]))
    assert env.builds[10].buildstate == "publish_failed"


def test_no_exception_nothing_changes(env):
    env.builds[10] = FakeBuild(10, "publishing", "deb")

    async def ok(args):
        return None

    env.worker._do_publish = ok
    asyncio.run(env.worker._publish([10]))
    assert env.builds[10].buildstate == "publishing"
    assert env.calls == []


@pytest.mark.parametrize("state", ["successful", "build_failed", "publish_failed"])
def test_exception_after_the_build_was_finished_does_not_change_it(env, state):
    """E.g. an abort set the build to build_failed, or the exception came after set_successful()."""
    env.builds[10] = FakeBuild(10, state, "deb")
    env.worker._do_publish = raising(RuntimeError("late error"))
    asyncio.run(env.worker._publish([10]))
    assert env.builds[10].buildstate == state
    assert env.calls == []


def test_exception_for_unknown_build_is_only_logged(env):
    env.worker._do_publish = raising(RuntimeError("boom"))
    asyncio.run(env.worker._publish([99]))  # must not raise
    assert env.calls == []


def test_error_handler_failure_does_not_escape(env):
    """The aptly worker loop must go on, even if the error handling itself fails."""
    env.builds[10] = FakeBuild(10, "publishing", "deb")
    env.worker._do_publish = raising(RuntimeError("boom"))

    async def broken(*args, **kwargs):
        raise RuntimeError("db down")

    env.builds[10].set_publish_failed = broken
    asyncio.run(env.worker._publish([10]))  # must not raise


# ---------------------------------------------------------------- source

def test_exception_in_src_publish_sets_publish_failed(env):
    env.builds[20] = FakeBuild(20, "publishing", "source")
    env.worker._do_src_publish = raising(RuntimeError("boom"))

    asyncio.run(env.worker._src_publish([20]))

    assert env.builds[20].buildstate == "publish_failed"
    assert ("buildlogdone", 20) in env.calls
    assert ("buildlogdone", 19) in env.calls, "the log of the top build is closed too"
    # a source publish does not release dependants, so no schedule run
    assert not any(c[0] == "enqueue_task" for c in env.calls)


def test_exception_in_src_publish_after_success_is_ignored(env):
    env.builds[20] = FakeBuild(20, "successful", "source")
    env.worker._do_src_publish = raising(RuntimeError("late error"))
    asyncio.run(env.worker._src_publish([20]))
    assert env.builds[20].buildstate == "successful"
    assert env.calls == []


# ---------------------------------------------------------------- the real _publish, retention_cleanup raises

def real_deb_build(id):
    """A fake build with the attributes _do_publish reads before retention_cleanup."""
    build = FakeBuild(id, "needs_publish", "deb")
    pv = types.SimpleNamespace(
        basemirror=types.SimpleNamespace(project=types.SimpleNamespace(name="base"), name="1.0"),
        project=types.SimpleNamespace(name="proj"), name="1", mirror_architectures="{amd64}", publish_s3=False)
    build.projectversion = pv
    build.parent = types.SimpleNamespace(parent=types.SimpleNamespace(id=1))
    build.sourcename = "foo"
    build.version = "1.0"
    build.architecture = "amd64"
    build.is_ci = False
    return build


def test_real_publish_retention_cleanup_raises_still_publishes(env):
    """retention_cleanup is housekeeping: an error is logged, the build is published without removals."""
    build = real_deb_build(10)
    env.builds[10] = build
    env.module.retention_cleanup = raising(RuntimeError("retention broke"))
    env.module.db2array = lambda a: a
    published = []

    async def deb_publish(*args, **kwargs):
        published.append(args)
        return True

    env.module.DebPublish = deb_publish

    asyncio.run(env.worker._publish([10]))

    assert build.buildstate == "successful"
    assert len(published) == 1
    assert published[0][-1] == [], "nothing is removed from aptly"  # remove_packages (publish_s3 is a keyword)
    assert any(c[0] == "buildlog" and c[1] == 10 and "retention broke" in c[2] for c in env.calls)
    assert ("enqueue_task", {"schedule": []}) in env.calls


def test_real_publish_failure_inside_is_publish_failed(env):
    """DebPublish raises: handled inside _do_publish, the build ends in publish_failed."""
    build = real_deb_build(10)
    env.builds[10] = build

    async def retention(session, build):
        return [], []

    env.module.retention_cleanup = retention
    env.module.db2array = lambda a: a
    env.module.DebPublish = raising(RuntimeError("publish broke"))
    asyncio.run(env.worker._publish([10]))
    assert build.buildstate == "publish_failed"


def test_real_publish_exception_outside_retention_sets_publish_failed(env):
    """An exception that _do_publish does not catch itself (here: no projectversion) is handled by the wrapper."""
    build = real_deb_build(10)
    build.projectversion = None  # build.projectversion.basemirror raises AttributeError
    env.builds[10] = build
    asyncio.run(env.worker._publish([10]))
    assert build.buildstate == "publish_failed"
    assert ("enqueue_task", {"schedule": []}) in env.calls


# ---------------------------------------------------------------- the "Done" footer is written once

def count(env, name, build_id):
    return len([c for c in env.calls if c[0] == name and c[1] == build_id])


def test_done_footer_only_once_when_exception_comes_late(env):
    """The normal path closed the log, then an exception: no second footer, the log is closed again."""
    env.builds[10] = FakeBuild(10, "publishing", "deb")

    async def late(args):
        await env.worker._log_done(10, no_header_newline=False)  # as the normal path does
        raise RuntimeError("late error")

    env.worker._do_publish = late
    asyncio.run(env.worker._publish([10]))

    assert count(env, "buildlogtitle", 10) == 1, "one footer"
    assert count(env, "buildlogdone", 10) == 2, "the writer opened for the error line is closed"
    assert env.builds[10].buildstate == "publish_failed"


def test_done_footer_written_when_log_was_not_closed(env):
    env.builds[10] = FakeBuild(10, "publishing", "deb")
    env.worker._do_publish = raising(RuntimeError("early error"))
    asyncio.run(env.worker._publish([10]))
    assert count(env, "buildlogtitle", 10) == 1
    assert count(env, "buildlogdone", 10) == 1


def test_done_record_is_reset_for_every_publish(env):
    """A footer was written for build 10; a later publish of the same build id writes it again."""
    env.builds[10] = FakeBuild(10, "publishing", "deb")
    env.worker._do_publish = raising(RuntimeError("one"))
    asyncio.run(env.worker._publish([10]))
    env.builds[10].buildstate = "publishing"
    asyncio.run(env.worker._publish([10]))
    assert count(env, "buildlogtitle", 10) == 2


# ---------------------------------------------------------------- abort

class AbortSession:
    """Session for _abort_projectversion: all() returns the prepared lists in order."""
    def __init__(self, results, building=0):
        self.results = list(results)
        self.building = building
        self.deleted = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def all(self):
        return self.results.pop(0)

    def count(self):
        return self.building

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1


def abortable(id, state, buildtype="deb"):
    build = FakeBuild(id, state, buildtype)
    build.buildtask = None
    build.children = []
    topbuild = FakeBuild(id - 100, "building", "build")
    topbuild.logs = []

    async def log(msg):
        topbuild.logs.append(msg)

    topbuild.log = log
    build.parent = types.SimpleNamespace(parent=topbuild, log=log)
    return build


def test_abort_projectversion_needs_publish_becomes_publish_failed(env):
    """Aborting a build that waits for its publish: it is built, only the publish is aborted."""
    debs = [abortable(1, "needs_publish"), abortable(2, "new"), abortable(3, "needs_build"),
            abortable(4, "building"), abortable(5, "publishing")]
    sources = [abortable(11, "needs_publish", "source"), abortable(12, "new", "source"),
               abortable(13, "publishing", "source")]
    env.module.Build = MagicMock()
    env.module.Session = lambda: AbortSession([debs, sources])

    asyncio.run(env.worker._abort_projectversion([7]))

    assert [d.buildstate for d in debs] == ["publish_failed", "build_failed", "build_failed",
                                            "build_failed", "build_failed"]
    assert [s.buildstate for s in sources] == ["publish_failed", "build_failed", "build_failed"]
    # only the build on a node is aborted there
    assert [c for c in env.calls if c[0] == "enqueue_backend"] == [("enqueue_backend", {"abort": 4})]


def srcbuild_with_debs(states, src_state="successful"):
    src = abortable(50, src_state, "source")
    src.children = [abortable(60 + n, state) for n, state in enumerate(states)]
    top = FakeBuild(40, "building", "build")
    top.children = [src]
    top.buildtask = None
    return top, src


def abort_single(env, top):
    session = FakeSession({40: top})
    session.delete = lambda obj: None
    env.module.Session = lambda: session
    asyncio.run(env.worker._abort([40]))


def test_abort_top_build_needs_publish_becomes_publish_failed(env):
    top, src = srcbuild_with_debs(["needs_publish", "needs_build", "building", "successful"])
    abort_single(env, top)
    assert [d.buildstate for d in src.children] == ["publish_failed", "build_failed", "building", "successful"]
    assert top.buildstate == "build_failed"
    assert [c for c in env.calls if c[0] == "enqueue_backend"] == [("enqueue_backend", {"abort": 62})]


def test_abort_top_build_source_waiting_for_publish(env):
    top, src = srcbuild_with_debs(["new"], src_state="needs_publish")
    abort_single(env, top)
    assert src.buildstate == "publish_failed"
    assert src.children[0].buildstate == "build_failed"


def test_abort_top_build_leaves_finished_states_alone(env):
    top, src = srcbuild_with_debs(["successful", "publish_failed", "build_failed"])
    abort_single(env, top)
    assert [d.buildstate for d in src.children] == ["successful", "publish_failed", "build_failed"]
    assert src.buildstate == "successful"


# a publish task which is still in the queue must not publish an aborted build

@pytest.mark.parametrize("state", ["build_failed", "publish_failed"])
def test_queued_publish_of_aborted_build_is_skipped(env, state):
    env.builds[10] = FakeBuild(10, state, "deb")
    asyncio.run(env.worker._do_publish([10]))
    assert env.builds[10].buildstate == state
    assert env.calls == []


@pytest.mark.parametrize("state", ["build_failed", "publish_failed"])
def test_queued_src_publish_of_aborted_build_is_skipped(env, state):
    env.builds[20] = FakeBuild(20, state, "source")
    assert asyncio.run(env.worker._do_src_publish([20])) is False
    assert env.builds[20].buildstate == state
    assert env.calls == []
