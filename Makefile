dev:  ## build and run development containers
	@docker-compose build --no-cache
	@docker-compose up -d

dev-cached:  ## Build (cached) and run development containers
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
	@docker tag molior_molior neolynx/molior_molior
	@docker push neolynx/molior_molior
	@docker rmi neolynx/molior_molior

prod-publish-aptly:  ## Publish docker aptly
	@docker tag molior_aptly neolynx/molior_aptly
	@docker push neolynx/molior_aptly
	@docker rmi neolynx/molior_aptly

prod-publish-web:  ## Publish docker molior
	@docker tag molior_web neolynx/molior_web
	@docker push neolynx/molior_web
	@docker rmi neolynx/molior_web

prod-publish:  ## Publish docker images
	@for i in molior web aptly nginx postgres registry; do docker tag molior_$$i neolynx/molior_$$i; done
	@for i in molior web aptly nginx postgres registry; do echo "\033[01;34mPushing $$i ...\033[00m"; docker push neolynx/molior_$$i; docker rmi neolynx/molior_$$i; done

# Self-documenting Makefile
# https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

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
	docker-compose test down -v

remove: clean   ## remove containers and volumes
	docker rmi -f molior_web:latest molior_molior:latest molior_postgres:latest molior_aptly:latest molior_nginx:latest molior_registry:latest

logs:  ## show logs
	@docker-compose logs -f molior web aptly

logs-molior:  ## show molior logs
	@docker-compose logs -f molior

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
