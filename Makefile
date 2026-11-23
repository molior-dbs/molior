# k3d cluster name (make create-k3d K3D_CLUSTER=local); the registry is <name>-registry, k3d names its container k3d-<name>-registry
K3D_CLUSTER ?= molior
REGISTRY := k3d-$(K3D_CLUSTER)-registry
REGISTRY_PORT := 5000
MOLIOR_DEV ?= true
PUSH_REGISTRY ?= localhost:$(REGISTRY_PORT)
MOLIOR_VERSION ?= dev

NAMESPACE := molior
LOCAL_PATH_VERSION ?= v0.0.32
LOCAL_PATH_DIR ?= /data/local-path-provisioner
SSH_USER ?= debian
# name clients use for the registry (no default, set per machine, see DEVELOPMENT-1.5.md); used by the install targets on the host
REGISTRY_HOST ?=
TRUST_PORT ?= 443
SSH_OPTS ?= -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
KUBE_CONTEXT = molior-$(IP)
export HELM_NAMESPACE=$(NAMESPACE)

ifneq ($(shell which podman 2>/dev/null),)
  DOCKERCMD := podman
  PODMAN_K3D_REGISTRY_ARGS := --default-network podman
else ifneq ($(shell which docker 2>/dev/null),)
  DOCKERCMD := docker
else
  # lazy: only fails when a docker target is used (the registry host has neither)
  DOCKERCMD = $(error Neither podman nor docker found in PATH)
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

helm-push: helm-package  ## Push helm chart to local OCI registry
	helm push molior-$(MOLIOR_VERSION).tgz oci://$(PUSH_REGISTRY)/charts

helm-package:  ## Build helm package
	helm package charts/

create-k3d:  ## Create k3d cluster $(K3D_CLUSTER) and its registry (default molior; make create-k3d K3D_CLUSTER=local)
	k3d registry list $(K3D_CLUSTER)-registry >/dev/null 2>&1 || k3d registry create $(K3D_CLUSTER)-registry --port 0.0.0.0:$(REGISTRY_PORT) $(PODMAN_K3D_REGISTRY_ARGS)
	k3d cluster create $(K3D_CLUSTER) \
		--registry-use $(REGISTRY):$(REGISTRY_PORT) \
		--port "8000:30080@server:0" \
		--port "8080:30088@server:0" \
		--k3s-arg "--disable=traefik@server:0" \
		--k3s-arg "--disable=metrics-server@server:0"
	kubectl config set-context --current --namespace=$(NAMESPACE)

delete-k3d:  ## Delete k3d cluster $(K3D_CLUSTER) (the registry stays)
	k3d cluster delete $(K3D_CLUSTER)

rsync:  ## Copy this source tree to ~/molior on a host (usage: make rsync IP=<host>; RSYNC_OPTS=--delete to mirror)
	@test -n "$(IP)" || (echo "Usage: make rsync IP=<node-ip>"; exit 1)
	rsync -a $(RSYNC_OPTS) --exclude .git --exclude node_modules --exclude __pycache__ --exclude '*.pyc' --exclude .env --exclude '*.dump.gz' \
		-e "ssh $(SSH_OPTS)" $(CURDIR)/ $(SSH_USER)@$(IP):molior/

install-registry:  ## Install docker-registry and an nginx server block for REGISTRY_HOST=<name> (after install-nginx). Push password on stdin, see scripts/install-registry
	sudo env REGISTRY_HOST="$(REGISTRY_HOST)" sh scripts/install-registry

passwd-registry:  ## Ask for a new registry push password on this host (run with a terminal: ssh -t <host> 'cd ~/molior && make passwd-registry')
	sudo sh scripts/passwd-registry

uninstall-registry:  ## Remove docker-registry, its nginx server block and /data/registry on this host (FORCE=1 if it holds images)
	sudo env FORCE="$(FORCE)" sh scripts/uninstall-registry

install-docker:  ## Install docker.io + docker-cli and trust the registry certificate for REGISTRY_HOST=<name> on this host (after install-nginx)
	sudo env REGISTRY_HOST="$(REGISTRY_HOST)" sh scripts/install-docker

install-containerd-trust:  ## Make containerd trust the registry certificate for REGISTRY_HOST=<name> [TRUST_PORT=443] on this host, restarts containerd once (after install-nginx)
	sudo env REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_PORT="$(TRUST_PORT)" sh scripts/install-containerd-trust

install-nginx:  ## Install nginx + self-signed certificate on this host (CERT_CN, CERT_SAN, REGISTRY_HOST=<name> adds its name, FORCE=1 replaces the certificate)
	sudo env CERT_CN="$(CERT_CN)" CERT_SAN="$(CERT_SAN)" REGISTRY_HOST="$(REGISTRY_HOST)" FORCE="$(FORCE)" sh scripts/install-nginx

configure-cluster:  ## Configure kubectl for a remote kubeadm cluster (usage: make configure-cluster IP=<host>)
	@test -n "$(IP)" || (echo "Usage: make configure-cluster IP=<node-ip>"; exit 1)
	@set -e; umask 077; tmp=$$(mktemp); trap 'rm -f $$tmp $$tmp.new' EXIT; \
	ssh $(SSH_OPTS) $(SSH_USER)@$(IP) 'sudo cat /etc/kubernetes/admin.conf' > $$tmp; \
	test -s $$tmp || (echo "Error: could not read /etc/kubernetes/admin.conf from $(IP)"; exit 1); \
	sed -i \
		-e 's|server: https://.*|server: https://$(IP):6443|' \
		-e 's|kubernetes-admin@kubernetes|$(KUBE_CONTEXT)|g' \
		-e 's|^\([[:space:]-]*\)name: kubernetes-admin$$|\1name: $(KUBE_CONTEXT)-admin|' \
		-e 's|user: kubernetes-admin$$|user: $(KUBE_CONTEXT)-admin|' \
		-e 's|cluster: kubernetes$$|cluster: $(KUBE_CONTEXT)|' \
		-e 's|^\([[:space:]-]*\)name: kubernetes$$|\1name: $(KUBE_CONTEXT)|' $$tmp; \
	KUBECONFIG=$$tmp kubectl config set-context $(KUBE_CONTEXT) --namespace=$(NAMESPACE) >/dev/null; \
	mkdir -p $$HOME/.kube; \
	KUBECONFIG=$$tmp:$$HOME/.kube/config kubectl config view --flatten > $$tmp.new; \
	cat $$tmp.new > $$HOME/.kube/config
	kubectl get nodes

install-local-path-provisioner:  ## Install local-path-provisioner as default StorageClass and create the PVs of a file (usage: make install-local-path-provisioner IP=<host> PV=<file>)
	@test -n "$(IP)" || (echo "Usage: make install-local-path-provisioner IP=<node-ip>"; exit 1)
	@test -f "$(PV)" || (echo "PV file '$(PV)' not found (usage: PV=<file>)"; exit 1)
	curl -fsSL https://raw.githubusercontent.com/rancher/local-path-provisioner/$(LOCAL_PATH_VERSION)/deploy/local-path-storage.yaml \
		| sed -e 's|/opt/local-path-provisioner|$(LOCAL_PATH_DIR)|' -e 's|reclaimPolicy: Delete|reclaimPolicy: Retain|' \
		| kubectl apply -f -
	kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=120s
	kubectl patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
	kubectl apply -f $(PV)
	kubectl get storageclass,pv

deploy-k3d:  deploy-image-molior deploy-image-molior-nginx deploy-image-molior-postgres deploy-image-aptly  ## Import local images into k3d

# REGISTRY is the k3d registry name by default, so only a REGISTRY given on the command line or in the environment counts here
PUSH_TO = $(if $(filter file,$(origin REGISTRY)),$(REGISTRY_HOST),$(REGISTRY))

push:  ## Tag the local <image>:dev images as $(MOLIOR_VERSION) and push them: make push REGISTRY=<name> [MOLIOR_VERSION=<tag>] [DOCKERCMD=...]
	@test -n "$(PUSH_TO)" || { echo "usage: make push REGISTRY=<registry name> [MOLIOR_VERSION=<tag>]"; exit 1; }
	@for i in molior molior-postgres aptly molior-nginx; do \
		echo "== $$i:dev -> $(PUSH_TO)/$$i:$(MOLIOR_VERSION)"; \
		$(DOCKERCMD) tag $$i:dev $(PUSH_TO)/$$i:$(MOLIOR_VERSION) && \
		$(DOCKERCMD) push $(PUSH_TO)/$$i:$(MOLIOR_VERSION) && \
		$(DOCKERCMD) rmi $(PUSH_TO)/$$i:$(MOLIOR_VERSION) || exit 1; \
	done

deploy-image-%:  ## Import a local <image>:dev into k3d (e.g. make deploy-image-molior)
	$(DOCKERCMD) tag $*:$(MOLIOR_VERSION) $(PUSH_REGISTRY)/$*:$(MOLIOR_VERSION)
	$(DOCKERCMD) push $(PUSH_REGISTRY)/$*:$(MOLIOR_VERSION)
	$(DOCKERCMD) rmi $(PUSH_REGISTRY)/$*:$(MOLIOR_VERSION)

download-k3d:  ## Download and install k3d binary
	@if ! which k3d 2>/dev/null; then echo Downloading https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64 to ~/.local/bin/k3d; \
		mkdir -p ~/.local/bin; \
		curl -fL -o ~/.local/bin/k3d https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64; \
		chmod +x ~/.local/bin/k3d; \
		echo ${PATH} | grep -q ${HOME}/.local/bin || echo Please add ~/.local/bin to the PATH; \
	fi



# VALUES=<file> adds a values file; registry and molior.dev still come from K3D_CLUSTER and MOLIOR_DEV (the later -f wins)
install-k3d:  ## Install molior dev into cluster (Secret molior-passwords with molior-dev if missing; optional VALUES=<values file>)
	@test -z "$(VALUES)" || test -f "$(VALUES)" || { echo "VALUES file $(VALUES) not found"; exit 1; }
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NAMESPACE) get secret molior-passwords >/dev/null 2>&1 || kubectl -n $(NAMESPACE) create secret generic molior-passwords \
		--from-literal=molior-password=molior-dev --from-literal=aptly-password=molior-dev --from-literal=registry-password=molior-dev
	printf 'registry:\n  host: %s\n  port: %s\nmolior:\n  dev: %s\n' $(REGISTRY) $(REGISTRY_PORT) $(MOLIOR_DEV) > /tmp/molior-registry-values.yaml
	helm install --create-namespace molior charts/ $(if $(VALUES),-f $(VALUES)) -f /tmp/molior-registry-values.yaml; rm -f /tmp/molior-registry-values.yaml

uninstall-k3d:  ## Uninstall molior helm chart from k3d
	helm uninstall --wait molior || true

reinstall-k3d: uninstall-k3d install-k3d  ## Uninstall and reinstall molior helm chart

redeploy-k3d: uninstall-k3d deploy-k3d install-k3d watch  ## Redeploy images and reinstall helm chart

reload: docker-images-molior deploy-k3d restart-molior  # Rebuild and deploy molior and restart

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

hold-molior:  ## Create the hold file on the molior volume: after the next pod start only postgres runs, molior waits (then: make restart-molior, make import-db, make release-molior)
	kubectl -n $(NAMESPACE) exec deploy/molior -c molior-server -- touch /var/lib/molior/molior-hold

release-molior:  ## Remove the hold file: a waiting molior runs db-upgrade.sh and starts
	kubectl -n $(NAMESPACE) exec deploy/molior -c molior-server -- rm -f /var/lib/molior/molior-hold

import-db:  ## Import a molior database dump (pg_dump -C, .sql or .sql.gz) into the molior-postgres container, streamed from this machine (usage: make import-db DUMP=<file>; FORCE=1 if the database holds data)
	@test -n "$(DUMP)" || (echo "Usage: make import-db DUMP=<file>"; exit 1)
	NAMESPACE="$(NAMESPACE)" DUMP="$(DUMP)" FORCE="$(FORCE)" sh scripts/import-db

set-passwords:  ## Ask for the molior, aptly and registry passwords and store them in the Secret molior-passwords, empty keeps the current one (needs a terminal; usage: make set-passwords)
	@NAMESPACE="$(NAMESPACE)" sh scripts/set-passwords

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
.PHONY: help hold-molior release-molior import-db set-passwords push docker-images docker-images-molior docker-images-aptly docker-shell create-k3d delete-k3d rsync install-registry passwd-registry uninstall-registry install-docker install-containerd-trust install-nginx configure-cluster install-local-path-provisioner deploy-k3d install-k3d uninstall-k3d reinstall-k3d redeploy-k3d reload list watch logs logs-molior logs-aptly shell-molior shell-aptly restart-molior restart-aptly psql docker-clean
