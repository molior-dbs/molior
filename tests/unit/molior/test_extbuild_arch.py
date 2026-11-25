"""
Tests for the architecture check of the external build upload (POST /api2/project/{p}/{v}/extbuild,
_finalize_extbuild in molior/fastapi/routers/v2/projectversion.py).

Files for an architecture that is not in the projectversion are skipped with "E: invalid architecture" in the build
log; "all" is built as amd64; without architectures in the projectversion nothing is checked.
"""
import asyncio

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# fastapi is in the molior image (molior:dev), not in molior-base:dev
pytest.importorskip("fastapi")
from molior.fastapi.routers.v2 import projectversion as pv_router  # noqa: E402

BUILD_ID, SRCBUILD_ID, PV_ID = 100, 101, 7


class Col:
    """A column of FakeBuild: a comparison gives (name, value), the filters of FakeQuery look at them."""
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return (self.name, value)

    def is_(self, value):
        return (self.name, value)

    __hash__ = object.__hash__


class FakeBuildMeta(type):
    def __getattr__(cls, name):
        return Col(name)


class FakeBuild(metaclass=FakeBuildMeta):
    created = []

    def __init__(self, id=None, **kw):
        self.id = id or 200 + len(FakeBuild.created)
        self.__dict__.update(kw)
        self.logs = []
        if id is None:
            FakeBuild.created.append(self)

    async def build_added(self):
        pass

    async def log(self, msg):
        self.logs.append(msg)

    async def logtitle(self, *args, **kw):
        pass

    async def set_failed(self):
        self.buildstate = "build_failed"

    async def set_building(self):
        self.buildstate = "building"

    async def set_needs_publish(self):
        self.buildstate = "needs_publish"

    async def set_nothing_done(self):
        self.buildstate = "nothing_done"


class FakeQuery:
    def __init__(self, session):
        self.session = session
        self.conds = {}

    def filter(self, *conds):
        self.conds.update(c for c in conds if isinstance(c, tuple))
        return self

    def first(self):
        if "id" in self.conds:
            return self.session.builds[self.conds["id"]]
        if "architecture" in self.conds:   # get_debbuild: the deb build made for an earlier file
            return next((b for b in FakeBuild.created
                         if b.architecture == self.conds["architecture"] and b.version == self.conds["version"]), None)
        return None   # the check for an existing build

    def all(self):
        return [b for b in FakeBuild.created if b.parent_id == self.conds.get("parent_id")]


class FakeSession:
    def __init__(self, builds):
        self.builds = builds

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, model):
        return FakeQuery(self)

    def add(self, obj):
        pass

    def commit(self):
        pass


def run(tmp_path, filenames, architectures):
    FakeBuild.created = []
    builds = {BUILD_ID: FakeBuild(BUILD_ID), SRCBUILD_ID: FakeBuild(SRCBUILD_ID)}
    files = []
    for name in filenames:
        f = tmp_path / ("upload-" + name)
        f.write_text(name)
        files.append((name, f))
    logs = []

    async def buildlog(build_id, msg):
        logs.append(msg)

    enqueue_aptly = AsyncMock()
    with patch.object(pv_router, "Build", FakeBuild), \
            patch.object(pv_router, "_bg_session", lambda: FakeSession(builds)), \
            patch.object(pv_router, "Configuration", lambda: SimpleNamespace(working_dir=str(tmp_path))), \
            patch.object(pv_router, "buildlog", buildlog), \
            patch.object(pv_router, "buildlogtitle", AsyncMock()), \
            patch.object(pv_router, "buildlogdone", AsyncMock()), \
            patch.object(pv_router, "enqueue_aptly", enqueue_aptly):
        ok = asyncio.run(pv_router._finalize_extbuild(BUILD_ID, PV_ID, SRCBUILD_ID, files, architectures))
    return ok, logs, files, enqueue_aptly


UPLOAD = ["hello_1.0_amd64.deb", "hello_1.0_amd64.changes", "hello_1.0_amd64.buildinfo"]


@pytest.mark.parametrize("arch, architectures, ok", [
    ("amd64", ["amd64", "arm64"], True),
    ("arm64", ["amd64", "arm64"], True),
    ("all", ["arm64"], True),
    ("armhf", ["amd64", "arm64"], False),
    ("armhf", [], True),
    ("amd6", ["amd64"], False),       # no substring match
])
def test_upload_arch_ok(arch, architectures, ok):
    assert pv_router._upload_arch_ok(arch, architectures) is ok


def test_upload_for_an_architecture_of_the_projectversion(tmp_path):
    ok, logs, files, enqueue_aptly = run(tmp_path, UPLOAD, ["amd64", "arm64"])
    assert ok is True
    assert [b.architecture for b in FakeBuild.created] == ["amd64"]
    assert not [line for line in logs if "invalid architecture" in line]
    debbuild = FakeBuild.created[0]
    for name in UPLOAD:
        assert (tmp_path / "buildout" / str(debbuild.id) / name).exists()
    enqueue_aptly.assert_any_call({"publish": [debbuild.id]})


def test_deb_of_another_architecture_is_skipped(tmp_path):
    ok, logs, files, enqueue_aptly = run(tmp_path, UPLOAD + ["hello_1.0_armhf.deb"], ["amd64", "arm64"])
    assert ok is True
    assert [b.architecture for b in FakeBuild.created] == ["amd64"]
    assert "E: invalid architecture: 'armhf'\n" in logs
    assert not files[-1][1].exists()                      # the temp file of the skipped deb is removed
    assert not list((tmp_path / "buildout").glob("*/hello_1.0_armhf.deb"))


def test_upload_only_for_another_architecture_fails(tmp_path):
    names = ["hello_1.0_armhf.deb", "hello_1.0_armhf.changes", "hello_1.0_armhf.buildinfo"]
    ok, logs, files, enqueue_aptly = run(tmp_path, names, ["amd64", "arm64"])
    assert ok is False
    assert FakeBuild.created == []
    assert logs.count("E: invalid architecture: 'armhf'\n") == 3
    assert "E: Missing *.changes file\n" in logs
    enqueue_aptly.assert_not_called()


def test_all_is_built_as_amd64(tmp_path):
    names = ["hello_1.0_all.deb", "hello_1.0_amd64.changes", "hello_1.0_amd64.buildinfo"]
    ok, logs, files, enqueue_aptly = run(tmp_path, names, ["arm64", "amd64"])
    assert ok is True
    assert [b.architecture for b in FakeBuild.created] == ["amd64"]


def test_without_architectures_nothing_is_checked(tmp_path):
    names = ["hello_1.0_armhf.deb", "hello_1.0_armhf.changes", "hello_1.0_armhf.buildinfo"]
    ok, logs, files, enqueue_aptly = run(tmp_path, names, [])
    assert ok is True
    assert [b.architecture for b in FakeBuild.created] == ["armhf"]
