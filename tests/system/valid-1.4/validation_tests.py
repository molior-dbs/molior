# Integration tests for molior
#
# Ported from the molior 1.4 validation suite (molior-testing, validation_tests.py). Test names, ids,
# requirements and steps are unchanged; changed are the values that pointed to the old site (trixie instead of
# stretch, deb.debian.org instead of the internal mirror) and the helpers in utils.py, which use the current API.

import pytest

from utils import logger

basemirror = "trixie"
basemirror_version = "13"

# Only what the build environments and the test packages need (see README.md): debootstrap (Priority required,
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
