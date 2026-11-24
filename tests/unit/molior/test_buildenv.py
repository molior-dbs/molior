"""
Tests for CreateBuildEnv() (molior/ops/buildenv.py): the build environments (chroot builds) of a base mirror.

The imports of buildenv.py (launchy, models, queues) are replaced by stubs. The mirror hooks (run-parts) are a fake
Launchy that returns a given exit code for "build" and for "publish".
"""
import asyncio
import importlib.util
import os
import sys

from unittest.mock import MagicMock, patch

BUILDENV_PY = os.path.join(os.path.dirname(__file__), "..", "..", "..", "molior", "ops", "buildenv.py")


class FakeBuild:
    def __init__(self, id, buildtype, parent=None):
        self.id = id
        self.buildtype = buildtype
        self.buildstate = "new"
        self.parent = parent
        self.children = []
        self.logdone_called = False

    async def logtitle(self, *args, **kwargs):
        pass

    async def log(self, *args, **kwargs):
        pass

    async def logdone(self):
        self.logdone_called = True

    async def set_building(self):
        self.buildstate = "building"

    async def set_needs_publish(self):
        self.buildstate = "needs_publish"

    async def set_publishing(self):
        self.buildstate = "publishing"

    async def set_successful(self):
        self.buildstate = "successful"

    async def set_failed(self):
        self.buildstate = "build_failed"

    async def set_publish_failed(self):
        self.buildstate = "publish_failed"


class FakeMirror:
    def __init__(self):
        self.mirror_state = "publishing"
        self.is_locked = False

    async def set_mirror_state(self, state):
        self.mirror_state = state


class FakeChroot:
    def __init__(self, basemirror):
        self.id = 7
        self.basemirror = basemirror
        self.ready = False


class FakeQuery:
    def __init__(self, obj):
        self.obj = obj

    def filter(self, *args):
        return self

    def first(self):
        return self.obj


class FakeSession:
    def __init__(self, build, chroot):
        self.build = build
        self.chroot = chroot

    def query(self, model):
        return FakeQuery(self.chroot if model is StubChroot else self.build)

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class StubBuild:
    id = MagicMock()


class StubChroot:
    id = MagicMock()


def run_buildenv(build_rc, publish_rc):
    """Runs CreateBuildEnv for one chroot build below a mirror build. Returns (result, chroot build, mirror build,
    mirror, chroot, queued tasks)."""
    mirror_build = FakeBuild(1, "mirror")
    build = FakeBuild(2, "chroot", parent=mirror_build)
    mirror_build.children = [build]
    mirror = FakeMirror()
    chroot = FakeChroot(mirror)
    session = FakeSession(build, chroot)
    queued = []

    class FakeLaunchy:
        def __init__(self, cmd, out, err):
            self.rc = build_rc if cmd[3] == "build" else publish_rc

        async def launch(self):
            pass

        async def wait(self):
            return self.rc

    async def enqueue_task(task):
        queued.append(task)

    async def buildlog(*args):
        pass

    stubs = {
        "launchy": MagicMock(Launchy=FakeLaunchy),
        "molior.ops": MagicMock(),
        "molior.logger": MagicMock(),
        "molior.model.database": MagicMock(Session=lambda: session),
        "molior.model.build": MagicMock(Build=StubBuild),
        "molior.model.chroot": MagicMock(Chroot=StubChroot),
        "molior.molior.queues": MagicMock(enqueue_task=enqueue_task, buildlog=buildlog),
    }
    with patch.dict(sys.modules, stubs):
        sys.modules.pop("molior.ops.buildenv", None)
        # load buildenv.py alone (molior/ops/__init__.py imports all ops and the real models)
        spec = importlib.util.spec_from_file_location("molior.ops.buildenv", BUILDENV_PY)
        buildenv = importlib.util.module_from_spec(spec)
        sys.modules["molior.ops.buildenv"] = buildenv
        spec.loader.exec_module(buildenv)
        ret = asyncio.run(buildenv.CreateBuildEnv(chroot.id, build.id, "trixie", "trixie", "13", "amd64", "main",
                                                  "http://aptly/trixie/13", "http://aptly/molior.asc"))
        sys.modules.pop("molior.ops.buildenv", None)
    return ret, build, mirror_build, mirror, chroot, queued


def test_success_makes_mirror_ready():
    ret, build, mirror_build, mirror, chroot, queued = run_buildenv(0, 0)
    assert ret is True
    assert build.buildstate == "successful"
    assert mirror_build.buildstate == "successful"
    assert mirror.mirror_state == "ready"
    assert chroot.ready is True
    assert queued == [{"schedule": []}]


def test_build_failure_fails_mirror():
    ret, build, mirror_build, mirror, chroot, queued = run_buildenv(1, 0)
    assert ret is False
    assert build.buildstate == "build_failed"
    assert mirror_build.buildstate == "build_failed"
    assert mirror_build.logdone_called
    assert mirror.mirror_state == "error"
    assert chroot.ready is False


def test_publish_failure_fails_mirror():
    """The push of the build image fails: the chroot build is publish_failed, and the mirror build and the mirror
    must not stay in publishing."""
    ret, build, mirror_build, mirror, chroot, queued = run_buildenv(0, 125)
    assert ret is False
    assert build.buildstate == "publish_failed"
    assert mirror_build.buildstate == "build_failed"
    assert mirror_build.logdone_called
    assert mirror.mirror_state == "error"
    assert chroot.ready is False
    assert queued == []
