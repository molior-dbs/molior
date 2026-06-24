FROM debian:trixie-slim

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get install -y --no-install-recommends curl gnupg apg ca-certificates apache2-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN echo deb [signed-by=/etc/apt/keyrings/aptly.asc] http://repo.aptly.info/ci trixie main > /etc/apt/sources.list.d/aptly.list
RUN curl -f https://www.aptly.info/pubkey.txt -o /etc/apt/keyrings/aptly.asc && apt-get update && \
    export DEBIAN_FRONTEND=noninteractive; apt-get install -y --no-install-recommends aptly && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/aptly aptly

ADD scripts/start-aptly /usr/local/sbin/start-aptly
ADD pkgdata/molior-aptly/usr/sbin/create-aptly-keys /usr/local/sbin/
CMD ["/usr/local/sbin/start-aptly"]
