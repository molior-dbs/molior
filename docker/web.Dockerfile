FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl nodejs npm gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir app
WORKDIR /app

ARG MOLIOR_APT_REPO
RUN test -n "$MOLIOR_APT_REPO"
RUN echo deb $MOLIOR_APT_REPO stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s $MOLIOR_APT_REPO/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get install -y --no-install-recommends molior-web && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ADD docker/web/nginx/molior-web /etc/nginx/sites-enabled/

CMD nginx -g 'daemon off;'
