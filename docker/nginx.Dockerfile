FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends nginx-light

RUN mkdir app
WORKDIR /app

CMD cp -ar /app/debian/pkgdata/* /; rm -f /etc/nginx/sites-enabled/default; ln -s ../sites-available/aptly /etc/nginx/sites-enabled/; ln -s ../sites-available/aptlyapi /etc/nginx/sites-enabled/; nginx -g 'daemon off;'
