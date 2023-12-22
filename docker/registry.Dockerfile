FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends docker-registry apache2-utils && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir app
WORKDIR /app

ADD docker/registry/config.yml /etc/docker/registry/config.yml

CMD htpasswd -Bbc /etc/docker/registry/.htpasswd $REGISTRY_USER $REGISTRY_PASSWORD && unset REGISTRY_USER REGISTRY_PASSWORD && /usr/bin/docker-registry serve /etc/docker/registry/config.yml
