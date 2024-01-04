FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends nginx-light apache2-utils && apt-get clean && rm -rf /var/lib/apt/lists/*

ADD pkgdata/molior-aptly/usr/sbin/create-aptly-passwd /usr/sbin/

ADD docker/common/nginx-conf.d.logging /etc/nginx/conf.d/logging.conf
ADD docker/common/nginx-aptly /etc/nginx/sites-available/aptly
ADD docker/common/nginx-aptlyapi /etc/nginx/sites-available/aptlyapi
RUN ln -s ../sites-available/aptly /etc/nginx/sites-enabled/
RUN ln -s ../sites-available/aptlyapi /etc/nginx/sites-enabled/

ADD docker/common/start-nginx /app/nginx

CMD /app/nginx
