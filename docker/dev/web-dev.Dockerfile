FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends wget nodejs npm dpkg-dev && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir app
WORKDIR /app

ADD docker/dev/ng-serve.proxy.conf.json /etc/

CMD [ "/molior/docker/dev/start-web" ]
