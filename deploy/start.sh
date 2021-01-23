#!/bin/sh
set -e

sleep 60

create-molior-keys "Molior Debsign" debsign@molior.info
create-aptly-keys "Molior Reposign" reposign@molior.info
create-aptly-passwd molior molior-dev
su molior -c "gpg1 --armor --export debsign@molior.info | gpg1 --import --no-default-keyring --keyring=trustedkeys.gpg"

/usr/lib/molior/db-upgrade.sh
su molior -c "/usr/bin/python3 -m molior.molior.server --host=localhost --port=8888"
