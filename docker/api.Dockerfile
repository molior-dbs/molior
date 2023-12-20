FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg

ARG MOLIOR_APT_REPO
RUN test -n "$MOLIOR_APT_REPO"
RUN echo deb $MOLIOR_APT_REPO stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s $MOLIOR_APT_REPO/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update

RUN adduser --uid 5432 --system --home /var/lib/postgresql --no-create-home --shell /bin/bash --group --gecos "PostgreSQL administrator" postgres

ARG DOCKER_GROUP_ID
RUN addgroup --gid $DOCKER_GROUP_ID --system docker

RUN useradd --uid 7777 -G docker -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN mkdir app
WORKDIR /app

RUN apt-get install -y --no-install-recommends devscripts postgresql-client-15 bc python3-aiohttp-devtools python3-pygments python3-devtools python3-watchfiles dh-python dh-exec python3-setuptools python3-yaml python3-sqlalchemy python3-jinja2 python3-cirrina python3-launchy python3-tz python3-giturlparse python3-aiofile python3-psutil python3-dateutil python3-async-cron python3-click python3-psycopg2 debootstrap git git-lfs xz-utils sudo docker.io openssh-client

CMD echo "Starting api (waiting for postgres 5s)"; sleep 5; echo MOLIOR_VERSION = \"`dpkg-parsechangelog -S Version`\" > molior/version.py; mkdir -p /etc/molior; cp -ar /app/docker/molior.yml /etc/molior; \
        /app/pkgdata/molior-server/usr/sbin/create-molior-keys "Molior Debsign" debsign@molior.info;\
        cp /app/docker/docker-registry.conf /etc/molior/; \
        cp /app/pkgdata/molior-server/etc/sudoers.d/01_molior /etc/sudoers.d/; \
        mkdir -p /etc/molior/mirror-hooks.d; \
        ln -sf /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker; \
        mkdir -p /var/lib/molior/debootstrap/; \
        mkdir -p /var/lib/molior/repositories/; \
        chown molior /var/lib/molior/repositories/; \
        mkdir -p /var/lib/molior/upload/; \
        chown molior /var/lib/molior/upload/; \
        cp -ar /app/pkgdata/molior-server/usr/lib/* /usr/lib/; ./pkgdata/molior-server/usr/lib/molior/db-upgrade.sh ./pkgdata/molior-server/usr/share/molior/database && \
        su molior -c "exec adev runserver -p 9999 molior/"
