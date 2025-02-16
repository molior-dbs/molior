FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends curl gnupg apg ca-certificates apache2-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN echo deb [signed-by=/etc/apt/keyrings/aptly.asc] http://repo.aptly.info/release bookworm main > /etc/apt/sources.list.d/aptly.list
RUN curl -f https://www.aptly.info/pubkey.txt -o /etc/apt/keyrings/aptly.asc && apt-get update && \
    apt-get install -y --no-install-recommends aptly && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/aptly aptly

ADD docker/prod/start-aptly /usr/local/sbin/start-aptly
ADD pkgdata/molior-aptly/usr/sbin/create-aptly-keys /usr/local/sbin/
CMD ["/usr/local/sbin/start-aptly"]
