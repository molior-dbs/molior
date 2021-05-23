#!/bin/sh

sed -i -e '/::/d' -e 's/localhost/molior/' /etc/nginx/sites-enabled/molior-web
rm -f /etc/nginx/sites-enabled/default

exec /usr/sbin/nginx
