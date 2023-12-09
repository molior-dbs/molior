FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg

RUN echo deb http://debian.roche.com/bookworm/12.0/repos/molior/1.5-bookworm stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://debian.roche.com/repo.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update

RUN adduser --uid 5432 --system --home /var/lib/postgresql --no-create-home --shell /bin/bash --group --gecos "PostgreSQL administrator" postgres

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN mkdir app
WORKDIR /app

RUN apt-get install -y --no-install-recommends devscripts postgresql-client-15 bc python3-aiohttp-devtools python3-pygments python3-devtools python3-watchfiles dh-python dh-exec python3-setuptools python3-yaml python3-sqlalchemy python3-jinja2 python3-cirrina python3-launchy python3-tz python3-giturlparse python3-aiofile python3-psutil python3-dateutil python3-async-cron python3-click python3-psycopg2 debootstrap git git-lfs xz-utils sudo docker.io

CMD echo "Starting api (waiting for postgres 5s)"; sleep 5; echo MOLIOR_VERSION = \"`dpkg-parsechangelog -S Version`\" > molior/version.py; mkdir -p /etc/molior; cp -ar /app/docker/molior.yml /etc/molior; \
        cp /app/docker/docker-registry.conf /etc/molior/; \
        cp /app/pkgdata/molior-server/etc/sudoers.d/01_molior /etc/sudoers.d/; \
        mkdir -p /etc/molior/mirror-hooks.d; \
        ln -s /usr/lib/molior/create-chroot.sh /etc/molior/mirror-hooks.d/01-create-chroot; \
        ln -s /usr/lib/molior/create-debootstrap.sh /etc/molior/mirror-hooks.d/02-create-debootstrap; \
        ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker; \
        mkdir -p /var/lib/molior/debootstrap/; \
        cp -ar /app/pkgdata/molior-server/usr/lib/* /usr/lib/; ./pkgdata/molior-server/usr/lib/molior/db-upgrade.sh ./pkgdata/molior-server/usr/share/molior/database && \
        su molior -c "exec adev runserver -p 9999 molior/"
