FROM debian:bookworm-slim

RUN mkdir app
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends docker-registry apache2-utils

COPY docker/registry/config.yml /etc/docker/registry/config.yml

CMD htpasswd -Bbc /etc/docker/registry/.htpasswd ${USER} ${PASSWORD} && /usr/bin/docker-registry serve /etc/docker/registry/config.yml
