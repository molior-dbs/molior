#!/bin/sh

set -e

# Stretch Backports (for sbuild)
echo "deb http://cdn-fastly.deb.debian.org/debian stretch-backports main" > /etc/apt/sources.list.d/backports.list

cat >/etc/apt/apt.conf.d/77molior <<EOF
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
EOF

cat >/etc/apt/preferences.d/backports <<EOF
Package: *
Pin: release a=stretch-backports
Pin-Priority: 900

Package: *
Pin: release a=stretch
Pin-Priority: 800
EOF

apt-get update

export DEBIAN_FRONTEND=noninteractive
apt-get --yes dist-upgrade



