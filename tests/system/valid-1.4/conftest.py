"""Fixtures of the 1.4 validation tests (molior-testing conftest.py), ported to the current API."""
import pytest

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
