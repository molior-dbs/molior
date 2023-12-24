FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN adduser --uid 5432 --system --home /var/lib/postgresql --no-create-home --shell /bin/bash --group --gecos "PostgreSQL administrator" postgres
ARG DOCKER_GROUP_ID
RUN addgroup --gid $DOCKER_GROUP_ID --system docker
RUN useradd --uid 7777 -G docker -m --shell /bin/sh --home-dir /var/lib/molior molior

RUN mkdir app
WORKDIR /app

ARG MOLIOR_APT_REPO
RUN test -n "$MOLIOR_APT_REPO"
RUN echo deb $MOLIOR_APT_REPO stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s $MOLIOR_APT_REPO/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get install -y --no-install-recommends molior-server docker.io && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ADD docker/molior.yml /etc/molior/
ADD docker/docker-registry.conf /etc/molior/
RUN ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker
RUN rm /etc/molior/mirror-hooks.d/01-create-chroot

ARG MOLIOR_ADMIN_PASSWD
ARG DEBSIGN_NAME
ARG DEBSIGN_EMAIL
CMD echo "Starting api (waiting for postgres 5s)"; sleep 5; \
        sed -i 's/admin-password:.*/admin-password: $MOLIOR_ADMIN_PASSWD/' /etc/molior/molior.yml && \
        /usr/sbin/create-molior-keys $DEBSIGN_NAME $DEBSIGN_EMAIL && \
        /usr/lib/molior/db-upgrade.sh && \
        su molior -c "/usr/bin/python3 -m molior.main --host=0.0.0.0 --port=9999"
