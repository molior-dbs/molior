FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg

ARG MOLIOR_APT_SERVER
RUN test -n "$MOLIOR_APT_SERVER"
RUN echo deb $MOLIOR_APT_SERVER/bookworm/12.3/repos/molior/1.5 stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s $MOLIOR_APT_SERVER/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update

RUN mkdir app
WORKDIR /app

RUN apt-get install -y --no-install-recommends aptly apg bzip2 xz-utils

CMD /app/debian/pkgdata/usr/sbin/create-aptly-keys "Molior Reposign" reposign@molior.info && \
    su aptly -c "aptly api serve -listen 0.0.0.0:3142"
