help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

start:  ## run development containers
	@docker-compose up -d

dev:  ## rebuild and run development containers
	@docker-compose build --no-cache
	@docker-compose up -d

dev-cached:  ## build (cached) and run development containers
	@docker-compose build
	@docker-compose up -d


prod-build:  ## Build prod containers
	@docker-compose -f docker/prod/docker-compose-build.yml build --no-cache

prod-build-cached:  ## Build prod containers (cached)
	@docker-compose -f docker/prod/docker-compose-build.yml build

prod-molior:  ## Build prod molior
	@docker-compose -f docker/prod/docker-compose-build.yml build --no-cache molior

prod-aptly:  ## Build prod aptly
	@docker-compose -f docker/prod/docker-compose-build.yml build --no-cache aptly

prod-web:  ## Build prod web
	@docker-compose -f docker/prod/docker-compose-build.yml build --no-cache web

prod-publish-molior:  ## Publish docker molior
	@docker tag molior_molior neolynx/molior_molior-`dpkg-architecture -q DEB_BUILD_ARCH`
	@docker push neolynx/molior_molior-`dpkg-architecture -q DEB_BUILD_ARCH`
	@docker rmi neolynx/molior_molior-`dpkg-architecture -q DEB_BUILD_ARCH`

prod-publish-aptly:  ## Publish docker aptly
	@docker tag molior_aptly neolynx/molior_aptly-`dpkg-architecture -q DEB_BUILD_ARCH`
	@docker push neolynx/molior_aptly-`dpkg-architecture -q DEB_BUILD_ARCH`
	@docker rmi neolynx/molior_aptly-`dpkg-architecture -q DEB_BUILD_ARCH`

prod-publish-web:  ## Publish docker molior
	@docker tag molior_web neolynx/molior_web-`dpkg-architecture -q DEB_BUILD_ARCH`
	@docker push neolynx/molior_web-`dpkg-architecture -q DEB_BUILD_ARCH`
	@docker rmi neolynx/molior_web-`dpkg-architecture -q DEB_BUILD_ARCH`

prod-publish:  ## Publish docker images
	@for i in molior web aptly nginx postgres registry; do docker tag molior_$$i neolynx/molior_$$i-`dpkg-architecture -q DEB_BUILD_ARCH`; done
	@for i in molior web aptly nginx postgres registry; do echo "\033[01;34mPushing $$i ...\033[00m"; docker push neolynx/molior_$$i-`dpkg-architecture -q DEB_BUILD_ARCH`; docker rmi neolynx/molior_$$i-`dpkg-architecture -q DEB_BUILD_ARCH`; done

prod-publish-manifest:
	@for i in molior web aptly nginx postgres registry; do echo "\033[01;34mPushing Manifest $$i ...\033[00m"; docker manifest rm neolynx/molior_$$i; docker manifest create neolynx/molior_$$i neolynx/molior_$$i-amd64 neolynx/molior_$$i-arm64; docker manifest push neolynx/molior_$$i; done

molior:
	docker-compose build --no-cache molior

molior-cached:
	docker-compose build molior

web:
	docker-compose build --no-cache web

web-cached:
	docker-compose build web

aptly:
	docker-compose build --no-cache aptly

aptly-cached:
	docker-compose build aptly

postgres:
	docker-compose build --no-cache postgres

nginx:
	docker-compose build --no-cache nginx

nginx-cached:
	docker-compose build nginx

registry:
	docker-compose build --no-cache registry

run-aptly-cmds:  ## run aptly commands
	@docker-compose stop aptly
	@docker-compose run aptly su aptly -c bash

stop:  ## stop containers
	@docker-compose down

stop-molior:  ## stop molior container
	@docker-compose stop molior

stop-aptly:  ## stop aptly container
	@docker-compose stop aptly

stop-nginx:  ## stop nginx container
	@docker-compose stop nginx

stop-web:  ## stop web container
	@docker-compose stop web

stop-registry:  ## stop registry container
	@docker-compose stop registry

clean:  ## clean containers and volumes
	@echo; echo "This will delete volumes and data!"; echo Press Enter to continue, Ctrl-C to abort ...; read x
	docker-compose down -v

remove: clean   ## remove containers and volumes
	docker rmi -f molior_web:latest molior_molior:latest molior_postgres:latest molior_aptly:latest molior_nginx:latest molior_registry:latest

# Logging: ##
logs:  ## show logs of molior, web and aptly
	@docker-compose logs -f --tail 20 molior web aptly

logs-all:  ## show all logs
	@docker-compose logs -f --tail 20 molior web aptly registry nginx postgres

logs-molior:  ## show molior logs
	@docker-compose logs -f --tail 20 molior

logs-aptly:  ## show aptly logs
	@docker-compose logs -f --tail 20 aptly

logs-registry:  ## show registry logs
	@docker-compose logs -f --tail 20 registry

logs-web:  ## show web logs
	@docker-compose logs -f --tail 20 web

logs-nginx:  ## show nginx logs
	@docker-compose logs -f --tail 20 nginx

logs-postgres:  ## show postgres logs
	@docker-compose logs -f --tail 20 postgres

shell-molior:  ## login to molior container
	docker-compose exec molior /bin/bash

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

psql:  ## run psql
	docker-compose exec postgres su postgres -c "psql molior"

docker-compose.tar:
	d=`mktemp -d tmp-XXXXX`; cp -ar docker/example $$d/molior; tar -C $$d/ -cvf docker-compose.tar molior/; rm -rf $$d/; echo Created: docker-compose.tar

restore-backup:
	@test -n "${backup}" || (echo Usage: make restore backup=path/to/db.tar; exit 1)
	@test -f "${backup}" || (echo Error: file not found: ${backup}; exit 1)
	@docker-compose stop molior
	zcat "${backup}" | docker-compose exec -T postgres su postgres -c "dropdb molior && psql"
	@docker-compose start molior

.PHONY: help molior
