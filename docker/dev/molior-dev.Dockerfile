FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN adduser --uid 5432 --system --home /var/lib/postgresql --no-create-home --shell /bin/bash --group --gecos "PostgreSQL administrator" postgres

RUN mkdir app
WORKDIR /app

RUN echo deb http://molior.info/1.5 stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get install -y --no-install-recommends devscripts postgresql-client-15 bc python3-aiohttp-devtools python3-pygments python3-devtools python3-watchfiles dh-python dh-exec python3-setuptools python3-yaml python3-sqlalchemy python3-jinja2 python3-cirrina python3-launchy python3-tz python3-giturlparse python3-aiofile python3-psutil python3-dateutil python3-async-cron python3-click python3-psycopg2 debootstrap git git-lfs xz-utils sudo docker.io openssh-client qemu-user-static expect && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 7777 -G docker -m --shell /bin/sh --home-dir /var/lib/molior molior

CMD [ "/app/docker/dev/start-molior" ]
