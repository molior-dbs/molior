"""
Provides test molior configuration class.
"""
import asyncio
from datetime import datetime

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from molior.molior.debianrepository import DebianRepository
from molior.aptly.api import get_snapshot_name


def test_publish_name():
    """
    Test publish name property
    """
    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection"):
        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []

        repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)
        assert repo.publish_name == "stretch_9.2_repos_testproject_1"


def test_name():
    """
    Test name property
    """
    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection"):
        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []

        repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)
        assert repo.name == "stretch-9.2-testproject-1"


def test_generate_snapshot_name_tmp():
    """
    Test generate temporary snapshot name
    """
    assert get_snapshot_name("test", "stable", temporary=True) == "test-stable-tmp"


def test_get_snapshot_name():
    """
    Test generate snapshot name
    """
    assert get_snapshot_name("test", "stable", temporary=False) == "test-stable"


def test_remove_old_packages():
    """
    Test remove old packages
    """
    now = datetime.strftime(datetime.now(), "%Y%m%d%H%M%S")
    new_package = "Pi386 test 1.0.0+git{}.57121d3 c36ac".format(now)
    packages = [
        "Pi386 test 1.0.0+git20170101120000.57121d3 c36ac",
        "Pi386 test 0.0.1 c36ac",
        new_package,
    ]

    with patch(
            "molior.molior.debianrepository.Configuration") as cfg_mock, patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.molior.debianrepository.logger"):

        cfg_mock.return_value.ci_builds = {"packages_ttl": 1}

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection

        aptly_connection.repo_packages_delete = AsyncMock(return_value=1337)
        aptly_connection.wait_task = AsyncMock(return_value=1342)

        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []
        repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)

        res = asyncio.run(repo._DebianRepository__remove_old_packages(packages))
        aptly_connection.wait_task.assert_called_with(1337)
        assert set(res).issubset([new_package, "Pi386 test 0.0.1 c36ac"])


def test_remove_old_packages_none():
    """
    Test remove old packages if there are no old packages
    """
    now = datetime.strftime(datetime.now(), "%Y%m%d%H%M%S")
    new_package = "Pi386 test 1.0.0+git{}.57121d3 c36ac".format(now)
    packages = [new_package]

    with patch(
            "molior.molior.debianrepository.Configuration") as cfg_mock, patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.molior.debianrepository.logger"):

        cfg_mock.return_value.ci_builds = {"packages_ttl": 1}

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.repo_packages_delete = AsyncMock(return_value=1337)
        aptly_connection.wait_task = AsyncMock(return_value=1342)

        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []
        repo = DebianRepository(
            basemirror_name, basemirror_version, project_name, project_version, archs
        )

        res = asyncio.run(repo._DebianRepository__remove_old_packages(packages))
        assert res == packages
        aptly_connection.repo_packages_delete.assert_not_called()


# def test_get_packages_non_ci():
#     """
#     Test get_packages non-ci packages
#     """
#     packages = [
#         "Pi386 test 1.0.0.57121d3 c36ac",
#         "Pi386 test 1.0.0+git20170101120000.57121d3 c36ac",
#     ]
#
#     with patch("molior.molior.debianrepository.Configuration"), patch(
#         "molior.molior.debianrepository.get_aptly_connection"
#     ) as get_aptly_connection, patch.object(
#         DebianRepository,
#         "_DebianRepository__remove_old_packages",
#         side_effect=asyncio.coroutine(
#             lambda a: ["Pi386 test 1.0.0+git20170101120000.57121d3 c36ac"]
#         ),
#     ) as remove_packages_mock:
#
#         aptly_connection = MagicMock()
#         get_aptly_connection.return_value = aptly_connection
#         aptly_connection.repo_packages_get = Mock(
#             side_effect=asyncio.coroutine(lambda a: packages)
#         )
#
#         basemirror_name = "stretch"
#         basemirror_version = "9.2"
#         project_name = "testproject"
#         project_version = "1"
#         archs = []
#         repo = DebianRepository(
#             basemirror_name, basemirror_version, project_name, project_version, archs
#         )
#
#         loop = asyncio.get_event_loop()
#         res = loop.run_until_complete(repo._DebianRepository__get_packages())
#         remove_packages_mock.assert_called_once()
#         assert res == ["Pi386 test 1.0.0.57121d3 c36ac"]


# def test_get_packages_ci():
#     """
#     Test get_packages ci packages
#     """
#     with patch("molior.molior.debianrepository.Configuration"), patch(
#         "molior.molior.debianrepository.get_aptly_connection"
#     ) as get_aptly_connection, patch.object(
#         DebianRepository,
#         "_DebianRepository__remove_old_packages",
#         side_effect=asyncio.coroutine(lambda a: []),
#     ) as remove_packages_mock:
#
#         aptly_connection = MagicMock()
#         get_aptly_connection.return_value = aptly_connection
#         aptly_connection.repo_packages_get = Mock(
#             side_effect=asyncio.coroutine(
#                 lambda a: ["Pi386 test 1.0.0+git20170101120000.57121d3 c36ac"]
#             )
#         )
#
#         basemirror_name = "stretch"
#         basemirror_version = "9.2"
#         project_name = "testproject"
#         project_version = "1"
#         archs = []
#         repo = DebianRepository(
#             basemirror_name, basemirror_version, project_name, project_version, archs
#         )
#
#         loop = asyncio.get_event_loop()
#         res = loop.run_until_complete(
#             repo._DebianRepository__get_packages(ci_build=True)
#         )
#         # remove_packages_mock.assert_called_once()
#         assert res == ["Pi386 test 1.0.0+git20170101120000.57121d3 c36ac"]


def test_add_packages():
    """
    Test add packages: upload to the stable repo, wait for the aptly task, delete the upload dir
    (the republish is a separate step, DebianRepository.republish)
    """
    files = ['file1', 'file2']

    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.molior.debianrepository.logger"):

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.repo_add = AsyncMock(return_value=(1337, "/tmp/upload"))
        aptly_connection.wait_task = AsyncMock(return_value=True)
        aptly_connection.delete_directory = AsyncMock(return_value=True)
        aptly_connection.republish = AsyncMock(return_value=True)

        repo = DebianRepository("jessie", "8.8", "test", "1", [])

        assert asyncio.run(repo.add_packages(files)) is True
        aptly_connection.repo_add.assert_awaited_once_with("jessie-8.8-test-1-stable", files)
        aptly_connection.wait_task.assert_awaited_once_with(1337)
        aptly_connection.delete_directory.assert_awaited_once_with("/tmp/upload")
        aptly_connection.republish.assert_not_called()


def test_add_packages_upload_fails():
    """
    Test add packages if the aptly task fails: False, the upload dir is kept
    """
    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.molior.debianrepository.logger"):

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.repo_add = AsyncMock(return_value=(1337, "/tmp/upload"))
        aptly_connection.wait_task = AsyncMock(return_value=False)
        aptly_connection.delete_directory = AsyncMock(return_value=True)

        repo = DebianRepository("jessie", "8.8", "test", "1", [])

        assert asyncio.run(repo.add_packages(["file1"], ci_build=True)) is False
        aptly_connection.repo_add.assert_awaited_once_with("jessie-8.8-test-1-unstable", ["file1"])
        aptly_connection.delete_directory.assert_not_called()


def test_init():
    """
    Test repo init
    """
    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.molior.debianrepository.get_snapshot_name") as get_snapshot_name, patch.object(
            DebianRepository, "publish_name", new_callable=PropertyMock) as publish_name_mock, patch.object(
            DebianRepository, "name", new_callable=PropertyMock) as name_mock, patch(
            "molior.molior.debianrepository.logger"):

        get_snapshot_name.return_value = "stretch_9.2_test_2-stable"
        name_mock.return_value = "stretch-9.2-test-2"
        publish_name_mock.return_value = "stretch_9.2_repos_test_2"

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.snapshot_create = AsyncMock(return_value=37)
        aptly_connection.snapshot_get = AsyncMock(return_value=[])
        aptly_connection.snapshot_publish = AsyncMock(return_value=38)
        aptly_connection.repo_get = AsyncMock(return_value=[])
        aptly_connection.repo_create = AsyncMock(return_value=None)

        async def wait_task_mock(_):
            """wait task mock"""
            return True

        aptly_connection.wait_task = wait_task_mock

        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []
        repo = DebianRepository(
            basemirror_name, basemirror_version, project_name, project_version, archs
        )
        repo.DISTS = ["stable"]

        assert asyncio.run(repo.init()) is True

        aptly_connection.repo_create.assert_called_with("stretch-9.2-test-2-stable")
        aptly_connection.snapshot_create.assert_called_with("stretch-9.2-test-2-stable", "stretch_9.2_test_2-stable")
        aptly_connection.snapshot_publish.assert_called_with(
            "stretch_9.2_test_2-stable",
            "main",
            ["source", "all"],
            "stable",
            "stretch_9.2_repos_test_2",
        )


def test_init_exists():
    """
    Test repo init if snapshot and repo already exist
    """
    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.molior.debianrepository.get_snapshot_name") as get_snapshot_name, patch.object(
            DebianRepository, "publish_name", new_callable=PropertyMock) as publish_name_mock, patch.object(
            DebianRepository, "name", new_callable=PropertyMock) as name_mock, patch(
            "molior.molior.debianrepository.logger"):

        name_mock.return_value = "stretch-9.2-test-2"
        publish_name_mock.return_value = "stretch_9.2_repos_test_2"

        get_snapshot_name.return_value = "stretch_9.2_test_2-stable"

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.snapshot_get = AsyncMock(return_value=[{"Name": "stretch_9.2_test_2-stable"}])
        aptly_connection.repo_get = AsyncMock(return_value=[{"Name": "stretch-9.2-test-2-stable"}])
        aptly_connection.repo_create = AsyncMock(return_value=None)

        async def wait_task_mock(_):
            """wait task mock"""
            return True

        aptly_connection.wait_task = wait_task_mock
        aptly_connection.snapshot_publish.return_value = 1337

        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []
        repo = DebianRepository(
            basemirror_name, basemirror_version, project_name, project_version, archs
        )
        repo.DISTS = ["stable"]

        assert asyncio.run(repo.init()) is False

        aptly_connection.repo_create.assert_not_called()
        aptly_connection.snapshot_publish.assert_not_called()


def _init_repo(aptly_connection):
    """
    Returns a DebianRepository with one dist and the given aptly connection
    """
    with patch("molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection", return_value=aptly_connection):
        repo = DebianRepository("stretch", "9.2", "testproject", "1", [])
    repo.DISTS = ["stable"]
    return repo


def _aptly_connection(calls, repo_task_ok=True):
    """
    Aptly connection mock which records the order of the calls
    """
    aptly = MagicMock()

    async def snapshot_get():
        return []

    async def repo_get():
        return []

    async def repo_create(name):
        calls.append("repo_create")
        return 1

    async def snapshot_create(repo_name, snapshot_name):
        calls.append("snapshot_create")
        return 2

    async def snapshot_publish(*args):
        calls.append("snapshot_publish")
        return 3

    async def wait_task(task_id):
        calls.append(f"wait_task {task_id}")
        return repo_task_ok if task_id == 1 else True

    aptly.snapshot_get = snapshot_get
    aptly.repo_get = repo_get
    aptly.repo_create = repo_create
    aptly.snapshot_create = snapshot_create
    aptly.snapshot_publish = snapshot_publish
    aptly.wait_task = wait_task
    return aptly


def test_init_waits_for_repo_create():
    """
    Test init waits for the aptly task which creates the repository before it creates the snapshot
    """
    calls = []
    repo = _init_repo(_aptly_connection(calls))
    assert asyncio.run(repo.init()) is True
    assert calls == ["repo_create", "wait_task 1", "snapshot_create", "wait_task 2", "snapshot_publish", "wait_task 3"]


def test_init_repo_create_fails():
    """
    Test init raises and does not go on if the aptly task which creates the repository failed
    """
    calls = []
    repo = _init_repo(_aptly_connection(calls, repo_task_ok=False))
    try:
        asyncio.run(repo.init())
        assert False, "init must raise"
    except Exception as exc:
        assert "creating repository" in str(exc) and "failed" in str(exc)
    assert calls == ["repo_create", "wait_task 1"]
