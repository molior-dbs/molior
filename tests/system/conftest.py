"""Shared fixtures of the system tests. They run in the test runner pod (test-web.Dockerfile) inside the
test cluster and talk to molior at MOLIOR_URL (default http://web:8000)."""
import datetime
import math
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


def pytest_report_collectionfinish(config, start_path, items):
    """The start time of the tests, after the "collected N items" line."""
    return "start: " + datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Keeps the result of each phase on the test item (rep_call), so fixtures can take a screenshot on failure."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


_setup_time = {}   # nodeid: setup time of a test whose setup passed (added to its call time)
_shown = {}        # nodeid: time of the phase just reported
_pending = []      # the time to show in front of the percentage of the result line being written


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
    _pending.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_report_teststatus(report, config):
    """Pads the word of a result line (not of the summary) to one column and marks the line to get its time."""
    outcome = yield
    category, letter, word = outcome.get_result()
    if not word or report.nodeid not in _shown:
        return
    _pending[:] = [_shown[report.nodeid]]
    word = (word[0].ljust(7), word[1]) if isinstance(word, tuple) else word.ljust(7)
    outcome.force_result((category, letter, word))


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    """Result lines in verbose mode: the start time of the test (UTC), the number of the test, the location and the
    result in columns, the time of the test (setup and call) in whole seconds, rounded up, before the percentage:
        "13:09:09  3/20: valid-1.4/validation_tests.py::test_api       PASSED     1s [ 15%]"
    Uses the location line and the progress message of pytest's terminal reporter (private, checked)."""
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if not reporter or config.option.verbose <= 0:
        return
    needed = ("_get_progress_information_message", "_write_progress_information_filling_space", "_get_main_color",
              "_locationline", "_session")
    if not all(hasattr(reporter, a) for a in needed):
        return
    progress = reporter._get_progress_information_message
    location = reporter._locationline
    columns = {}   # nodeid: number of the test; "width": width of the longest location
    started = {}   # nodeid: start time; pytest writes the location again if it changes between start and result

    def with_time():
        msg = progress()
        return " {:>5}".format("{}s".format(math.ceil(_pending[0]))) + msg if _pending else msg

    def right_after():
        # pytest right-aligns the progress to the terminal width; write it right after the result instead
        color, _ = reporter._get_main_color()
        reporter.write(reporter._get_progress_information_message(), flush=True, **{color: True})

    def numbered(nodeid, *args):
        items = getattr(reporter._session, "items", None) or []
        if not columns and items:
            for i, item in enumerate(items, 1):
                columns[item.nodeid] = i
            columns["width"] = max(len(location(item.nodeid, *item.location)) for item in items)
        if nodeid not in columns:
            return location(nodeid, *args)
        total = len(items)
        if nodeid not in started:
            started[nodeid] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
        return "{} {:>{}}/{}: {} ".format(started[nodeid], columns[nodeid], len(str(total)), total,
                                          location(nodeid, *args).ljust(columns["width"]))

    reporter._get_progress_information_message = with_time
    reporter._locationline = numbered
    reporter._write_progress_information_filling_space = right_after
