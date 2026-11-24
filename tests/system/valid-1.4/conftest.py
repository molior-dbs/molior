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
