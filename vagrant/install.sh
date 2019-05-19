#!/bin/sh

set -e

# Stretch Backports (for git-lfs, nodejs, npm)
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
apt-get install --yes --no-install-recommends locales-all gdebi-core \
                      build-essential debhelper devscripts ipython3 \
                      net-tools fakeroot \
                      vim-nox libpython3.5-dev exuberant-ctags fonts-hack-ttf \
                      python3-flake8 flake8 cmake python3-pytest python3-pytest-cov \
                      python3-setuptools python-setuptools python-all python-all-dev python3-all \
                      htop git psmisc \
                      dh-systemd dh-exec python3-nose python3-coverage python3-mock python3-yaml python3-sqlalchemy \
                      golang gnupg1 haveged \
                      apache2-utils apg python3-jinja2 python3-sphinx python3-sphinx-rtd-theme python3-sphinxcontrib.plantuml \
                      python-setuptools python-all python-all-dev \
                      python3-cryptography python3-aiohttp \
                      python-gitdb python-smmap python3-gitdb python3-smmap \
                      python3-validictory \
                      debootstrap/stretch-backports \
                      nodejs/stretch-backports npm/stretch-backports \
                      jq


