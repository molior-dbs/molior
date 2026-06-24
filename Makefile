NAMESPACE := molior

export HELM_NAMESPACE=$(NAMESPACE)

help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

docker-images: docker-molior docker-web docker-aptly  ## Create docker images
	docker build -f docker/common/postgres.Dockerfile -t molior-postgres:dev .
	docker build -f docker/common/nginx.Dockerfile -t molior-nginx:dev .

docker-molior:
	@docker inspect molior-base:dev >/dev/null 2>&1 || (echo Building base docker image...; \
		docker build -f docker/molior-base.Dockerfile -t molior-base:dev .)
	docker build -f docker/molior.Dockerfile -t molior:dev .

docker-web:
	docker build -f docker/web.Dockerfile -t molior-web:dev ../molior-web2

docker-aptly:
	docker build -f docker/aptly.Dockerfile -t aptly:dev .

create-cluster:  ## Create k3d cluster
	k3d cluster create molior \
		--registry-create molior-registry:0.0.0.0:5000 \
		--port "8000:30080@server:0" \
		--port "8080:30088@server:0" \
		--k3s-arg "--disable=traefik@server:0" \
		--k3s-arg "--disable=metrics-server@server:0"
	kubectl config set-context --current --namespace=$(NAMESPACE)

delete-cluster:  ## Delete k3d cluster
	k3d cluster delete molior

deploy-cluster:  deploy-image-molior deploy-image-molior-nginx deploy-image-molior-postgres deploy-image-molior-web  ## Import local images into k3d

deploy-image-%:  ## Import a local <image>:dev into k3d (e.g. make deploy-image-molior)
	docker tag $*:dev localhost:5000/$*:dev
	docker push localhost:5000/$*:dev
	docker rmi localhost:5000/$*:dev

install-k3d:
	@if ! which k3d 2>/dev/null; then echo Downloading https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64 to ~/.local/bin/k3d; \
		mkdir -p ~/.local/bin; \
		curl -fL -o ~/.local/bin/k3d https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64; \
		chmod +x ~/.local/bin/k3d; \
		echo ${PATH} | grep -q ${HOME}/.local/bin || echo Please add ~/.local/bin to the PATH; \
	fi



install-cluster:
	helm install --create-namespace molior charts/
	sleep 2

uninstall-cluster:
	helm uninstall --wait molior || true

reinstall-cluster: uninstall-cluster install-cluster

redeploy-cluster: uninstall-cluster deploy-cluster install-cluster watch

list:
	kubectl get pods

watch:
	watch kubectl get pods

logs-molior:
	kubectl logs -l app=molior -f

logs-aptly:
	kubectl logs -l molior.service=aptly -f


restart-molior:
	kubectl delete pod -l app=molior

psql:  ## run psql
	kubectl exec -it molior-6c76b45685-ktsqv -- su molior -c psql molior















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


prod-publish-manifest:
	@for i in molior web aptly nginx postgres registry; do echo "\033[01;34mPushing Manifest $$i ...\033[00m"; docker manifest rm neolynx/molior_$$i; docker manifest create neolynx/molior_$$i neolynx/molior_$$i-amd64 neolynx/molior_$$i-arm64; docker manifest push neolynx/molior_$$i; done

run-aptly-cmds:  ## run aptly commands
	@docker-compose stop aptly
	@docker-compose run aptly su aptly -c bash

remove: clean   ## remove containers and volumes
	docker rmi -f molior_web:latest molior_molior:latest molior_postgres:latest molior_aptly:latest molior_nginx:latest molior_registry:latest

docker-compose.tar:
	d=`mktemp -d tmp-XXXXX`; cp -ar docker/example $$d/molior; tar -C $$d/ -cvf docker-compose.tar molior/; rm -rf $$d/; echo Created: docker-compose.tar

restore-backup:
	@test -n "${backup}" || (echo Usage: make restore backup=path/to/db.tar; exit 1)
	@test -f "${backup}" || (echo Error: file not found: ${backup}; exit 1)
	@docker-compose stop molior
	zcat "${backup}" | docker-compose exec -T postgres su postgres -c "dropdb molior && psql"
	@docker-compose start molior

.PHONY: help
