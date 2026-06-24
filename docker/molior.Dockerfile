# Build debian package
FROM debian:trixie-slim as build

COPY . /work/src
WORKDIR /work/src

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && apt-get install -y --no-install-recommends curl gnupg && \
    echo deb http://molior.info/1.5-next stable main > /etc/apt/sources.list.d/molior.list && \
    curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get build-dep -y . && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN dpkg-buildpackage -us -uc -b


# Dev Image
FROM debian:trixie-slim

RUN groupadd --system --gid 5432 postgres
RUN useradd --uid 5432 --system --home-dir /var/lib/postgresql --no-create-home --shell /bin/bash --gid 5432 --comment "PostgreSQL administrator" postgres

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

COPY --from=build /work/*.deb /tmp/

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && apt-get install -y --no-install-recommends curl gnupg && \
    echo deb http://molior.info/1.5-next stable main > /etc/apt/sources.list.d/molior.list && \
    curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    export DEBIAN_FRONTEND=noninteractive; apt-get install -y --no-install-recommends podman uidmap python3-kubernetes /tmp/molior-server*deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN rm -f /tmp/*.deb

ADD scripts/start-molior /usr/local/sbin/start-molior
RUN ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker
RUN rm /etc/molior/mirror-hooks.d/01-create-chroot

CMD ["start-molior"]
