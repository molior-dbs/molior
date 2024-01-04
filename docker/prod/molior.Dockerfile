FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN adduser --uid 5432 --system --home /var/lib/postgresql --no-create-home --shell /bin/bash --group --gecos "PostgreSQL administrator" postgres

RUN mkdir app
WORKDIR /app

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN echo deb http://molior.info/1.5 stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get install -y --no-install-recommends molior-server docker.io && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN usermod -G docker molior

ADD docker/start-molior /app/molior

RUN ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker
RUN rm /etc/molior/mirror-hooks.d/01-create-chroot

CMD /app/molior
