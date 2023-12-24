FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*

ARG MOLIOR_APT_REPO
RUN test -n "$MOLIOR_APT_REPO"
RUN echo deb $MOLIOR_APT_REPO stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s $MOLIOR_APT_REPO/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && apt-get install -y --no-install-recommends aptly apg bzip2 xz-utils ca-certificates && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir app
WORKDIR /app

ARG REPOSIGN_NAME
ARG REPOSIGN_EMAIL
CMD /usr/sbin/create-aptly-keys $REPOSIGN_NAME $REPOSIGN_EMAIL && \
    su aptly -c "aptly api serve -listen 0.0.0.0:3142"
