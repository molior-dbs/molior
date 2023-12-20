FROM debian:bookworm-slim

RUN useradd --uid 5432 --shell /bin/bash --home-dir /var/lib/postgresql postgres
RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN apt-get update && apt-get install -y --no-install-recommends postgresql && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir app
WORKDIR /app

CMD su postgres -c "exec /usr/lib/postgresql/15/bin/postgres -D /var/lib/postgresql/15/main -c config_file=/etc/postgresql/15/main/postgresql.conf"
