.EXPORT_ALL_VARIABLES:
.PHONY: MAKECMDGOALS

dev: COMPOSE_FILE = docker-compose-dev.yml
dev:  ## run development containers
	@docker-compose build
	@docker-compose up -d

build: COMPOSE_FILE = docker-compose.yml
build:  ## run development containers
	@docker-compose build

start-prod:  ## run containers (background)
	@docker-compose --profile serve up -d

# Self-documenting Makefile
# https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

api: COMPOSE_FILE = docker-compose-build.yml
api:
	docker-compose build --no-cache api

api-cached: COMPOSE_FILE = docker-compose-build.yml
api-cached:
	docker-compose build --build-arg api

web: COMPOSE_FILE = docker-compose-build.yml
web:
	docker-compose build --no-cache web

web-cached: COMPOSE_FILE = docker-compose-build.yml
web-cached:
	docker-compose build web

aptly: COMPOSE_FILE = docker-compose-build.yml
aptly:
	docker-compose build --no-cache aptly

aptly-cached: COMPOSE_FILE = docker-compose-build.yml
aptly-cached:
	docker-compose build aptly

postgres:
	docker-compose build --no-cache postgres

nginx: COMPOSE_FILE = docker-compose-build.yml
nginx:
	docker-compose build --no-cache nginx

nginx-cached: COMPOSE_FILE = docker-compose-build.yml
nginx-cached:
	docker-compose build nginx

registry: COMPOSE_FILE = docker-compose-build.yml
registry:
	docker-compose build --no-cache registry

stop:  ## stop containers
	@docker-compose --profile serve --profile test down

stop-api:  ## stop api container
	@docker-compose stop api

stop-aptly:  ## stop aptly container
	@docker-compose stop aptly

stop-nginx:  ## stop nginx container
	@docker-compose stop nginx

stop-web:  ## stop web container
	@docker-compose stop web

stop-registry:  ## stop registry container
	@docker-compose stop registry

run-aptly: stop-aptly
	docker run -it -v $(CWD)/../aptly:/app -v molior_aptly:/var/lib/aptly/ molior_aptly /bin/bash

clean:  ## clean containers and volumes
	@echo; echo "This will delete volumes and data!"; echo Press Enter to continue, Ctrl-C to abort ...; read x
	docker-compose --profile serve --profile test down -v

remove: clean   ## remove containers and volumes
	docker rmi -f molior_web:latest molior_api:latest molior_postgres:latest molior_aptly:latest molior_nginx:latest molior_registry:latest

logs:  ## show logs
	@docker-compose logs -f api postgres web aptly nginx

logs-api:  ## show api logs
	@docker-compose logs -f api

logs-aptly:  ## show aptly logs
	@docker-compose logs -f aptly

logs-registry:  ## show registry logs
	@docker-compose logs -f registry

logs-web:  ## show web logs
	@docker-compose logs -f web

logs-nginx:  ## show nginx logs
	@docker-compose logs -f nginx

logs-postgres:  ## show postgres logs
	@docker-compose logs -f postgres

shell-api:  ## login to api container
	docker-compose exec api /bin/bash

shell-web:  ## login to web container
	docker-compose exec web /bin/bash

shell-postgres:  ## login to postgres container
	docker-compose exec postgres /bin/bash

shell-aptly:  ## login to aptly container
	docker-compose exec aptly /bin/bash

shell-nginx:  ## login to nginx container
	docker-compose exec nginx /bin/bash

shell-registry:  ## login to registry container
	docker-compose exec registry /bin/bash

psql:  ## login to api container
	docker-compose exec postgres su postgres -c "psql molior"

docker-push:
	for i in web api aptly nginx postgres registry; do docker tag molior_$$i neolynx/molior_$$i; done
	for i in web api aptly nginx postgres registry; do docker push neolynx/molior_$$i; done
