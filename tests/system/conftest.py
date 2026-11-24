"""Shared fixtures of the system tests. They run in the test runner pod (test-web.Dockerfile) inside the
test cluster and talk to molior at MOLIOR_URL (default http://web:8000)."""
import uuid

import pytest

from moliortest import Api, ADMIN_PASSWORD


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


_setup_time = {}   # nodeid: setup time of a test whose setup passed (added to its call time)
_shown = {}        # nodeid: time to show next to the result of the phase just reported


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_logreport(report):
    """Remembers the time to show for each phase (pytest_report_teststatus is also called for the summary)."""
    if report.when == "setup" and report.passed:
        _setup_time[report.nodeid] = report.duration
    elif report.when == "call":
        _shown[report.nodeid] = _setup_time.pop(report.nodeid, 0) + report.duration
    else:
        _shown[report.nodeid] = report.duration
    yield
    _shown.pop(report.nodeid, None)


@pytest.hookimpl(hookwrapper=True)
def pytest_report_teststatus(report, config):
    """Shows the time of each test (setup and call) right after its result: "PASSED 66.2s [ 18%]"."""
    outcome = yield
    category, letter, word = outcome.get_result()
    if not word or report.nodeid not in _shown:
        return  # no result line for this phase, or called for the summary at the end
    seconds = " {:.1f}s".format(_shown[report.nodeid])
    word = (word[0] + seconds, word[1]) if isinstance(word, tuple) else word + seconds
    outcome.force_result((category, letter, word))
