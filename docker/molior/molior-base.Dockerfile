FROM debian:trixie-slim

COPY debian /work/src/debian
WORKDIR /work/src

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && apt-get install -y --no-install-recommends \
    curl gnupg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN echo deb http://molior.info/1.5-next stable main > /etc/apt/sources.list.d/molior.list && \
    curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor --batch --yes -o /etc/apt/trusted.gpg.d/molior.gpg && \
    apt-get update && \
    export DEBIAN_FRONTEND=noninteractive; apt-get build-dep -y . && \
    apt-get install -y --no-install-recommends \
        dh-autoreconf git-lfs openssh-client python3-psycopg2 sudo expect yq podman uidmap postgresql-client \
        qemu-user-static devscripts bc xz-utils debootstrap && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

