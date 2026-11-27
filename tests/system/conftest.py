"""Shared fixtures of the system tests. They run in the test runner pod (test-web.Dockerfile) inside the
test cluster and talk to molior at MOLIOR_URL (default http://web:8000)."""
import uuid

import pytest

from moliortest import Api, ADMIN_PASSWORD

# result lines with start time, number and time of each test (also used by tests/deploy)
pytest_plugins = ["pytest_output"]
# minutes a run of all system tests takes about (the eta after the start time, pytest_output.py)
RUN_MINUTES = 20


def pytest_output_run_minutes(config):
    return RUN_MINUTES


@pytest.fixture
def public():
    return Api()


@pytest.fixture
def admin():
    return Api().login("admin", ADMIN_PASSWORD)


@pytest.fixture
def unique():
    """A unique, valid molior name (letters, digits, dashes)."""
    return lambda prefix: f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Keeps the result of each phase on the test item (rep_call), so fixtures can take a screenshot on failure."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)
