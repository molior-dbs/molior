FROM debian:trixie-slim

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get full-upgrade -y && apt-get install -y --no-install-recommends \
        nginx-light apache2-utils \
        && apt-get clean && rm -rf /var/lib/apt/lists/*

ADD pkgdata/molior-aptly/usr/sbin/create-aptly-passwd /usr/sbin/

ADD docker/aptly/nginx-conf.d.logging /etc/nginx/conf.d/logging.conf
ADD docker/aptly/nginx-aptly /etc/nginx/sites-available/aptly
ADD docker/aptly/nginx-aptlyapi.tpl /etc/nginx/sites-available/aptlyapi.tpl
RUN ln -s ../sites-available/aptly /etc/nginx/sites-enabled/
RUN ln -s ../sites-available/aptlyapi /etc/nginx/sites-enabled/
RUN rm -f /etc/nginx/sites-enabled/default

ADD docker/aptly/start-nginx /usr/local/sbin/start-nginx

STOPSIGNAL SIGQUIT

CMD start-nginx
