"""Fixtures of the 1.4 validation tests (molior-testing conftest.py), ported to the current API."""
import pytest

import api_tests
import utils


def pytest_configure(config):
    # marks of the 1.4 tests: metadata for the validation report, first/after for the order (pytest-order is not
    # used; the tests run in file order)
    config.addinivalue_line("markers", "metadata(**kwargs): validation metadata (id, author, requirements)")
    config.addinivalue_line("markers", "first: run first (1.4 ordering)")
    config.addinivalue_line("markers", "after(name): run after the named test (1.4 ordering)")


@pytest.fixture
def molior_url():
    yield utils.MOLIOR_URL


@pytest.fixture
def create_mirror(molior_url):
    """
    Returns utils to create a mirror
    """

    def __create_mirror(*args, **kwargs):
        utils.create_mirror(molior_url, *args, **kwargs)

    yield __create_mirror


@pytest.fixture
def aptly_url():
    """URL of the published APT repos (aptly nginx), as the 1.4 testconfig.yaml aptly_url"""
    yield utils.APTLY_URL


@pytest.fixture(scope="session")
def project_name():
    yield "{}-{}".format("molior", "validation")


@pytest.fixture
def project_version():
    yield "1"


@pytest.fixture
def aptly_api_url():
    """URL of the aptly REST API (nginx with basic auth in front of aptly), as the 1.4 testconfig.yaml aptly_api_url"""
    yield utils.APTLY_API_URL


@pytest.fixture
def api_vars(project_name, project_version, molior_url, aptly_url, aptly_api_url):
    yield {
        "molior_url": molior_url,
        "aptly_url": aptly_url,
        "aptly_api_url": aptly_api_url,
        "api_user": "admin",
        "api_password": utils.ADMIN_PASSWORD,
        "project_name": project_name,
        "projectversion_name": project_version,
    }


@pytest.fixture
def api_test(api_vars):
    """
    Runs a 1.4 API test suite (tests/api-tests/<name>.yml, translated in api_tests.py)
    """

    def __api_test(path):
        api_tests.SUITES[path](api_vars)

    yield __api_test


@pytest.fixture
def aptly_api_test(api_vars):
    """
    Runs a 1.4 API test suite against the aptly API URL
    """

    def __aptly_api_test(path):
        api_tests.SUITES[path](api_vars)

    yield __aptly_api_test


@pytest.fixture
def build_test(api_vars):
    """
    Executes a build and tests if it succeeded

    1.4 ran the yml with pyresttest (utils.execute_build_test); here the translated suite of api_tests.py runs
    directly. Returns what the suite returns (ci-build.yml: the build id).
    """

    def __execute_build_test(api_test_description, build_vars=api_vars):
        return api_tests.SUITES[api_test_description](build_vars)

    yield __execute_build_test


@pytest.fixture
def get_project_vars(api_vars):
    """
    Returns a callable with the build variables

    1.4 returned a JSON string for pyresttest with its fixed test user; here a dict with the admin of api_vars.
    """

    def __get_project_vars(project_name, project_version, repository_url):
        return dict(api_vars, project_name=project_name, projectversion_name=project_version, repo_url=repository_url)

    yield __get_project_vars


@pytest.fixture
def get_basemirror(molior_url):
    """
    Returns ID of base mirror
    """

    def __get_basemirror(*args, **kwargs):
        return utils.get_basemirror(molior_url, *args, **kwargs)

    yield __get_basemirror


@pytest.fixture
def get_build_id(molior_url):
    """
    Returns a callable to get the build id
    """

    def __get_build_id(package):
        return utils.get_build(molior_url, package).get("id")

    yield __get_build_id


@pytest.fixture
def molior_exec():
    """
    Returns a callable that runs a shell command in the molior server container and returns its stdout
    (1.4: molior_ssh_run, ssh to the molior host). Raises when the command fails.
    """

    def __molior_exec(command):
        return utils.molior_exec(command)

    yield __molior_exec


@pytest.fixture
def aptly_exec():
    """
    Returns a callable that runs a shell command in the aptly server container and returns its stdout
    (1.4: aptly_ssh_run, ssh to the aptly host). Raises when the command fails.
    """

    def __aptly_exec(command):
        return utils.aptly_exec(command)

    yield __aptly_exec
