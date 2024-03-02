FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN echo deb http://deb.debian.org/debian bookworm-backports main > /etc/apt/sources.list.d/backports.list
RUN echo deb http://molior.info/1.5 stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get install -y --no-install-recommends apg bzip2 xz-utils ca-certificates golang/bookworm-backports golang-go/bookworm-backports golang-doc/bookworm-backports golang-src/bookworm-backports make git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -m --shell /bin/sh --home-dir /var/lib/aptly aptly

RUN mkdir app
WORKDIR /app

ADD pkgdata/molior-aptly/usr/sbin/create-aptly-keys /usr/sbin/

RUN GOPATH=/usr/local go install github.com/cosmtrek/air@latest

CMD usermod -o -u `stat -c %u /app` aptly; \
    chown -R `stat -c %u /app` /var/lib/aptly; \
    /usr/sbin/create-aptly-keys $REPOSIGN_NAME $REPOSIGN_EMAIL && \
    su aptly -c "air -build.pre_cmd \"go mod tidy; go generate\" -build.exclude_dir system -build.exclude_dir debian -- api serve -listen 0.0.0.0:3142"
