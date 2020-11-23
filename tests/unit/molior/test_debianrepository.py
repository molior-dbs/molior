"""
Provides test molior configuration class.
"""
import asyncio
from datetime import datetime

from mock import patch, Mock, MagicMock, PropertyMock

from molior.molior.debianrepository import DebianRepository
from molior.tools import get_snapshot_name


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

        aptly_connection.repo_packages_delete = Mock(side_effect=asyncio.coroutine(lambda a, b: 1337))
        aptly_connection.wait_task = Mock(side_effect=asyncio.coroutine(lambda a: 1342))

        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []
        repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)

        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(repo._DebianRepository__remove_old_packages(packages))
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
        aptly_connection.repo_packages_delete.return_value = 1337
        aptly_connection.wait_task = Mock(side_effect=asyncio.coroutine(lambda a: 1342))

        basemirror_name = "stretch"
        basemirror_version = "9.2"
        project_name = "testproject"
        project_version = "1"
        archs = []
        repo = DebianRepository(
            basemirror_name, basemirror_version, project_name, project_version, archs
        )

        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(
            repo._DebianRepository__remove_old_packages(packages)
        )
        assert res == packages


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
    Test add packages
    """
    files = []

    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.tools.get_snapshot_name") as get_snapshot_name, patch.object(
            DebianRepository, "publish_name", new_callable=PropertyMock) as publish_name, patch(
            "molior.molior.debianrepository.logger"):

        get_snapshot_name.return_value = "jessie_8.8_repos_test_1-stable"
        publish_name.return_value = "jessie_8.8_repos_test_1"

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.repo_add = Mock(side_effect=asyncio.coroutine(lambda a, b: (1337, "/tmp")))
        aptly_connection.delete_directory = Mock(side_effect=asyncio.coroutine(lambda a: True))
        aptly_connection.snapshot_create = Mock(side_effect=asyncio.coroutine(lambda a, b: 1338))
        aptly_connection.snapshot_get = Mock(
            side_effect=asyncio.coroutine(
                lambda: [
                    {"Name": "jessie_8.8_repos_test_1-stable"},
                    {"Invalid": 1},
                ]
            )
        )
        aptly_connection.snapshot_delete = Mock(side_effect=asyncio.coroutine(lambda a: 1339))
        aptly_connection.snapshot_publish_update = Mock(side_effect=asyncio.coroutine(lambda a, b, c, d: 1340))
        aptly_connection.snapshot_rename = Mock(side_effect=asyncio.coroutine(lambda a, b: 1341))
        aptly_connection.wait_task = Mock(side_effect=asyncio.coroutine(lambda a: 1342))
        aptly_connection.republish = Mock(side_effect=asyncio.coroutine(lambda a, b, c: None))

        basemirror_name = "jessie"
        basemirror_version = "8.8"
        project_name = "test"
        project_version = "1"
        archs = []
        repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(repo.add_packages(files))
        aptly_connection.republish.assert_called_with(
            "stable",
            "jessie-8.8-test-1-stable",
            "jessie_8.8_repos_test_1",
        )


def test_init():
    """
    Test repo init
    """
    loop = asyncio.get_event_loop()

    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.tools.get_snapshot_name") as get_snapshot_name, patch.object(
            DebianRepository, "publish_name", new_callable=PropertyMock) as publish_name_mock, patch.object(
            DebianRepository, "name", new_callable=PropertyMock) as name_mock, patch(
            "molior.molior.debianrepository.logger"):

        get_snapshot_name.return_value = "stretch_9.2_test_2-stable"
        name_mock.return_value = "stretch-9.2-test-2"
        publish_name_mock.return_value = "stretch_9.2_repos_test_2"

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.snapshot_create = Mock(
            side_effect=asyncio.coroutine(lambda a, b: 37)
        )
        aptly_connection.snapshot_get = Mock(side_effect=asyncio.coroutine(lambda: []))
        aptly_connection.snapshot_publish = Mock(
            side_effect=asyncio.coroutine(lambda a, b, c, d, e: 38)
        )
        aptly_connection.repo_get = Mock(side_effect=asyncio.coroutine(lambda: []))
        aptly_connection.repo_create = Mock(
            side_effect=asyncio.coroutine(lambda a: None)
        )

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

        loop.run_until_complete(repo.init())

        aptly_connection.repo_create.assert_called_with("stretch-9.2-test-2-stable")
        aptly_connection.snapshot_publish.assert_called_with(
            "stretch_9.2_repos_test_2-stable",
            "main",
            ["source", "all"],
            "stable",
            "stretch_9.2_repos_test_2",
        )


def test_init_exists():
    """
    Test repo init if snapshot and repo already exist
    """
    loop = asyncio.get_event_loop()

    with patch(
            "molior.molior.debianrepository.Configuration"), patch(
            "molior.molior.debianrepository.get_aptly_connection") as get_aptly_connection, patch(
            "molior.tools.get_snapshot_name") as get_snapshot_name, patch.object(
            DebianRepository, "publish_name", new_callable=PropertyMock) as publish_name_mock, patch.object(
            DebianRepository, "name", new_callable=PropertyMock) as name_mock, patch(
            "molior.molior.debianrepository.logger"):

        name_mock.return_value = "stretch-9.2-test-2"
        publish_name_mock.return_value = "stretch_9.2_repos_test_2"

        get_snapshot_name.return_value = "stretch_9.2_test_2-stable"

        aptly_connection = MagicMock()
        get_aptly_connection.return_value = aptly_connection
        aptly_connection.snapshot_get = Mock(
            side_effect=asyncio.coroutine(
                lambda: [{"Name": "stretch_9.2_test_2-stable"}]
            )
        )
        aptly_connection.repo_get = Mock(
            side_effect=asyncio.coroutine(lambda: [{"Name": "stretch-9.2-test-2-stable"}])
        )
        aptly_connection.repo_create = Mock(
            side_effect=asyncio.coroutine(lambda a: None)
        )

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

        loop.run_until_complete(repo.init())

        aptly_connection.repo_create.assert_not_called()
        aptly_connection.snapshot_publish.assert_not_called()
