"""
Tests for continuing a mirror after a molior restart (molior/molior/worker_aptly.py):
mirror_resume_state, mirror_pending_tasks and finalize_mirror.

Case: restart while trixie/13.8 is downloading. aptly has the update tasks of 4 components, 2 of them
done, 2 still running, and queued snapshot tasks (state 0). molior must wait for all of them before the
snapshots and the publish, and must not delete the mirror.
"""
import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from molior.molior import worker_aptly
from molior.molior.worker_aptly import finalize_mirror, mirror_aptly_names, mirror_pending_tasks, mirror_resume_state

COMPONENTS = ["main", "contrib", "non-free", "non-free-firmware"]
NAMES = mirror_aptly_names("", "", "trixie", "13.8", COMPONENTS)

# aptly task list after a restart during the download
RESTART_TASKS = [
    {"ID": 1, "State": 1, "Name": "Update mirror trixie-13.8-main"},
    {"ID": 2, "State": 2, "Name": "Update mirror trixie-13.8-contrib"},
    {"ID": 3, "State": 1, "Name": "Update mirror trixie-13.8-non-free"},
    {"ID": 4, "State": 2, "Name": "Update mirror trixie-13.8-non-free-firmware"},
    {"ID": 5, "State": 0, "Name": "Create snapshot of mirror trixie-13.8-main"},
    {"ID": 6, "State": 2, "Name": "Create snapshot of mirror trixie-13.8-contrib"},
    {"ID": 7, "State": 0, "Name": "Create snapshot of mirror trixie-13.8-non-free"},
    {"ID": 8, "State": 2, "Name": "Create snapshot of mirror trixie-13.8-non-free-firmware"},
    {"ID": 9, "State": 0, "Name": "Delete mirror trixie-13.8-main"},
]


def test_aptly_names():
    assert NAMES == ["trixie-13.8-main", "trixie-13.8-contrib", "trixie-13.8-non-free", "trixie-13.8-non-free-firmware"]
    assert mirror_aptly_names("bookworm", "12.5", "docker", "1", ["stable"]) == ["bookworm-12.5-docker-1-stable"]
    assert mirror_aptly_names("bookworm", "12.5", "flat", "1", [""]) == ["bookworm-12.5-flat-1"]


def test_resume_follows_all_update_tasks():
    assert mirror_resume_state(RESTART_TASKS, NAMES) == ("updating", [1, 2, 3, 4])


def test_resume_ignores_other_mirrors():
    tasks = [{"ID": 1, "State": 1, "Name": "Update mirror trixie-13.8-1-main"},
             {"ID": 2, "State": 1, "Name": "Update mirror bookworm-12.5-trixie-13.8-main"}]
    assert mirror_resume_state(tasks, NAMES) == (None, [])
    assert mirror_resume_state([], NAMES) == (None, [])


def test_resume_takes_latest_update_run():
    tasks = [{"ID": 1, "State": 3, "Name": "Update mirror trixie-13.8-main"},
             {"ID": 2, "State": 3, "Name": "Update mirror trixie-13.8-contrib"},
             {"ID": 10, "State": 1, "Name": "Update mirror trixie-13.8-main"},
             {"ID": 11, "State": 0, "Name": "Update mirror trixie-13.8-contrib"}]
    assert mirror_resume_state(tasks, NAMES[:2]) == ("updating", [10, 11])


def test_resume_publishing():
    publish = "Publish snapshot: " + ", ".join(NAMES)
    tasks = RESTART_TASKS + [{"ID": 12, "State": 1, "Name": publish}]
    assert mirror_resume_state(tasks, NAMES) == ("publishing", [12])
    # an old publish task does not hide a newer update run
    tasks = [{"ID": 1, "State": 2, "Name": publish}, {"ID": 2, "State": 1, "Name": "Update mirror trixie-13.8-main"}]
    assert mirror_resume_state(tasks, NAMES) == ("updating", [2])


def test_pending_tasks():
    assert mirror_pending_tasks(RESTART_TASKS, NAMES) == [1, 3, 5, 7, 9]
    assert mirror_pending_tasks(RESTART_TASKS, ["trixie-13.8-contrib"]) == []
    assert mirror_pending_tasks([{"ID": 1, "State": 0, "Name": "Update mirror trixie-13.8-main-x"}], NAMES) == []


class Query:
    def __init__(self, result):
        self.result = result

    def join(self, *args):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return self.result


class FakeSession:
    def __init__(self, build, mirror):
        self.build = build
        self.mirror = mirror

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, model):
        return Query(self.build if model is worker_aptly.Build else self.mirror)

    def commit(self):
        pass


class FakeAptly:
    """aptly with the tasks of RESTART_TASKS: the downloads 1 and 3 run for `polls` polls, then succeed."""

    def __init__(self, polls=2, snapshots=(), publish_error=None):
        self.polls = {1: polls, 3: polls}
        self.snapshots = set(snapshots)
        self.publish_error = publish_error
        self.tasks = [dict(t) for t in RESTART_TASKS]
        self.snapshot_calls = []
        self.mirror_delete = AsyncMock()
        self.publish_progress = []

    def task(self, task_id):
        return next(t for t in self.tasks if t["ID"] == task_id)

    async def mirror_get_progress(self, task_id):
        if task_id in self.polls:
            self.polls[task_id] -= 1
            if self.polls[task_id] <= 0:
                self.task(task_id)["State"] = 2
        if task_id == 20:
            return {"State": 2, "TotalNumberOfPackages": 1, "RemainingNumberOfPackages": 0}
        done = self.task(task_id)["State"] == 2
        return {"State": self.task(task_id)["State"], "TotalNumberOfPackages": 10,
                "RemainingNumberOfPackages": 0 if done else 5,
                "TotalDownloadSize": 100, "RemainingDownloadSize": 0 if done else 50}

    async def get_tasks(self):
        # the queued snapshots 5, 7 and the delete 9 run once the downloads are done
        if all(self.task(i)["State"] == 2 for i in (1, 3)):
            for t in self.tasks:
                if t["ID"] in (5, 7):
                    t["State"] = 2
                    self.snapshots.add(t["Name"].split()[-1])
                if t["ID"] == 9:
                    t["State"] = 3  # aptly refuses: the mirror has snapshots
        return self.tasks

    async def snapshot_exists(self, name):
        return name in self.snapshots

    async def mirror_snapshot(self, base_mirror, base_mirror_version, mirror, version, components):
        self.snapshot_calls.append(list(components))
        ids = []
        for i, name in enumerate(mirror_aptly_names(base_mirror, base_mirror_version, mirror, version, components)):
            self.snapshots.add(name)
            self.tasks.append({"ID": 30 + i, "State": 0, "Name": f"Create snapshot of mirror {name}"})
            ids.append(30 + i)
        return ids

    async def get_task_state(self, task_id):
        task = self.task(task_id)
        state = task["State"]
        task["State"] = 2  # queued on the first poll, done on the next
        return {"State": state}

    async def mirror_publish(self, *args):
        if self.publish_error:
            raise Exception(self.publish_error)
        self.tasks.append({"ID": 20, "State": 1, "Name": "Publish snapshot: " + ", ".join(NAMES)})
        return 20


def make_build_and_mirror(mirror_state):
    build = MagicMock()
    for method in ("log", "logtitle", "logdone", "set_publishing", "set_publish_failed", "set_failed", "set_successful"):
        setattr(build, method, AsyncMock())
    mirror = MagicMock()
    mirror.mirror_state = mirror_state
    mirror.project.is_basemirror = False
    mirror.mirror_distribution = "trixie"
    mirror.mirror_slash_workaround = False

    async def set_mirror_state(state):
        mirror.mirror_state = state
    mirror.set_mirror_state = AsyncMock(side_effect=set_mirror_state)
    return build, mirror


def run_finalize(aptly, mirror_state, task_ids):
    build, mirror = make_build_and_mirror(mirror_state)
    with patch.object(worker_aptly, "Session", FakeSession(build, mirror)), \
            patch.object(worker_aptly, "get_aptly_connection", return_value=aptly), \
            patch.object(worker_aptly, "notify", AsyncMock()), \
            patch.object(worker_aptly.asyncio, "sleep", AsyncMock()):
        asyncio.run(finalize_mirror(1, "", "", "trixie", "13.8", COMPONENTS, ["amd64"], task_ids))
    return build, mirror


def test_finalize_after_restart_waits_for_all_downloads_and_queued_snapshots():
    # snapshots of the 2 finished components exist already (tasks 6 and 8)
    aptly = FakeAptly(polls=3, snapshots={"trixie-13.8-contrib", "trixie-13.8-non-free-firmware"})
    build, mirror = run_finalize(aptly, "updating", [1, 2, 3, 4])

    assert aptly.task(1)["State"] == 2 and aptly.task(3)["State"] == 2
    # the queued snapshots 5 and 7 made the rest: nothing to create, nothing deleted
    assert aptly.snapshot_calls == []
    aptly.mirror_delete.assert_not_called()
    build.set_publish_failed.assert_not_called()
    build.set_successful.assert_awaited_once()
    assert mirror.mirror_state == "ready"


def test_finalize_creates_only_missing_snapshots():
    aptly = FakeAptly(polls=1, snapshots={"trixie-13.8-contrib"})
    aptly.tasks = [t for t in aptly.tasks if t["ID"] not in (5, 7, 9)]
    build, mirror = run_finalize(aptly, "updating", [1, 2, 3, 4])

    assert aptly.snapshot_calls == [["main", "non-free", "non-free-firmware"]]
    build.set_successful.assert_awaited_once()


def test_finalize_queued_update_is_not_taken_as_done():
    aptly = FakeAptly(polls=2)
    aptly.task(1)["State"] = 0
    aptly.task(3)["State"] = 0
    build, mirror = run_finalize(aptly, "updating", [1, 2, 3, 4])

    assert aptly.polls == {1: 0, 3: 0}  # polled until done
    build.set_successful.assert_awaited_once()


def test_finalize_publish_error_keeps_the_mirror():
    aptly = FakeAptly(polls=1, publish_error="unable to publish: snapshot with name trixie-13.8-main not found")
    build, mirror = run_finalize(aptly, "updating", [1, 2, 3, 4])

    aptly.mirror_delete.assert_not_called()
    build.set_publish_failed.assert_awaited_once()
    build.logdone.assert_awaited_once()
    assert mirror.mirror_state == "error"


@pytest.mark.parametrize("state", [1, 2])
def test_finalize_continues_publishing(state):
    aptly = FakeAptly()
    aptly.tasks.append({"ID": 20, "State": state, "Name": "Publish snapshot: " + ", ".join(NAMES)})
    build, mirror = run_finalize(aptly, "publishing", [20])

    build.set_successful.assert_awaited_once()
    assert mirror.mirror_state == "ready"
