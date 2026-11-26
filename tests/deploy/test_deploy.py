"""Deploy tests: molior-deploy (molior-tools) creates the deployments of the testproject repo from a molior of the
test cluster. Port of test_molior_deploy of the 1.4 validation tests (molior-testing validation_tests.py, id 4643c058)
with two setup tests in front of it: in 1.4 the base mirror and the testproject build came from the tests before it."""
import os
import subprocess

import pytest

import utils
from utils import logger

basemirror = "trixie"
basemirror_version = "13"

# Its own base mirror (the system tests are not used): what the build environment, the testproject build and the
# deployments need. aptly adds the dependencies (FilterWithDeps).
basemirror_filter = (
    # debootstrap minbase (molior-deploy and the build environment), gnupg (molior-deploy --include)
    "Priority (required) | Priority (important) | gnupg | ca-certificates"
    # the build environment (create-docker.sh) and the build dependencies of testproject
    " | apt | build-essential | fakeroot | eatmydata | libfile-fcntllock-perl | lintian | devscripts | curl | git"
    " | passwd | debhelper"
    # the Depends of the testproject-* packages (testproject debian/control)
    " | net-tools | ifupdown | htop | isc-dhcp-client | iputils-ping | bash-completion | vim | wget | telnet | tree"
    " | linux-image-amd64 | grub-pc | xserver-xorg-video-vesa | xserver-xorg-input-evdev | xserver-xorg | nodm | lxde"
    " | polkitd | rsyslog | acpi-support-base | acpid | lxterminal"
    # the initrd of the installer variant (molior-tools plugins/installer.plugin), fdisk for SFDISK
    " | busybox | initramfs-tools | isolinux | syslinux-common | xz-utils | pv | util-linux | eject | fdisk"
)


# setup, not a 1.4 test (no metadata)
def test_deploy_basemirror():
    """
    Creates the base mirror of the deployments
    """
    logger.warning("==================================================== test_deploy_basemirror")
    utils.create_basemirror(basemirror, basemirror_version, "http://deb.debian.org/debian/", basemirror, "main",
                            ["amd64"], "hkp://keyserver.ubuntu.com:80",
                            "762F67A0B2C39DE4,78DBA3BC47EF2265,6ED0E7B82643E131", basemirror_filter)


# setup, not a 1.4 test (no metadata)
@pytest.mark.after("test_deploy_basemirror")
def test_deploy_testproject(project_name, project_version):
    """
    Builds the packages of the deployments (testproject: testproject-<variant>)
    """
    logger.warning("==================================================== test_deploy_testproject")
    utils.create_project(project_name, project_version, "{}/{}".format(basemirror, basemirror_version), ["amd64"],
                         "https://github.com/molior-dbs/testproject.git")
    utils.wait_for_build("testproject")


@pytest.mark.metadata(
    id="4643c058",
    author="im",
    requirements=["017"],
    reviewer="fb",
    review_date="Wed, 11 Nov 2020 15:51:54 +0100",
)
@pytest.mark.after("test_deploy_testproject")
@pytest.mark.parametrize(
    "build_type,build_type_output",
    [
        ("dir", "_dir.tar.gz"),
        ("docker", "_docker.tar.gz"),
        ("installer", "_installer.iso"),
        ("lxd", "_lxd.tar.gz"),
        ("vbox", "_vbox.ova"),
        ("image", "_image.img.gz"),
    ],
)
def test_molior_deploy(
    molior_url,
    aptly_url,
    project_name,
    project_version,
    build_type,
    build_type_output,
):
    """
    Tests molior deploy
    """
    logger.warning("==================================================== test_molior_deploy")
    # 1.4 ran it in the checkout; here in RESULTS_DIR: the deployment and its log (molior-deploy -L) stay there.
    # No stdin: molior-deploy must not wait for an answer (test-deploy.sh: -c, cleanup on error without asking).
    outcome = subprocess.run(
        [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "test-deploy.sh"),
            molior_url,
            aptly_url,
            project_name,
            project_version,
            build_type,
            build_type_output,
            "1.4.0~alpha3"
        ],
        cwd=utils.RESULTS,
        stdin=subprocess.DEVNULL,
    )
    assert outcome.returncode == 0, "Molior deploy exited with code {}".format(outcome)
