# Integration tests for molior
#
# Ported from the molior 1.4 validation suite (molior-testing, validation_tests.py). Test names, ids,
# requirements and steps are unchanged; changed are the values that pointed to the old site (trixie instead of
# stretch, deb.debian.org instead of the internal mirror) and the helpers in utils.py, which use the current API.

import pytest
import requests
from time import sleep

from utils import logger, wait_for_paralell_builds

basemirror = "trixie"
basemirror_version = "13"

# Only what the build environments and the test packages need (see DEVELOPMENT-1.5.md): debootstrap (Priority required,
# apt, build-essential, ca-certificates), the build environment tools (create-docker.sh) and the build
# dependencies of the test packages (debhelper, python3). aptly adds their dependencies (FilterWithDeps).
basemirror_filter = (
    "Priority (required) | apt | build-essential | ca-certificates"
    " | fakeroot | eatmydata | libfile-fcntllock-perl | lintian | devscripts | curl | git | passwd"
    " | debhelper | python3"
)


@pytest.mark.metadata(
    id="dbcf79da",
    author="im",
    requirements=["001", "002", "004"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_cleanup")
def test_basemirror_creation(create_mirror):
    """
    Tests the mirror creation on molior
    """
    logger.warning("==================================================== test_basemirror_creation")
    create_mirror(
        "http://deb.debian.org/debian/",
        basemirror,
        basemirror_version,
        basemirror,
        "main",
        "amd64",
        is_basemirror=True,
        keyserver="hkp://keyserver.ubuntu.com:80",
        keys="762F67A0B2C39DE4,78DBA3BC47EF2265,6ED0E7B82643E131",
        allow_rerun=True,
        mirror_filter=basemirror_filter,
        filter_with_deps=True,
    )


@pytest.mark.metadata(
    id="c0588942",
    author="im",
    requirements=["000", "006", "007", "016"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_basemirror_creation")
def test_build_parallelization(
    molior_url,
    aptly_url,
    api_test,
    project_name,
):
    """
    Tests the parallel building of repositories
    """
    logger.warning("==================================================== test_build_parallelization")

    # create the repositories using the api test
    api_test("tests/api-tests/init-testproject.yml")

    print("APTLY URL TEST: ", "{}/{}/{}/repos/{}".format(aptly_url, basemirror, basemirror_version, project_name))
    # verify that the aptly repository has been created
    response = requests.get(
        "{}/{}/{}/repos/{}".format(aptly_url, basemirror, basemirror_version, project_name)
    )
    assert response.ok, "The aptly repo was not created for project '{}'".format(
        project_name
    )

    sleep(5)
    # wait for the processes to finish
    # 1.4 waited for repo names ("build-notifications", "ci-build", "badtick", ...); the deb builds carry the source
    # package name, so the 1.4 wait always ran into its timeout. Source package names, badtrick has no molior.yml
    # and builds nothing.
    builds = wait_for_paralell_builds(molior_url, ["build-notify-package", "cipackage", "testproject",
                                                   "badtrack", "trick", "tick", "track"])
    for b in builds:
        assert b.get("buildstate") == "successful" or b.get("buildstate") == "build_failed" \
            or b.get("buildstate") == "nothing_done"
