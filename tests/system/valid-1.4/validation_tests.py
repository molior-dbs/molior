# Integration tests for molior
#
# Ported from the molior 1.4 validation suite (molior-testing, validation_tests.py). Test names, ids,
# requirements and steps are unchanged; changed are the values that pointed to the old site (trixie instead of
# stretch, deb.debian.org instead of the internal mirror) and the helpers in utils.py, which use the current API.

import os

import pytest
import requests
from datetime import datetime
from time import sleep

from utils import get_build, get_build_log, get_deb_build_ids, logger, wait_for_paralell_builds

basemirror = "trixie"
basemirror_version = "13"
# The 1.4 test mirrored an internal repository (a vendor printer driver, one package). Its URLs are not in the code:
# CITIZEN_MIRROR_URL is the repository root (with dists/), CITIZEN_KEY_URL its armored signing key. Without them
# the test is skipped.
citizen_mirror_url = os.environ.get("CITIZEN_MIRROR_URL", "")
citizen_key_url = os.environ.get("CITIZEN_KEY_URL", "")

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


@pytest.mark.metadata(
    id="4a919a48",
    author="im",
    requirements=["000", "001", "010"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_build_parallelization")
def test_build_output(aptly_url, project_name):
    """
    Tests if the debian packages have been built
    """
    logger.warning("==================================================== test_build_output")
    debian_packages = {
        "trick": True,
        "trick-dev": True,
        "trick-dbg": True,
        "track": True,
        "tick": True,
        "badtrick": False,
        "testproject-vbox": True,
    }

    # get the packages file from aptly
    logger.warning("REQUEST: {}/{}/{}/repos/{}/1/dists/stable/main/binary-amd64/Packages".format(
                    aptly_url, basemirror, basemirror_version, project_name
                            ))
    packages_response = requests.get(
        "{}/{}/{}/repos/{}/1/dists/stable/main/binary-amd64/Packages".format(
            aptly_url, basemirror, basemirror_version, project_name
        )
    )
    assert (
        packages_response.ok
    ), "Could not download packages file for repo '{}'".format(
        project_name
    )
    packages = packages_response.text
    logger.warning("PACKAGES: {}".format(packages_response))

    for package in debian_packages:
        logger.warning("CHECKING PACKAGE: %s" % package)
        found = "Package: {}".format(package) in packages
        assert (
            found == debian_packages[package]
        ), "Package occurence is unexpected {} should be {}".format(
            package, debian_packages[package]
        )


@pytest.mark.metadata(
    id="8a89f528",
    author="im",
    requirements=["100", "101"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_schroot_creation")
def test_api(api_test):
    """
    Tests various api calls
    """
    logger.warning("==================================================== test_api")
    api_test("tests/api-tests/get-tests.yml")


@pytest.mark.metadata(
    id="8cd64879",
    author="im",
    requirements=["010"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_api")
def test_aptly(aptly_api_test):
    """
    Tests the aptly repository
    """
    logger.warning("==================================================== test_aptly")
    aptly_api_test("tests/api-tests/aptly.yml")


@pytest.mark.metadata(
    id="b8f486cc",
    author="fb",
    requirements=["008"],
    reviewer="ra",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_api")
def test_projectversion_delete(api_test):
    """
    Tests the creation and deletion of a projectversion
    """
    logger.warning("==================================================== test_projectversion_delete")
    api_test("tests/api-tests/delete-projectversion.yml")


@pytest.mark.metadata(
    id="681288e5",
    author="fb",
    requirements=["007"],
    reviewer="ra",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_projectversion_delete")
def test_projectversion_clone(api_test):
    """
    Tests the cloning of a projectversion
    """
    logger.warning("==================================================== test_projectversion_clone")
    api_test("tests/api-tests/clone-projectversion.yml")


@pytest.mark.metadata(
    id="c6b970e6",
    author="fb",
    requirements=["007"],
    reviewer="ra",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_projectversion_clone")
def test_projectversion_overlay(api_test):
    """
    Tests the creation of an overlay of a projectversion
    """
    logger.warning("==================================================== test_projectversion_overlay")
    api_test("tests/api-tests/overlay-projectversion.yml")


@pytest.mark.metadata(
    id="375cd781",
    author="fb",
    requirements=["102", "007"],
    reviewer="ra",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_projectversion_overlay")
def test_projectversion_dependency_edit(api_test):
    """
    Tests editing of dependencies of a projectversion
    """
    logger.warning("==================================================== test_projectversion_dependency_edit")
    api_test("tests/api-tests/edit-dependencies.yml")


@pytest.mark.metadata(
    id="e34fe8d2",
    author="fb",
    requirements=["100"],
    reviewer="ra",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_projectversion_dependency_edit")
def test_projectversion_search_and_sort(api_test):
    """
    Tests sorting of projectversions of a project
    """
    logger.warning("==================================================== test_projectversion_search_and_sort")
    api_test("tests/api-tests/sorted.yml")


@pytest.mark.metadata(
    id="99106b79",
    author="fb",
    requirements=["007"],
    reviewer="ra",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_projectversion_search_and_sort")
def test_projectversion_repository_delete(api_test):
    """
    Tests projectversion repository delete
    """
    logger.warning("==================================================== test_projectversion_repository_delete")
    api_test("tests/api-tests/delete-repository.yml")


@pytest.mark.metadata(
    id="f58bdeb5",
    author="im",
    requirements=["002"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_projectversion_repository_delete")
def test_mirror(create_mirror, get_basemirror, aptly_url):
    """
    Tests the mirroring
    """
    logger.warning("==================================================== test_mirror")
    if not citizen_mirror_url or not citizen_key_url:
        pytest.skip("CITIZEN_MIRROR_URL and CITIZEN_KEY_URL are not set")
    basemirror_id = get_basemirror(basemirror, basemirror_version)
    assert basemirror_id, "Base mirror not found"

    create_mirror(
        citizen_mirror_url,
        "citizen",
        "1.2.2-0",
        "stretch",
        "main",
        "amd64",
        basemirror_id=basemirror_id,
        keyurl=citizen_key_url,
        allow_rerun=True,
    )
    response = requests.get(
        "{}/{}/{}/mirrors/citizen/1.2.2-0/dists/stretch/".format(aptly_url, basemirror, basemirror_version)
    )
    assert response.ok, "The debian mirror was not created on the apt host"


@pytest.mark.metadata(
    id="a201b9df",
    author="im",
    requirements=["014", "015", "012", "010"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_mirror")
def test_successful_build(molior_url):
    """
    Short tests a build
    """
    logger.warning("==================================================== test_successful_build")
    build = get_build(molior_url, "track", buildstate="successful")
    assert build, "no successful build found: track"

    # 1.4 read /buildout/<id>/build.log over HTTP and checked "Status: successful"; 1.5 has neither, the log is read
    # in the molior container and a successful deb build log ends with the title "molior: Done"
    log = get_build_log(build.get("id"), "molior: Done")
    # test that the build was successful
    assert "molior: Done" in log, "Build was not successful"


@pytest.mark.metadata(
    id="6b0e3946",
    author="im",
    requirements=["014", "015", "012", "010"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_build_short")
def test_failed_build(molior_url):
    """
    Short tests a failed build
    """
    logger.warning("==================================================== test_failed_build")
    build = get_build(molior_url, "badtrack", buildstate="build_failed")
    assert build, "no %s build found: %s" % ("build_failed", "badtrack")

    # 1.4 checked "Error: sbuild command failed"; the 1.5 build script writes the title "molior: Building failed"
    log = get_build_log(build.get("id"), "molior: Building failed")
    # verify that the build has failed
    assert (
        "molior: Building failed" in log
    ), "Could not determine that the build failed"


@pytest.mark.metadata(
    id="cec29475",
    author="im",
    requirements=["014", "015", "012", "010"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_failed_build_short")
def test_build_log(get_build_id, molior_url, molior_exec):
    """
    Short tests if the build log exists
    """
    logger.warning("==================================================== test_build_log")
    build_id = get_build_id("trick")

    log = get_build_log(build_id, "molior: Done")
    # verify that the build has failed
    assert (
        "molior: Done" in log
    ), "Could not determine that the build failed"

    # verify that the log file exists on the molior server
    molior_exec("ls /var/lib/molior/buildout/{}/build.log".format(build_id))


@pytest.mark.metadata(
    id="4b46b62f",
    author="im",
    requirements=["016", "000", "001"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_build_log")
def test_build_order(molior_url):
    """
    Tests wether the build order was correct
    """
    logger.warning("==================================================== test_build_order")

    track = get_build(molior_url, "track", buildstate="successful")
    tick = get_build(molior_url, "tick", buildstate="successful")
    track_end = track.get("endstamp")
    tick_start = tick.get("startstamp")

    # '2020-10-30T16:14:30.433904+0100'
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
    assert not datetime.strptime(tick_start, fmt) < datetime.strptime(track_end, fmt), \
        "tick '{}' should have been started after track '{}' has ended.".format(tick_start, track_end)


@pytest.mark.metadata(
    id="348c848a",
    author="im",
    requirements=["300", "301"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_build_order")
def test_role_based_access(api_test):
    """
    Tests the role access to molior
    """
    logger.warning("==================================================== test_role_based_access")
    api_test("tests/api-tests/rolebasedaccess.yml")


@pytest.mark.metadata(
    id="3c84a262",
    author="im",
    requirements=["018", "000", "001", "010"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_role_based_access")
def test_multi_project_builds(molior_url, aptly_url, build_test, project_name):
    """
    Tests the build of multiple projects
    """
    logger.warning("==================================================== test_multi_project_builds")
    # cipackage was built by test_build_parallelization: wait for the new (CI) build only
    known_builds = get_deb_build_ids(molior_url, ["cipackage", "multiproject"])
    build_test("tests/api-tests/ci-build.yml")
    build_test("tests/api-tests/multi-project.yml")

#    get_build(molior_url, "cipackage", buildstate="successful")
#    get_build(molior_url, "multiproject", buildstate="successful")

    sleep(5)
    # wait for the processes to finish
    # 1.4 waited for the repo name "ci-build"; the deb builds carry the source package name cipackage, so 1.4 never
    # found the CI build and always ran into its timeout
    builds = wait_for_paralell_builds(molior_url, ["cipackage", "multiproject"], ignore_ids=known_builds)
    assert {b.get("sourcename") for b in builds} == {"cipackage", "multiproject"}, "builds missing: {}".format(builds)
    for b in builds:
        print(b)
        if b.get("sourcename") == "multiproject":
            assert b.get("buildstate") == "successful"
        if b.get("sourcename") == "cipackage":
            assert b.get("buildstate") == "successful"

    expected_package = "multiproject"

    # verify that the aptly repository has been created
    response = requests.get(
        "{}/{}/{}/repos/{}/{}/dists/stable/main/binary-amd64/Packages".format(
            aptly_url, basemirror, basemirror_version, project_name, "prj1"
        )
    )
    assert (
        response.ok
    ), "The aptly repo was not created for project '{}', version '{}'".format(
        project_name, "prj1"
    )
    assert (
        expected_package in response.text
    ), "Could not find expected package in the packages"

    response = requests.get(
        "{}/{}/{}/repos/{}/{}/dists/stable/main/binary-amd64/Packages".format(
            aptly_url, basemirror, basemirror_version, project_name, "prj2"
        )
    )
    assert (
        response.ok
    ), "The aptly repo was not created for project '{}', version '{}'".format(
        project_name, "prj2"
    )
    assert (
        expected_package in response.text
    ), "Could not find expected package in the packages"


@pytest.mark.metadata(
    id="2872bce4",
    author="im",
    requirements=["000", "001"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_mono_build")
def test_git_lfs_build(molior_url, build_test, get_project_vars, project_name):
    """
    Test a build using the mono mirror
    """
    logger.warning("==================================================== test_git_lfs_build")
    build_test(
        "tests/api-tests/create-project.yml",
        get_project_vars(
            project_name,
            "git-lfs",
            "https://github.com/molior-dbs/test-git-lfs.git",
        ),
    )
    get_build(molior_url, "git-lfs-test", buildstate="successful")


@pytest.mark.metadata(
    id="d2a19958",
    author="im",
    requirements=["000", "001"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_git_lfs_build")
def test_submodule_build(molior_url, build_test, get_project_vars, project_name):
    """
    Test a build using the mono mirror
    """
    logger.warning("==================================================== test_submodule_build")
    build_test(
        "tests/api-tests/create-project.yml",
        get_project_vars(
            project_name,
            "submodule",
            "https://github.com/molior-dbs/test-submodule.git",
        ),
    )
    get_build(molior_url, "submodulepackage", buildstate="successful")
