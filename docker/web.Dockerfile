FROM debian:bookworm-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends wget nodejs npm
RUN mkdir app
WORKDIR /app

CMD echo "export function MoliorWebVersion() { return \"1.5~dev\"; }" > /app/src/app/lib/version.ts; PATH=node_modules/.bin:$PATH NODE_OPTIONS=--openssl-legacy-provider ng serve --poll=2000 --host 0.0.0.0 --base-href=/ --serve-path=/ --proxy-config docker/ng-serve.proxy.conf.json || cat /tmp/ng-*/angular-errors.log
