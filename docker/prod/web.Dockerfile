FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir app
WORKDIR /app

RUN echo deb http://molior.info/1.5 stable main > /etc/apt/sources.list.d/molior.list
RUN curl -s http://molior.info/1.5/archive-keyring.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/molior.gpg && apt-get update && \
    apt-get install -y --no-install-recommends molior-web && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ADD nginx-molior-web /etc/nginx/sites-enabled/molior-web

CMD nginx -g 'daemon off;'
