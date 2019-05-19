#!/bin/sh

echo
echo "This will wipe the molior database and aptly..."
echo
echo "Are you really sure ?"
echo "Press Ctrl-C to abort..."
echo
read x

sudo -u postgres psql molior -e -c "
delete from sourcerepositoryhook;
delete from hook;
delete from buildtask;
delete from build;
delete from buildorder;
delete from chroot;
delete from projectversionbuildvariant;
delete from buildconfiguration;
delete from buildvariant;
delete from sourcerepositoryprojectversion;
delete from buildorder;
delete from sourcerepository;
delete from projectversionbuildvariant;
delete from projectversiondependency;
delete from projectversion;
delete from userrole;
delete from project;
delete from maintainer;
"

PUBLISH=`wget http://localhost:8000/api/publish -O- -q | jq -r '.[].Prefix + "%" + .[].Distribution'`
SNAPSHOTS=`wget http://localhost:8000/api/snapshots -O- -q | jq -r '.[].Name'`
REPOS=`wget http://localhost:8000/api/repos -O- -q | jq -r '.[].Name'`
MIRRORS=`wget http://localhost:8000/api/mirrors -O- -q | jq -r '.[].Name'`

set -x

sudo service aptly stop
for t in $PUBLISH
do
    distribution=`echo $t | cut -d% -f2`
    prefix=`echo $t | cut -d% -f1`
    sudo -u aptly aptly publish drop $distribution $prefix || true
done
for t in $SNAPSHOTS
do
    sudo -u aptly aptly snapshot drop $t || true
done
for repo in $REPOS
do
    sudo -u aptly aptly snapshot drop $repo || true
    sudo -u aptly aptly repo drop $repo || true
done
for mirror in $MIRRORS
do
    sudo -u aptly aptly mirror drop $mirror || true
done
sudo service aptly start

sudo rm -rf /var/lib/schroot/chroots/*

sudo rm -rf ~molior/repositories/* ~molior/buildout/* ~molior/schroot/* ~molior/debootstrap/*


