#!/bin/sh

if [ -z "$APTLY_USER" ]; then
    APTLY_USER=molior
fi

if [ -z "$APTLY_PASS" ]; then
    APTLY_PASS=molior-dev
fi

create-aptly-passwd $APTLY_USER $APTLY_PASS
sed -i 's/80/3142/' /etc/nginx/sites-enabled/aptly
sed -i -e 's/8000/8001/' /etc/nginx/sites-enabled/aptlyapi
rm -f /etc/nginx/sites-enabled/default

exec /usr/sbin/nginx
