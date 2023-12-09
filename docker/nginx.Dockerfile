FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends nginx-light apache2-utils

RUN mkdir app
WORKDIR /app

CMD rm -f /etc/nginx/sites-enabled/default; \
    cp /app/docker/nginx/aptly /etc/nginx/sites-available/; \
    cp /app/docker/nginx/aptlyapi /etc/nginx/sites-available/; \
    cp /app/docker/nginx/nginx-conf.d.logging /etc/nginx/conf.d/logging.conf; \
    /app/debian/pkgdata/usr/sbin/create-aptly-passwd molior molior-dev && \
    ln -s ../sites-available/aptly /etc/nginx/sites-enabled/; ln -s ../sites-available/aptlyapi /etc/nginx/sites-enabled/; nginx -g 'daemon off;'
