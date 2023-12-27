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

ADD docker/molior.yml /etc/molior/
ADD docker/docker-registry.conf /etc/molior/
RUN ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker
RUN rm /etc/molior/mirror-hooks.d/01-create-chroot

CMD echo "Starting api (waiting for postgres 5s)"; sleep 5; \
    groupmod -g `stat -c %g /var/run/docker.sock` docker; \
    sed -i "s#admin_password:.*#admin_password: '$ADMIN_PASSWORD'#" /etc/molior/molior.yml && \
    sed -i "s#api_user:.*#api_user: '$APTLY_USER'#" /etc/molior/molior.yml && \
    sed -i "s#api_pass:.*#api_pass: '$APTLY_PASSWORD'#" /etc/molior/molior.yml && \
    sed -i "s#debsign_gpg_email:.*#debsign_gpg_email: '$DEBSIGN_EMAIL'#" /etc/molior/molior.yml && \
    sed -i "s#gpg_key:.*#gpg_key: '$REPOSIGN_EMAIL'#" /etc/molior/molior.yml && \
    sed -i "s#apt_url_public:.*#apt_url_public: '$APT_URL_PUBLIC'#" /etc/molior/molior.yml && \
    sed -i "s#DOCKER_USER=.*#DOCKER_USER='$REGISTRY_USER'#" /etc/molior/docker-registry.conf && \
    sed -i "s#DOCKER_PASSWORD=.*#DOCKER_PASSWORD='$REGISTRY_PASSWORD'#" /etc/molior/docker-registry.conf && \
    /usr/sbin/create-molior-keys $DEBSIGN_NAME $DEBSIGN_EMAIL && \
    /usr/lib/molior/db-upgrade.sh && \
    su molior -c "/usr/bin/python3 -m molior.main --host=0.0.0.0 --port=9999"
