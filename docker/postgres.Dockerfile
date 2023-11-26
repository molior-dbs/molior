FROM debian:bookworm-slim

RUN apt-get update

RUN adduser --uid 5432 --system --home /var/lib/postgresql --no-create-home --shell /bin/bash --group --gecos "PostgreSQL administrator" postgres

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN apt-get install -y --no-install-recommends postgresql

RUN mkdir app
WORKDIR /app

CMD su postgres -c "exec /usr/lib/postgresql/15/bin/postgres -D /var/lib/postgresql/15/main -c config_file=/etc/postgresql/15/main/postgresql.conf"
