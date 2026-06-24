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

# Dev image
FROM debian:trixie-slim

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && apt-get install -y --no-install-recommends curl gnupg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=build /work/*.deb /tmp/
RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y --no-install-recommends /tmp/molior-web_*.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN rm -f /tmp/*.deb

ADD scripts/nginx-molior-web /etc/nginx/sites-enabled/molior-web

STOPSIGNAL SIGQUIT

CMD ["nginx", "-g", "daemon off;"]
