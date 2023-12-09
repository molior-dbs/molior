FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg

RUN echo deb http://debian.roche.com/bookworm/12.0/repos/molior/1.5-bookworm stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://debian.roche.com/repo.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update

RUN mkdir app
WORKDIR /app

RUN apt-get install -y --no-install-recommends docker-registry apache2-utils

COPY docker/registry/config.yml /etc/docker/registry/config.yml

CMD htpasswd -Bbc /etc/docker/registry/.htpasswd ${USER} ${PASSWORD} && /usr/bin/docker-registry serve /etc/docker/registry/config.yml
