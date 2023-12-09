FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg

RUN echo deb http://debian.roche.com/bookworm/12.0/repos/molior/1.5-bookworm stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://debian.roche.com/repo.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update

RUN mkdir app
WORKDIR /app

RUN apt-get install -y --no-install-recommends aptly apg

CMD /app/debian/pkgdata/usr/sbin/create-aptly-keys "Molior Reposign" reposign@molior.info && \
    su aptly -c "aptly api serve -listen 0.0.0.0:3142"
