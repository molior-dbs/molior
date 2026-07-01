FROM debian:trixie-slim

RUN useradd --uid 5432 --shell /bin/bash --home-dir /var/lib/postgresql postgres
RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && apt-get install -y --no-install-recommends \
       postgresql \
   && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY docker/molior/start-postgres /usr/local/bin/
CMD start-postgres
