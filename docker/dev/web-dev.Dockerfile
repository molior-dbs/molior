FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends wget nodejs npm dpkg-dev && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir app
WORKDIR /app

ADD docker/dev/ng-serve.proxy.conf.json /etc/

CMD echo "export function MoliorWebVersion() { return \"`dpkg-parsechangelog -S Version`\"; }" > /app/src/app/lib/version.ts; PATH=node_modules/.bin:$PATH NODE_OPTIONS=--openssl-legacy-provider ng serve --poll=2000 --host 0.0.0.0 --base-href=/ --serve-path=/ --proxy-config /etc/ng-serve.proxy.conf.json --disable-host-check || cat /tmp/ng-*/angular-errors.log
