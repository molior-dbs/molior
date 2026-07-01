REGISTRY := k3d-molior-registry
REGISTRY_PORT := 5000
MOLIOR_DEV ?= true
PUSH_REGISTRY ?= localhost:$(REGISTRY_PORT)
MOLIOR_VERSION ?= dev

NAMESPACE := molior
export HELM_NAMESPACE=$(NAMESPACE)

ifneq ($(shell which podman 2>/dev/null),)
  DOCKERCMD := podman
  PODMAN_K3D_REGISTRY_ARGS := --default-network podman
else ifneq ($(shell which docker 2>/dev/null),)
  DOCKERCMD := docker
else
  $(error Neither podman nor docker found in PATH)
endif

help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

docker-images: docker-images-molior docker-images-aptly  ## Create docker images

docker-images-molior:  ## Build molior docker images (moior, postgres)
	@$(DOCKERCMD) inspect molior-base:dev >/dev/null 2>&1 || (echo Building base docker image...; \
		$(DOCKERCMD) build -f docker/molior/molior-base.Dockerfile -t molior-base:dev .)
	$(DOCKERCMD) build -f docker/molior/molior-dev.Dockerfile -t molior:dev .
	$(DOCKERCMD) build -f docker/molior/postgres.Dockerfile -t molior-postgres:dev .

docker-images-aptly:  ## Build aptly docker images (aptly, nginx)
	$(DOCKERCMD) build -f docker/aptly/aptly.Dockerfile -t aptly:dev .
	$(DOCKERCMD) build -f docker/aptly/nginx.Dockerfile -t molior-nginx:dev .

docker-images-prod:
	$(DOCKERCMD) build --no-cache -f docker/aptly/aptly.Dockerfile -t aptly:prod .
	$(DOCKERCMD) build --no-cache -f docker/aptly/nginx.Dockerfile -t molior-nginx:prod .
	$(DOCKERCMD) build --no-cache -f docker/molior/postgres.Dockerfile -t molior-postgres:prod .
	$(DOCKERCMD) build --no-cache -f docker/molior/molior.Dockerfile -t molior:prod .

docker-shell:  ## Start a shell in a new molior container
	$(DOCKERCMD) run -it --rm -v $(PWD):/work/src molior:dev bash

create-cluster:  ## Create k3d cluster
	k3d registry list molior-registry >/dev/null 2>&1 || k3d registry create molior-registry --port 0.0.0.0:$(REGISTRY_PORT) $(PODMAN_K3D_REGISTRY_ARGS)
	k3d cluster create molior \
		--registry-use $(REGISTRY):$(REGISTRY_PORT) \
		--port "8000:30080@server:0" \
		--port "8080:30088@server:0" \
		--k3s-arg "--disable=traefik@server:0" \
		--k3s-arg "--disable=metrics-server@server:0"
	kubectl config set-context --current --namespace=$(NAMESPACE)

delete-cluster:  ## Delete k3d cluster
	k3d cluster delete molior

deploy-cluster:  deploy-image-molior deploy-image-molior-nginx deploy-image-molior-postgres deploy-image-aptly  ## Import local images into k3d

deploy-image-%:  ## Import a local <image>:dev into k3d (e.g. make deploy-image-molior)
	$(DOCKERCMD) tag $*:$(MOLIOR_VERSION) $(PUSH_REGISTRY)/$*:$(MOLIOR_VERSION)
	$(DOCKERCMD) push $(PUSH_REGISTRY)/$*:$(MOLIOR_VERSION)
	$(DOCKERCMD) rmi $(PUSH_REGISTRY)/$*:$(MOLIOR_VERSION)

install-k3d:  ## Download and install k3d binary
	@if ! which k3d 2>/dev/null; then echo Downloading https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64 to ~/.local/bin/k3d; \
		mkdir -p ~/.local/bin; \
		curl -fL -o ~/.local/bin/k3d https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64; \
		chmod +x ~/.local/bin/k3d; \
		echo ${PATH} | grep -q ${HOME}/.local/bin || echo Please add ~/.local/bin to the PATH; \
	fi



install-cluster:  ## Install molior dev into cluster
	printf 'registry:\n  host: %s\n  port: %s\nmolior:\n  dev: %s\n' $(REGISTRY) $(REGISTRY_PORT) $(MOLIOR_DEV) > /tmp/molior-registry-values.yaml
	helm install --create-namespace molior charts/ -f /tmp/molior-registry-values.yaml; rm -f /tmp/molior-registry-values.yaml

uninstall-cluster:  ## Uninstall molior helm chart from k3d
	helm uninstall --wait molior || true

reinstall-cluster: uninstall-cluster install-cluster  ## Uninstall and reinstall molior helm chart

redeploy-cluster: uninstall-cluster deploy-cluster install-cluster watch  ## Redeploy images and reinstall helm chart

reload: docker-images-molior deploy-cluster restart-molior  # Rebuild and deploy molior and restart

list:  ## List pods
	kubectl get pods

watch:  ## Watch pods
	watch kubectl get pods

logs:  ## Show logs
	kubectl logs -l "app in (molior, aptly)" -f

logs-molior:  ## Show molior logs
	kubectl logs -l app=molior -f

logs-aptly:  ## Show aptly logs
	kubectl logs -l app=aptly -f


shell-molior:  ## Open a bash shell in the molior container
	kubectl exec -it $(shell kubectl get pod -l app=molior -o jsonpath='{.items[0].metadata.name}') -- bash

shell-aptly:  ## Open a bash shell in the aptly container
	kubectl exec -it $(shell kubectl get pod -l app=aptly -o jsonpath='{.items[0].metadata.name}') -- bash

restart-molior:  ## Restart molior pod
	kubectl delete pod -l app=molior

restart-aptly:  ## Restart aptly pod
	kubectl delete pod -l app=aptly

psql:  ## Run psql
	kubectl exec -it $(shell kubectl get pod -l app=molior -o jsonpath='{.items[0].metadata.name}') -- su molior -c psql molior

docker-clean:  ## Remove docker images
	docker rmi -f molior-base:dev molior:dev molior-nginx:dev molior-postgres:dev aptly:dev
	docker system prune


#prod-publish-manifest:  ## Push multi-arch manifests for all prod images
#	@for i in molior web aptly nginx postgres registry; do echo "\033[01;34mPushing Manifest $$i ...\033[00m"; docker manifest rm neolynx/molior_$$i; docker manifest create neolynx/molior_$$i neolynx/molior_$$i-amd64 neolynx/molior_$$i-arm64; docker manifest push neolynx/molior_$$i; done

#restore-backup:  ## Restore a database backup (usage: make restore-backup backup=path/to/db.tar)
#	@test -n "${backup}" || (echo Usage: make restore backup=path/to/db.tar; exit 1)
#	@test -f "${backup}" || (echo Error: file not found: ${backup}; exit 1)
#	@docker-compose stop molior
#	zcat "${backup}" | docker-compose exec -T postgres su postgres -c "dropdb molior && psql"
#	@docker-compose start molior

# Update with: echo .PHONY: `grep ^[a-z-]*: Makefile | cut -d: -f1` >> Makefile
.PHONY: help docker-images docker-images-molior docker-images-aptly docker-shell create-cluster delete-cluster deploy-cluster install-cluster uninstall-cluster reinstall-cluster redeploy-cluster reload list watch logs logs-molior logs-aptly shell-molior shell-aptly restart-molior restart-aptly psql docker-clean
