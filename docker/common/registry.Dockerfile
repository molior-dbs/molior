FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends docker-registry apache2-utils && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir app
WORKDIR /app

ADD docker/registry/config.yml /etc/docker/registry/config.yml

ADD docker/start-registry /app/registry

CMD /app/registry
