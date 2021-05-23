#!/bin/sh

if [ -z "$REPOSIGN_EMAIL" ]; then
    REPOSIGN_EMAIL=debsign@molior.info
fi

if [ -z "$REPOSIGN_NAME" ]; then
    REPOSIGN_NAME="Molior Reposign"
fi

create-aptly-keys $REPOSIGN_NAME $REPOSIGN_EMAIL

su - aptly -c "HOME=/var/lib/aptly /usr/bin/aptly api serve -gpg-provider=internal -listen localhost:8001"
