"""Fixtures of the deploy tests (tests/deploy/deploy-tests.sh). They run on the runner host, not in the test cluster:
molior-deploy needs root (sudo), loop devices, nbd, docker and virtualbox."""
import pytest

import utils


# minutes a run of all deploy tests takes about (the eta after the start time, tests/system/pytest_output.py)
RUN_MINUTES = 20


def pytest_output_run_minutes(config):
    return RUN_MINUTES


def pytest_configure(config):
    # marks of the 1.4 test (molior-testing validation_tests.py); the tests run in file order
    config.addinivalue_line("markers", "metadata(**kwargs): validation metadata (id, author, requirements)")
    config.addinivalue_line("markers", "after(name): run after the named test (1.4 ordering)")


# Without the base mirror or the testproject packages every deployment fails: stop the run.
STOP_ON_FAILURE = ("test_deploy_basemirror", "test_deploy_testproject")
_session = []


def pytest_sessionstart(session):
    _session.append(session)


def pytest_runtest_logreport(report):
    if report.failed and report.nodeid.split("::")[-1] in STOP_ON_FAILURE and _session:
        _session[0].shouldstop = "{} failed, the deployments need it".format(report.nodeid)


@pytest.fixture
def molior_url():
    yield utils.MOLIOR_URL


@pytest.fixture
def aptly_url():
    """URL of the published APT repos as the host sees them (aptly.publicUrl of the test install)"""
    yield utils.APTLY_URL


@pytest.fixture(scope="session")
def project_name():
    # the target of debian/molior.yml of the testproject repo
    yield "molior-validation"


@pytest.fixture
def project_version():
    yield "1"
