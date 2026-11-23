"""
Tests for the error handling of publishing (molior/ops/aptly.py and
DebianRepository.remove_packages in molior/molior/debianrepository.py).

An error of an earlier step (upload, removal of obsolete packages) must not be
hidden by the result of a later step (republish).

The heavy third party imports are replaced by stubs, the real source files are loaded.
"""
import asyncio
import importlib
import importlib.util
import sys
import types

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3] / "molior"


class FakeLaunchy:
    def __init__(self, *args, **kwargs):
        pass

    async def launch(self):
        pass

    async def wait(self):
        return 0


class FakeRepo:
    """Stands in for DebianRepository, records the calls."""
    results = {}
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def add_packages(self, files, ci_build=False):
        return self._step("add_packages")

    async def remove_packages(self, packages, ci_build=False):
        return self._step("remove_packages")

    async def republish(self, ci_build=False):
        return self._step("republish")

    def _step(self, name):
        FakeRepo.calls.append(name)
        result = FakeRepo.results.get(name, True)
        if isinstance(result, Exception):
            raise result
        return result


class FakeSession:
    def __init__(self, projectversions):
        self.projectversions = projectversions

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return self.projectversions.pop(0) if self.projectversions else None


def fake_projectversion():
    return SimpleNamespace(
        fullname="base/1.0/proj/1", basemirror=SimpleNamespace(project=SimpleNamespace(name="base"), name="1.0"),
        project=SimpleNamespace(name="proj"), name="1", mirror_architectures="{amd64}", publish_s3=False)


@pytest.fixture
def ops(tmp_path):
    """The module molior.ops.aptly with stubbed dependencies."""
    configuration = SimpleNamespace(working_dir=str(tmp_path), debsign_gpg_email="key@example.com")
    buildlog = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
    stubs = {
        "launchy": MagicMock(Launchy=FakeLaunchy),
        "aiofile": MagicMock(),
        "molior.logger": MagicMock(),
        "molior.tools": MagicMock(strip_epoch_version=lambda v: v.split(":")[-1], db2array=lambda a: a),
        "molior.molior.debianrepository": MagicMock(DebianRepository=FakeRepo),
        "molior.molior.configuration": MagicMock(Configuration=lambda: configuration),
        "molior.molior.queues": MagicMock(buildlog=buildlog, buildlogtitle=MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))),
        "molior.model.database": MagicMock(),
        "molior.model.build": MagicMock(),
        "molior.model.buildtask": MagicMock(),
        "molior.model.projectversion": MagicMock(),
        "molior.model.debianpackage": MagicMock(),
    }
    package = types.ModuleType("molior.ops")
    package.__path__ = [str(ROOT / "ops")]
    stubs["molior.ops"] = package
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("molior.ops.aptly", ROOT / "ops" / "aptly.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["molior.ops.aptly"] = module
        spec.loader.exec_module(module)
        module.add_files = lambda *args: None
        module.buildlog_mock = buildlog
        FakeRepo.results = {}
        FakeRepo.calls = []
        yield module


def log_lines(module):
    return [call.args[1] for call in module.buildlog_mock.call_args_list]


def set_projectversions(module, count):
    module.Session = lambda: FakeSession([fake_projectversion() for _ in range(count)])


# ---------------------------------------------------------------- deb: publish_packages

@pytest.fixture
def deb_files(ops, tmp_path):
    out_path = tmp_path / "buildout" / "7"
    out_path.mkdir(parents=True)
    names = ["foo_1.0_amd64.deb", "foo_1.0_amd64.changes"]
    for name in names:
        (out_path / name).write_text("x")

    async def get_files(path, sourcename, version, architecture="source"):
        return ["foo_1.0_amd64.deb"]

    ops.debchanges_get_files = get_files
    return out_path


def publish_deb(ops, out_path, remove_packages=()):
    return asyncio.run(ops.publish_packages(
        7, "deb", "foo", "1.0", "amd64", False, "base", "1.0", "proj", "1", ["amd64"], out_path,
        remove_packages=list(remove_packages)))


def test_deb_all_steps_ok(ops, deb_files):
    assert publish_deb(ops, deb_files, [("foo", "0.9", "amd64")]) is True
    assert FakeRepo.calls == ["add_packages", "remove_packages", "republish"]
    assert not list(deb_files.glob("*.deb")), "published files are deleted"


def test_deb_add_fails_stops_and_keeps_files(ops, deb_files):
    """The old packages must not be removed when the new one was not added."""
    FakeRepo.results = {"add_packages": False}
    assert publish_deb(ops, deb_files, [("foo", "0.9", "amd64")]) is False
    assert FakeRepo.calls == ["add_packages"]
    assert (deb_files / "foo_1.0_amd64.deb").exists()
    assert "E: error uploading files to repository\n" in log_lines(ops)


def test_deb_add_raises(ops, deb_files):
    FakeRepo.results = {"add_packages": RuntimeError("aptly down")}
    assert publish_deb(ops, deb_files) is False
    assert FakeRepo.calls == ["add_packages"]


def test_deb_remove_fails(ops, deb_files):
    FakeRepo.results = {"remove_packages": False}
    assert publish_deb(ops, deb_files, [("foo", "0.9", "amd64")]) is False
    assert FakeRepo.calls == ["add_packages", "remove_packages"]
    assert "E: error removing obsolete packages from repository\n" in log_lines(ops)


def test_deb_republish_fails(ops, deb_files):
    FakeRepo.results = {"republish": False}
    assert publish_deb(ops, deb_files) is False
    assert (deb_files / "foo_1.0_amd64.deb").exists()
    assert "E: error republishing repository\n" in log_lines(ops)


def test_deb_republish_returns_none(ops, deb_files):
    """aptly.republish() returns None when the snapshot list cannot be loaded."""
    FakeRepo.results = {"republish": None}
    assert publish_deb(ops, deb_files) is False


# ---------------------------------------------------------------- source: DebSrcPublish

@pytest.fixture
def src_dir(ops, tmp_path):
    path = tmp_path / "buildout" / "5"  # no repo_id, no .changes: all files are published
    path.mkdir(parents=True)
    (path / "foo_1.0.tar.gz").write_text("x")
    return path


def publish_src(ops, projectversions):
    set_projectversions(ops, len(projectversions))
    return asyncio.run(ops.DebSrcPublish(5, None, "foo", "1.0", projectversions, False))


def test_src_ok(ops, src_dir):
    assert publish_src(ops, [1]) is True
    assert FakeRepo.calls == ["add_packages", "republish"]
    assert not (src_dir / "foo_1.0.tar.gz").exists()


def test_src_add_fails_does_not_republish(ops, src_dir):
    FakeRepo.results = {"add_packages": False}
    assert publish_src(ops, [1]) is False
    assert FakeRepo.calls == ["add_packages"]
    assert (src_dir / "foo_1.0.tar.gz").exists()
    assert "E: error adding files\n" in log_lines(ops)


def test_src_republish_fails(ops, src_dir):
    FakeRepo.results = {"republish": False}
    assert publish_src(ops, [1]) is False
    assert (src_dir / "foo_1.0.tar.gz").exists()


def test_src_error_in_first_projectversion_is_not_hidden(ops, src_dir):
    """Only the last projectversion used to count."""
    results = iter([False, True, True, True])  # add (pv 1) fails, the other steps work

    def step(name):
        FakeRepo.calls.append(name)
        return next(results)

    with patch.object(FakeRepo, "_step", staticmethod(step)):
        assert publish_src(ops, [1, 2]) is False
    assert FakeRepo.calls == ["add_packages", "add_packages", "republish"]
    assert (src_dir / "foo_1.0.tar.gz").exists()


def test_src_all_projectversions_ok(ops, src_dir):
    assert publish_src(ops, [1, 2]) is True
    assert FakeRepo.calls == ["add_packages", "republish", "add_packages", "republish"]


def test_src_unknown_projectversion_only_fails(ops, src_dir):
    """No projectversion found: nothing published, still an error (as before)."""
    set_projectversions(ops, 0)
    assert asyncio.run(ops.DebSrcPublish(5, None, "foo", "1.0", [1], False)) is False
    assert FakeRepo.calls == []


# ---------------------------------------------------------------- DebianRepository.remove_packages

@pytest.fixture
def repo():
    aptly = MagicMock()
    stubs = {
        "molior.logger": MagicMock(),
        "molior.aptly": MagicMock(get_aptly_connection=lambda: aptly, get_snapshot_name=MagicMock()),
        "molior.molior.configuration": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        sys.modules.pop("molior.molior.debianrepository", None)
        module = importlib.import_module("molior.molior.debianrepository")
        repo = module.DebianRepository("base", "1.0", "proj", "1", ["amd64"])
        repo.aptly = aptly
        yield repo
        sys.modules.pop("molior.molior.debianrepository", None)


def async_return(value):
    async def coro(*args, **kwargs):
        return value
    return coro


def test_remove_packages_empty_list_is_ok(repo):
    repo.aptly.repo_packages_delete = async_return(1)
    assert asyncio.run(repo.remove_packages([])) is True
    repo.aptly.wait_task = MagicMock()
    repo.aptly.wait_task.assert_not_called()


def test_remove_packages_waits_for_the_task(repo):
    repo.aptly.repo_packages_get = async_return(["Pamd64 foo 0.9 abc"])
    repo.aptly.repo_packages_delete = async_return(42)
    waited = []

    async def wait_task(task_id):
        waited.append(task_id)
        return True

    repo.aptly.wait_task = wait_task
    assert asyncio.run(repo.remove_packages([("foo", "0.9", "amd64")])) is True
    assert waited == [42]


def test_remove_packages_task_fails(repo):
    repo.aptly.repo_packages_get = async_return(["Pamd64 foo 0.9 abc"])
    repo.aptly.repo_packages_delete = async_return(42)
    repo.aptly.wait_task = async_return(False)
    assert asyncio.run(repo.remove_packages([("foo", "0.9", "amd64")])) is False


def test_remove_packages_not_in_repository(repo):
    """Nothing found in aptly: nothing to delete, no task to wait for."""
    repo.aptly.repo_packages_get = async_return([])
    delete = MagicMock()
    repo.aptly.repo_packages_delete = delete
    assert asyncio.run(repo.remove_packages([("foo", "0.9", "amd64")])) is True
    delete.assert_not_called()
