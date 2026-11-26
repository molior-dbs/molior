#!/bin/sh
# Install molior-tools (molior-deploy) and what the deploy tests need on a CI runner (Debian or Ubuntu, sudo).
# Usage: .github/scripts/install-molior-tools.sh <git ref>
#   <git ref>: tag, branch or commit of https://github.com/molior-dbs/molior-tools (MOLIOR_TOOLS_VERSION in ci.yml)
#
# molior-tools has no release packages: the deb is built from the source of the ref (dpkg-buildpackage) and
# installed with apt, which pulls its dependencies. Also installed:
#   - the host tools of the deployment variants of the testproject repo (molior-tools plugins/*.plugin):
#     installer: genisoimage xorriso syslinux-utils mtools dosfstools; vbox: virtualbox kpartx qemu-utils (and the
#     kernel module nbd); docker: docker (already on the runner)
#   - virtualbox as packaged by the distribution (with its kernel module, virtualbox-dkms); the vbox plugin only
#     creates the disk and the VM and exports the OVA (vboxmanage), it never starts a VM
#   - python3 with pytest, pytest-timeout and requests (tests/deploy runs on the host)
set -eu

REF=${1:?usage: $0 <git ref>}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

echo "== packages"
sudo apt-get update -q
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
    git build-essential dpkg-dev debhelper dh-python python3-all python3-setuptools txt2man man2html-base \
    genisoimage xorriso syslinux-utils mtools dosfstools kpartx qemu-utils \
    python3-pytest python3-pytest-timeout python3-requests

echo "== virtualbox"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q virtualbox

echo "== molior-tools $REF"
git -c advice.detachedHead=false clone -q --depth 1 --branch "$REF" https://github.com/molior-dbs/molior-tools.git \
    "$T/molior-tools" 2>/dev/null || {
    # a commit id: clone everything and check it out
    git clone -q https://github.com/molior-dbs/molior-tools.git "$T/molior-tools"
    git -C "$T/molior-tools" -c advice.detachedHead=false checkout -q "$REF"
}
git -C "$T/molior-tools" log --oneline -1
(cd "$T/molior-tools" && dpkg-buildpackage -us -uc -b >"$T/build.log" 2>&1) || { cat "$T/build.log"; exit 1; }
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "$T"/molior-tools_*_all.deb
cat /usr/lib/molior-tools/version

echo "== kernel module nbd (vbox variant)"
sudo modprobe nbd
grep -q '^nbd ' /proc/modules
vboxmanage -v
