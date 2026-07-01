FROM debian:trixie-slim

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && apt-get install -y --no-install-recommends \
    curl gnupg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 5432 postgres
RUN useradd --uid 5432 --system --home-dir /var/lib/postgresql --no-create-home --shell /bin/bash --gid 5432 --comment "PostgreSQL administrator" postgres

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

ADD docker/molior/start-molior /usr/local/sbin/start-molior

RUN echo deb http://molior.info/1.5-next stable main > /etc/apt/sources.list.d/molior.list && \
    curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor --batch --yes -o /etc/apt/trusted.gpg.d/molior.gpg && \
    apt-get update && \
    export DEBIAN_FRONTEND=noninteractive; apt-get install -y --no-install-recommends \
        molior-server && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /
CMD start-molior
