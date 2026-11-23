"""
Tests for AptlyApi.republish (lookup of the tmp snapshot by name), AptlyApi.snapshot_exists
and the polling of AptlyApi.wait_task (molior/aptly/api.py).

aiohttp is not installed on the dev host, so it and the molior modules that api.py imports
are replaced by stubs; the real api.py is loaded.
"""
import asyncio
import importlib.util
import sys
import types

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3] / "molior"


class FakeResponse:
    def __init__(self, status, text=""):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """aiohttp.ClientSession stand in: answers GET with the status set in `answers` (by URL)."""
    answers = {}
    urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, auth=None, params=None):
        FakeSession.urls.append(url)
        return FakeResponse(*FakeSession.answers[url])


class AptlyError(Exception):
    pass


@pytest.fixture
def api_module():
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = FakeSession
    aiohttp.BasicAuth = MagicMock()

    pkg_molior = types.ModuleType("molior")
    pkg_molior.__path__ = [str(ROOT)]
    pkg_aptly = types.ModuleType("molior.aptly")
    pkg_aptly.__path__ = [str(ROOT / "aptly")]
    logger_mod = types.ModuleType("molior.logger")
    logger_mod.logger = MagicMock()
    conf_mod = types.ModuleType("molior.molior.configuration")
    conf_mod.Configuration = MagicMock()
    pkg_inner = types.ModuleType("molior.molior")
    pkg_inner.__path__ = []
    errors_mod = types.ModuleType("molior.aptly.errors")
    errors_mod.AptlyError = AptlyError

    stubs = {
        "aiohttp": aiohttp,
        "molior": pkg_molior,
        "molior.aptly": pkg_aptly,
        "molior.logger": logger_mod,
        "molior.molior": pkg_inner,
        "molior.molior.configuration": conf_mod,
        "molior.aptly.errors": errors_mod,
    }
    with patch.dict(sys.modules, stubs):
        for name in ("taskstate", "api"):
            spec = importlib.util.spec_from_file_location(f"molior.aptly.{name}", ROOT / "aptly" / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"molior.aptly.{name}"] = mod
            spec.loader.exec_module(mod)
        FakeSession.answers = {}
        FakeSession.urls = []
        yield sys.modules["molior.aptly.api"]


URL = "http://aptly:3142/api"
SNAP = "trixie_latest_repos_rlx_trixie-stable"
TMP = SNAP + "-tmp"


def make_api(api_module, delete_fails=False, wait_results=None):
    api = api_module.AptlyApi(URL, "gpg@key")
    calls = []
    results = list(wait_results or [])

    async def snapshot_delete(name):
        calls.append(("delete", name))
        if delete_fails:
            raise Exception("delete failed")
        return 1

    async def snapshot_create(repo, name):
        calls.append(("create", repo, name))
        return 2

    async def snapshot_publish_update(name, component, dist, publish_name):
        calls.append(("publish", name, dist, publish_name))
        return 3

    async def snapshot_rename(name, new_name):
        calls.append(("rename", name, new_name))
        return 4

    async def wait_task(task_id):
        calls.append(("wait", task_id))
        return results.pop(0) if results else True

    async def get_all(*args, **kwargs):
        raise AssertionError("the list of all snapshots must not be loaded")

    api.snapshot_delete = snapshot_delete
    api.snapshot_create = snapshot_create
    api.snapshot_publish_update = snapshot_publish_update
    api.snapshot_rename = snapshot_rename
    api.wait_task = wait_task
    api.snapshot_get = get_all
    return api, calls


def run_republish(api):
    return asyncio.run(api.republish("stable", ["amd64"], "trixie-latest-rlx-trixie-stable",
                                     "trixie_latest_repos_rlx_trixie"))


# snapshot_exists

@pytest.mark.parametrize("status,expected", [(200, True), (404, False)])
def test_snapshot_exists(api_module, status, expected):
    FakeSession.answers = {f"{URL}/snapshots/{TMP}": (status, "")}
    api = api_module.AptlyApi(URL, "gpg@key")
    assert asyncio.run(api.snapshot_exists(TMP)) is expected
    assert FakeSession.urls == [f"{URL}/snapshots/{TMP}"]


@pytest.mark.parametrize("status", [401, 500, 502])
def test_snapshot_exists_raises_on_other_errors(api_module, status):
    """A proxy error (502) or an auth error must not be taken for a missing snapshot."""
    FakeSession.answers = {f"{URL}/snapshots/{TMP}": (status, "bad")}
    api = api_module.AptlyApi(URL, "gpg@key")
    with pytest.raises(AptlyError):
        asyncio.run(api.snapshot_exists(TMP))


# republish

def test_republish_without_leftover_tmp_snapshot(api_module):
    FakeSession.answers = {f"{URL}/snapshots/{TMP}": (404, "")}
    api, calls = make_api(api_module)
    assert run_republish(api) is True
    assert FakeSession.urls == [f"{URL}/snapshots/{TMP}"]   # one lookup by name, no list
    assert [c[0] for c in calls if c[0] != "wait"] == ["create", "publish", "delete", "rename"]
    assert ("create", "trixie-latest-rlx-trixie-stable", TMP) in calls
    assert ("delete", SNAP) in calls
    assert ("rename", TMP, SNAP) in calls


def test_republish_deletes_leftover_tmp_snapshot_first(api_module):
    FakeSession.answers = {f"{URL}/snapshots/{TMP}": (200, "{}")}
    api, calls = make_api(api_module)
    assert run_republish(api) is True
    steps = [c[:2] if c[0] in ("delete", "rename") else c[:1] for c in calls if c[0] != "wait"]
    assert steps == [("delete", TMP), ("create",), ("publish",), ("delete", SNAP), ("rename", TMP)]


def test_republish_lookup_error_stops_before_any_change(api_module):
    FakeSession.answers = {f"{URL}/snapshots/{TMP}": (502, "bad gateway")}
    api, calls = make_api(api_module)
    assert run_republish(api) is None   # unchanged behaviour: falsy, the caller fails the publish
    assert calls == []


def test_republish_tmp_delete_fails_then_republishes_non_tmp(api_module):
    """Unchanged recovery path: the leftover tmp snapshot cannot be deleted (task fails)."""
    FakeSession.answers = {f"{URL}/snapshots/{TMP}": (200, "{}")}
    # wait results: tmp delete fails, republish of the non-tmp snapshot ok, second tmp delete ok, rest ok
    api, calls = make_api(api_module, wait_results=[False, True, True])
    assert run_republish(api) is True
    names = [(c[0], c[1]) for c in calls if c[0] in ("delete", "publish")]
    assert names[:3] == [("delete", TMP), ("publish", SNAP), ("delete", TMP)]


# wait_task polling

def run_wait(api_module, states):
    api = api_module.AptlyApi(URL, "gpg@key")
    sleeps = []
    polls = list(states)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def get_task_state(task_id):
        return {"State": polls.pop(0)}

    async def delete_task(task_id):
        return {}

    async def get(path, params=None):
        return "output"

    api.get_task_state = get_task_state
    api.delete_task = delete_task
    api.GET = get
    with patch.object(api_module.asyncio, "sleep", fake_sleep):
        result = asyncio.run(api.wait_task(5))
    return result, sleeps


def test_wait_task_first_poll_is_early(api_module):
    ok = api_module.TaskState.SUCCESSFUL.value
    result, sleeps = run_wait(api_module, [ok])
    assert result is True
    assert sleeps == [0.1]


def test_wait_task_backs_off_to_two_seconds(api_module):
    running = api_module.TaskState.RUNNING.value
    ok = api_module.TaskState.SUCCESSFUL.value
    result, sleeps = run_wait(api_module, [running] * 7 + [ok])
    assert result is True
    assert sleeps == [0.1, 0.2, 0.4, 0.8, 1.6, 2, 2, 2]


def test_wait_task_failed_task(api_module):
    failed = api_module.TaskState.FAILED.value
    result, sleeps = run_wait(api_module, [failed])
    assert result is False
    assert sleeps == [0.1]
