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
        self.commits = 0

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, model):
        return Query(self.build if model is worker_aptly.Build else self.mirror)

    def commit(self):
        self.commits += 1


class FakeAptly:
    """aptly with the tasks of RESTART_TASKS: the downloads 1 and 3 run for `polls` polls, then succeed."""

    def __init__(self, polls=2, snapshots=(), publish_error=None):
        self.session = None
        self.commits_at_first_poll = None
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
        if self.commits_at_first_poll is None:
            self.commits_at_first_poll = self.session.commits
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
    aptly.session = FakeSession(build, mirror)
    with patch.object(worker_aptly, "Session", aptly.session), \
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


@pytest.mark.parametrize("state,task_ids", [("updating", [1, 2, 3, 4]), ("publishing", [20])])
def test_finalize_no_transaction_open_while_waiting(state, task_ids):
    """the session reads build and mirror, then commits before polling aptly (postgres may restart meanwhile)"""
    aptly = FakeAptly(polls=1)
    if state == "publishing":
        aptly.tasks.append({"ID": 20, "State": 1, "Name": "Publish snapshot: " + ", ".join(NAMES)})
    run_finalize(aptly, state, task_ids)
    assert aptly.commits_at_first_poll == 1


class ListQuery:
    """query(...).join/filter(...).all()/first(): returns the next result of the list given for the model"""

    def __init__(self, results):
        self.results = results

    def join(self, *args):
        return self

    def filter(self, *args):
        return self

    def all(self):
        return self.results.pop(0)

    def first(self):
        found = self.results.pop(0)
        return found[0] if found else None


class StartupSession(FakeSession):
    def __init__(self, results):
        super().__init__(None, None)
        self.results = results

    def query(self, model):
        return ListQuery(self.results["build" if model is worker_aptly.Build else "mirror"])


def make_mirror_build(build_id, buildstate):
    build = MagicMock()
    build.id = build_id
    build.buildstate = buildstate
    for method in ("log", "logdone", "set_building", "set_publishing", "set_failed", "set_publish_failed"):
        setattr(build, method, AsyncMock())
    return build


def run_startup(tasks, mirrors, builds):
    """mirrors: [(mirror, its build or None if it has no task on aptly: then its build is not looked up)],
    builds: the mirror builds in building/publishing"""
    results = {"mirror": [[m for m, _ in mirrors]], "build": [[b] for _, b in mirrors if b] + [builds]}
    aptly = MagicMock()
    aptly.get_tasks = AsyncMock(side_effect=tasks)
    loop = MagicMock()
    with patch.object(worker_aptly, "Session", StartupSession(results)), \
            patch.object(worker_aptly, "get_aptly_connection", return_value=aptly), \
            patch.object(worker_aptly, "finalize_mirror", MagicMock()) as finalize, \
            patch.object(worker_aptly.asyncio, "get_event_loop", return_value=loop), \
            patch.object(worker_aptly.asyncio, "sleep", AsyncMock()):
        asyncio.run(worker_aptly.startup_mirror())
    return finalize, loop


def make_mirror(name, version, state):
    _, mirror = make_build_and_mirror(state)
    mirror.project.name = name
    mirror.project.is_basemirror = True
    mirror.name = version
    mirror.id = 30879
    mirror.mirror_components = ",".join(COMPONENTS)
    mirror.mirror_architectures = "{amd64}"
    mirror.mirror_with_sources = True
    return mirror


def test_startup_continues_running_mirror_and_fails_orphans():
    trixie = make_mirror("trixie", "13.8", "updating")
    trixie_build = make_mirror_build(100, "building")
    old = make_mirror("jessie", "8.11", "error")
    orphan = make_mirror_build(17, "publishing")

    # aptly answers on the second attempt
    finalize, loop = run_startup([Exception("aptly not up"), RESTART_TASKS],
                                 [(trixie, trixie_build), (old, None)], [trixie_build, orphan])

    assert finalize.call_args.args[0] == 100
    assert finalize.call_args.args[-1] == [1, 2, 3, 4]
    assert loop.create_task.call_count == 1
    trixie_build.set_building.assert_awaited_once()
    trixie_build.set_failed.assert_not_called()
    assert trixie.mirror_state == "updating"
    old.set_mirror_state.assert_not_called()  # error without tasks stays error, no log line
    orphan.set_publish_failed.assert_awaited_once()
    orphan.logdone.assert_awaited_once()


def test_startup_without_tasks_fails_the_mirror_build():
    trixie = make_mirror("trixie", "13.8", "updating")
    build = make_mirror_build(100, "building")
    finalize, loop = run_startup([[]], [(trixie, None)], [build])

    finalize.assert_not_called()
    assert trixie.mirror_state == "error"
    build.set_failed.assert_awaited_once()


# missing aptly mirrors (e.g. trixie-13.8-main was deleted after its update failed, the other components are kept):
# update and init of the mirror create the missing ones

class RecreateAptly:
    """aptly with the mirrors in `existing`; records creates and updates."""

    def __init__(self, existing, create_error=None):
        self.existing = set(existing)
        self.create_error = create_error
        self.created = []
        self.updated = []

    async def mirror_exists(self, name):
        return name in self.existing

    async def mirror_create(self, mirror, version, base_mirror, base_mirror_version, url, dist, components,
                            architectures, mirror_filter, skip_existing=False, **kwargs):
        if self.create_error:
            raise Exception(self.create_error)
        created = []
        for name in mirror_aptly_names(base_mirror, base_mirror_version, mirror, version, components):
            if skip_existing and name in self.existing:
                continue
            if name in self.existing:
                raise Exception(f"mirror with name {name} already exists")
            self.existing.add(name)
            created.append(name)
        self.created += created
        return created

    async def snapshot_exists(self, name):
        return False

    async def mirror_update(self, base_mirror, base_mirror_version, mirror, version, components):
        names = mirror_aptly_names(base_mirror, base_mirror_version, mirror, version, components)
        missing = [name for name in names if name not in self.existing]
        if missing:
            raise worker_aptly.AptlyError(f"mirror {missing[0]} not found")
        self.updated = names
        return [1, 2, 3, 4]

    async def gpg_add_key(self, **kwargs):
        return True, "key added"


def make_trixie_mirror(mirror_state):
    build, mirror = make_build_and_mirror(mirror_state)
    build.id = 100
    build.set_building = AsyncMock()
    mirror.external_repo = False
    mirror.basemirror = None
    mirror.project.name = "trixie"
    mirror.name = "13.8"
    mirror.mirror_url = "https://deb.debian.org/debian/"
    mirror.mirror_components = ",".join(COMPONENTS)
    mirror.mirror_architectures = "{amd64,i386,arm64,armhf}"
    mirror.mirror_with_sources = True
    mirror.mirror_with_installer = False
    mirror.mirror_filter = ""
    mirror.mirror_filter_with_deps = False
    return build, mirror


def run_worker(method, aptly, build, mirror, mirrorkey=None):
    session = FakeSession(build, mirror)
    orig_query = session.query

    def query(model):
        if model is worker_aptly.MirrorKey:
            return Query(mirrorkey)
        return orig_query(model)
    session.query = query
    enqueued = AsyncMock()
    worker = worker_aptly.AptlyWorker.__new__(worker_aptly.AptlyWorker)
    with patch.object(worker_aptly, "Session", session), \
            patch.object(worker_aptly, "get_aptly_connection", return_value=aptly), \
            patch.object(worker_aptly, "enqueue_aptly", enqueued), \
            patch.object(worker_aptly, "finalize_mirror", AsyncMock()):
        asyncio.run(getattr(worker, method)([1]))
    return enqueued


def build_log(build):
    return "".join(c.args[0] for c in build.log.call_args_list)


def test_update_creates_missing_mirror_first():
    aptly = RecreateAptly(NAMES[1:])
    build, mirror = make_trixie_mirror("error")
    run_worker("_update_mirror", aptly, build, mirror)
    assert aptly.created == ["trixie-13.8-main"]
    assert aptly.updated == NAMES
    assert mirror.mirror_state == "updating"
    build.set_failed.assert_not_called()
    assert "I: mirror missing on aptly, created again: trixie-13.8-main\n" in build_log(build)


def test_update_with_all_mirrors_creates_nothing():
    aptly = RecreateAptly(NAMES)
    build, mirror = make_trixie_mirror("error")
    run_worker("_update_mirror", aptly, build, mirror)
    assert aptly.created == []
    assert aptly.updated == NAMES
    assert "created again" not in build_log(build)


def test_update_fails_the_build_if_the_create_fails():
    aptly = RecreateAptly(NAMES[1:], create_error="unable to fetch Release")
    build, mirror = make_trixie_mirror("error")
    run_worker("_update_mirror", aptly, build, mirror)
    assert aptly.updated == []
    assert mirror.mirror_state == "error"
    build.set_failed.assert_called_once()
    build.logdone.assert_called_once()
    assert "unable to fetch Release" in build_log(build)


def test_init_skips_existing_mirrors():
    """A retry of an init that created only some of the components (before: 'already exists', init_error)."""
    aptly = RecreateAptly(NAMES[1:])
    build, mirror = make_trixie_mirror("init_error")
    mirrorkey = MagicMock(keyurl="", keyids="{}", keyserver="")
    enqueued = run_worker("_init_mirror", aptly, build, mirror, mirrorkey)
    assert aptly.created == ["trixie-13.8-main"]
    assert mirror.mirror_state == "created"
    build.set_failed.assert_not_called()
    enqueued.assert_called_once_with({"update_mirror": [1]})
    assert "I: mirror exists already on aptly: " + ", ".join(NAMES[1:]) + "\n" in build_log(build)
