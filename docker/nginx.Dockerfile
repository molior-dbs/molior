FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends nginx-light apache2-utils && apt-get clean && rm -rf /var/lib/apt/lists/*

ADD docker/aptly/create-aptly-passwd /usr/sbin/
ADD docker/aptly/nginx/nginx-conf.d.logging /etc/nginx/conf.d/logging.conf
ADD docker/aptly/nginx/aptly /etc/nginx/sites-available/
ADD docker/aptly/nginx/aptlyapi /etc/nginx/sites-available/
RUN ln -s ../sites-available/aptly /etc/nginx/sites-enabled/
RUN ln -s ../sites-available/aptlyapi /etc/nginx/sites-enabled/

ADD docker/start-nginx /app/nginx

CMD /app/nginx
