# molior: build, test and run locally in k3d. `make` or `make help` lists the targets.
# Local Development targets work on the local k3d cluster (kubectl context k3d-$(K3D_CLUSTER), not the current context).

MOLIOR_VERSION ?= dev
NAMESPACE := molior
# local k3d cluster (make create-cluster K3D_CLUSTER=local); its registry container is k3d-<cluster>-registry
K3D_CLUSTER ?= molior
K3D_VERSION ?= v5.9.0
K3D_REGISTRY = k3d-$(K3D_CLUSTER)-registry
# host ports of the local cluster (other values for a second cluster next to an existing one); the registry listens on
# K3D_REGISTRY_PORT inside the cluster too
K3D_REGISTRY_PORT ?= 5000
K3D_WEB_PORT ?= 8000
K3D_APTLY_PORT ?= 8080
# true: plain-HTTP session cookies (no TLS in the local cluster)
MOLIOR_DEV ?= true
# system-tests: pytest args, relative to tests/system (default: all suites)
TEST ?= smoke valid-1.4/validation_tests.py
# IMAGE_SOURCE=<repo url>: label org.opencontainers.image.source (CI: ghcr links a new package to the repo)
IMAGE_SOURCE ?=
IMAGE_LABEL = $(if $(IMAGE_SOURCE),--label org.opencontainers.image.source=$(IMAGE_SOURCE))
IMAGES := molior molior-postgres aptly molior-nginx
ALL_APPS := molior,aptly

KUBECTL_LOCAL = kubectl --context k3d-$(K3D_CLUSTER) -n $(NAMESPACE)
HELM_LOCAL = helm --kube-context k3d-$(K3D_CLUSTER) -n $(NAMESPACE)

ifneq ($(shell which podman 2>/dev/null),)
  DOCKERCMD := podman
  PODMAN_K3D_REGISTRY_ARGS := --default-network podman
else ifneq ($(shell which docker 2>/dev/null),)
  DOCKERCMD := docker
else
  # lazy: only fails when a docker target is used (a host without either can still run the other targets)
  DOCKERCMD = $(error Neither podman nor docker found in PATH)
endif

# tag the local <image>:dev images as $(1)/<image>:$(2) and push them: $(call push-images,<registry>,<tag>,<images>)
define push-images
	@for i in $(3); do \
		echo "== $$i:dev -> $(1)/$$i:$(2)"; \
		$(DOCKERCMD) tag $$i:dev $(1)/$$i:$(2) && \
		$(DOCKERCMD) push $(1)/$$i:$(2) && \
		$(DOCKERCMD) rmi $(1)/$$i:$(2) || exit 1; \
	done
endef

.NOTPARALLEL:

##@ Local Development (k3d cluster K3D_CLUSTER=molior)

help:  ## Show this help
	@printf '\n\033[1;94m     ~ Molior Makefile ~\033[0m\n'
	@awk 'BEGIN {FS = ":.*## "} /^##@/ {printf "\n\033[1;92m%s\033[0m\n", substr($$0, 5)} \
		/^[a-z][a-z0-9-]*:.*## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install-deps:  ## Install k3d to ~/.local/bin (helm, kubectl and podman or docker are needed too)
	@set -e; mkdir -p ~/.local/bin; T=$$(mktemp -d); trap 'rm -rf "$$T"' EXIT; \
		U=https://github.com/k3d-io/k3d/releases/download/$(K3D_VERSION); \
		curl -fsSL -o "$$T/k3d-linux-amd64" "$$U/k3d-linux-amd64"; \
		sum=$$(curl -fsSL "$$U/checksums.txt" | awk '$$2 ~ /(^|\/)k3d-linux-amd64$$/ {print $$1}'); \
		echo "$$sum  $$T/k3d-linux-amd64" | sha256sum -c -; \
		install -m 755 "$$T/k3d-linux-amd64" ~/.local/bin/k3d; \
		~/.local/bin/k3d version | head -1; \
		echo "$$PATH" | tr : '\n' | grep -qx "$$HOME/.local/bin" || echo "Add ~/.local/bin to the PATH"

create-cluster:  ## Create the cluster and its registry (web UI http://localhost:8000, aptly http://localhost:8080)
	k3d registry list $(K3D_CLUSTER)-registry >/dev/null 2>&1 || \
		k3d registry create $(K3D_CLUSTER)-registry --port 0.0.0.0:$(K3D_REGISTRY_PORT) --enforce-port-match $(PODMAN_K3D_REGISTRY_ARGS)
	k3d cluster create $(K3D_CLUSTER) --kubeconfig-switch-context=false \
		--registry-use $(K3D_REGISTRY):$(K3D_REGISTRY_PORT) \
		--port "$(K3D_WEB_PORT):30080@server:0" \
		--port "$(K3D_APTLY_PORT):30088@server:0" \
		--k3s-arg "--disable=traefik@server:0" \
		--k3s-arg "--disable=metrics-server@server:0"

docker-images: docker-images-molior docker-images-aptly  ## Build the images (molior, molior-postgres, aptly, molior-nginx)

docker-image-base:
	@$(DOCKERCMD) inspect molior-base:dev >/dev/null 2>&1 || (echo Building base docker image...; \
		$(DOCKERCMD) build -f docker/molior/molior-base.Dockerfile -t molior-base:dev .)

docker-images-molior: docker-image-base
	$(DOCKERCMD) build $(IMAGE_LABEL) -f docker/molior/molior-dev.Dockerfile -t molior:dev .
	$(DOCKERCMD) build $(IMAGE_LABEL) -f docker/molior/postgres.Dockerfile -t molior-postgres:dev .

docker-images-aptly:
	$(DOCKERCMD) build $(IMAGE_LABEL) -f docker/aptly/aptly.Dockerfile -t aptly:dev .
	$(DOCKERCMD) build $(IMAGE_LABEL) -f docker/aptly/nginx.Dockerfile -t molior-nginx:dev .

deploy:  ## Push the images to the cluster registry (published on localhost)
	$(call push-images,localhost:$(K3D_REGISTRY_PORT),$(MOLIOR_VERSION),$(IMAGES))

deploy-molior:
	$(call push-images,localhost:$(K3D_REGISTRY_PORT),$(MOLIOR_VERSION),molior molior-postgres)

# VALUES=<file> adds a values file; registry and molior.dev come from K3D_CLUSTER and MOLIOR_DEV (the later --set wins)
install-helmchart:  ## Install molior with the helm chart (VALUES=<values file>, after deploy)
	@test -z "$(VALUES)" || test -f "$(VALUES)" || { echo "VALUES file $(VALUES) not found"; exit 1; }
	kubectl --context k3d-$(K3D_CLUSTER) create namespace $(NAMESPACE) --dry-run=client -o yaml \
		| kubectl --context k3d-$(K3D_CLUSTER) apply -f -
	$(KUBECTL_LOCAL) get secret molior-passwords >/dev/null 2>&1 || $(KUBECTL_LOCAL) create secret generic molior-passwords \
		--from-literal=molior-password=molior-dev --from-literal=aptly-password=molior-dev \
		--from-literal=registry-password=molior-dev
	$(HELM_LOCAL) install molior charts/ $(if $(VALUES),-f $(VALUES)) \
		--set registry.host=$(K3D_REGISTRY) --set registry.port=$(K3D_REGISTRY_PORT) --set molior.dev=$(MOLIOR_DEV) \
		--set aptly.publicUrl=http://localhost:$(K3D_APTLY_PORT)

reload: docker-images-molior deploy-molior  ## Rebuild molior, push it and restart its pod (dev loop)
	$(KUBECTL_LOCAL) rollout restart deployment/molior
	$(KUBECTL_LOCAL) rollout status deployment/molior --timeout=600s

redeploy: docker-images deploy  ## Rebuild and push all images, install molior again
	@$(MAKE) --no-print-directory uninstall-helmchart install-helmchart

# --cascade foreground: helm waits until the pods are gone (default: background, the old pods still terminate while
# a new install starts them again, two aptly or postgres on the same volume)
uninstall-helmchart:  ## Uninstall molior (the volumes stay)
	$(HELM_LOCAL) uninstall --ignore-not-found --cascade foreground --wait --timeout 300s molior
	$(KUBECTL_LOCAL) wait --for=delete pod -l 'app in ($(ALL_APPS))' --timeout=300s

delete-cluster:  ## Delete the cluster (the registry and its images stay)
	k3d cluster delete $(K3D_CLUSTER)

##@ Testing

lint:  ## Run flake8
	flake8 molior tests

unit-tests:  ## Run the unit tests with coverage
	python3 -m pytest -q -p no:cacheprovider --cov --cov-config=.coveragerc --cov-report= \
		--junitxml=unit-test-report.xml tests/unit

# tests/system/system-tests.sh uses docker, so the base image is built with docker too
system-tests:  ## Run the system tests in a throwaway k3d cluster (TEST=valid-1.4/validation_tests.py::test_build_order)
	@$(MAKE) --no-print-directory docker-image-base DOCKERCMD=docker
	tests/system/system-tests.sh $(TEST)

##@ Deploying

# CI: make set-version MOLIOR_VERSION=<version> (top entry of debian/changelog)
set-version:
	@test "$(MOLIOR_VERSION)" != dev || { echo "usage: make set-version MOLIOR_VERSION=<version>"; exit 1; }
	sed -i '1s/^\([^ ]*\) ([^)]*)/\1 ($(MOLIOR_VERSION))/' debian/changelog
	@head -1 debian/changelog

# CI: make tag-images MOLIOR_VERSION=<version> (local <image>:dev as <image>:<version>, no push)
tag-images:
	@test "$(MOLIOR_VERSION)" != dev || { echo "usage: make tag-images MOLIOR_VERSION=<version>"; exit 1; }
	@for i in $(IMAGES); do \
		echo "== $$i:dev -> $$i:$(MOLIOR_VERSION)"; \
		$(DOCKERCMD) tag $$i:dev $$i:$(MOLIOR_VERSION) || exit 1; \
	done

# prod images: molior-server from the molior.info repository, not from this tree
docker-images-prod:
	$(DOCKERCMD) build --no-cache -f docker/aptly/aptly.Dockerfile -t aptly:prod .
	$(DOCKERCMD) build --no-cache -f docker/aptly/nginx.Dockerfile -t molior-nginx:prod .
	$(DOCKERCMD) build --no-cache -f docker/molior/postgres.Dockerfile -t molior-postgres:prod .
	$(DOCKERCMD) build --no-cache -f docker/molior/molior.Dockerfile -t molior:prod .

push:  ## Push the images: make push REGISTRY=<registry> [MOLIOR_VERSION=<tag>]
	@test -n "$(REGISTRY)" || { echo "usage: make push REGISTRY=<registry> [MOLIOR_VERSION=<tag>]"; exit 1; }
	$(call push-images,$(REGISTRY),$(MOLIOR_VERSION),$(IMAGES))

chart:  ## Package the helm chart (MOLIOR_VERSION=<version> sets the chart version and the image tag)
ifeq ($(MOLIOR_VERSION),dev)
	helm package charts/
else
	@set -e; D=$$(mktemp -d); trap 'rm -rf "$$D"' EXIT; cp -r charts "$$D/molior"; \
		sed -i '/^molior:/,/^[^ #]/s/^\(  version:\).*/\1 "$(MOLIOR_VERSION)"/' "$$D/molior/values.yaml"; \
		grep -q '^  version: "$(MOLIOR_VERSION)"$$' "$$D/molior/values.yaml"; \
		helm package --version $(MOLIOR_VERSION) --app-version $(MOLIOR_VERSION) "$$D/molior"
endif

# Host setup of a single node kubeadm host (to be documented in a separate file)
SSH_USER ?= debian
SSH_OPTS ?= -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
# name clients use for the registry of the host (no default)
REGISTRY_HOST ?=
TRUST_PORT ?= 443

# make rsync IP=<host> [RSYNC_OPTS=--delete]: copy this tree to ~/molior on the host
rsync:
	@test -n "$(IP)" || (echo "Usage: make rsync IP=<host>"; exit 1)
	rsync -a $(RSYNC_OPTS) --exclude .git --exclude node_modules --exclude __pycache__ --exclude '*.pyc' --exclude .env \
		--exclude '*.dump.gz' -e "ssh $(SSH_OPTS)" $(CURDIR)/ $(SSH_USER)@$(IP):molior/

# nginx and a self-signed certificate (CERT_CN, CERT_SAN, REGISTRY_HOST=<name> adds its name, FORCE=1 replaces it)
install-nginx:
	sudo env CERT_CN="$(CERT_CN)" CERT_SAN="$(CERT_SAN)" REGISTRY_HOST="$(REGISTRY_HOST)" FORCE="$(FORCE)" sh scripts/install-nginx

# docker-registry and its nginx server block for REGISTRY_HOST=<name>, push password on stdin (after install-nginx)
install-registry:
	sudo env REGISTRY_HOST="$(REGISTRY_HOST)" sh scripts/install-registry

# new registry push password (needs a terminal: ssh -t <host> 'cd ~/molior && make passwd-registry')
passwd-registry:
	sudo sh scripts/passwd-registry

# remove docker-registry, its nginx server block and /data/registry (FORCE=1 if it holds images)
uninstall-registry:
	sudo env FORCE="$(FORCE)" sh scripts/uninstall-registry

# docker.io and docker-cli, trusting the registry certificate of REGISTRY_HOST=<name> (after install-nginx)
install-docker:
	sudo env REGISTRY_HOST="$(REGISTRY_HOST)" sh scripts/install-docker

# containerd trusts the registry certificate of REGISTRY_HOST=<name> [TRUST_PORT=443], restarts containerd once
install-containerd-trust:
	sudo env REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_PORT="$(TRUST_PORT)" sh scripts/install-containerd-trust

##@ Molior Maintenance (current kubectl context)

KUBE_CONTEXT = molior-$(IP)
# make configure-cluster IP=<host>: merge the kubeconfig of the host into ~/.kube/config as context molior-<host>
configure-cluster:
	@test -n "$(IP)" || (echo "Usage: make configure-cluster IP=<host>"; exit 1)
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

LOCAL_PATH_VERSION ?= v0.0.32
LOCAL_PATH_DIR ?= /data/local-path-provisioner
LOCAL_PATH_URL = https://raw.githubusercontent.com/rancher/local-path-provisioner/$(LOCAL_PATH_VERSION)/deploy/local-path-storage.yaml
# make install-local-path-provisioner IP=<host> PV=<file>: local-path as default StorageClass, and the PVs of the file
install-local-path-provisioner:
	@test -n "$(IP)" || (echo "Usage: make install-local-path-provisioner IP=<host> PV=<file>"; exit 1)
	@test -f "$(PV)" || (echo "PV file '$(PV)' not found (usage: PV=<file>)"; exit 1)
	curl -fsSL "$(LOCAL_PATH_URL)" \
		| sed -e 's|/opt/local-path-provisioner|$(LOCAL_PATH_DIR)|' -e 's|reclaimPolicy: Delete|reclaimPolicy: Retain|' \
		| kubectl apply -f -
	kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=120s
	kubectl patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
	kubectl apply -f $(PV)
	kubectl get storageclass,pv

list:  ## List the pods
	kubectl -n $(NAMESPACE) get pods

watch:  ## Watch the pods
	watch kubectl -n $(NAMESPACE) get pods

logs:  ## Follow the logs (APP=molior or APP=aptly, default both)
	kubectl -n $(NAMESPACE) logs -f --all-containers --max-log-requests 10 -l "app in ($(or $(APP),$(ALL_APPS)))"

shell:  ## Open a shell in a pod (APP=molior or APP=aptly, default molior)
	kubectl -n $(NAMESPACE) exec -it deploy/$(or $(APP),molior) -c $(or $(APP),molior)-server -- bash

psql:  ## Open psql on the molior database
	kubectl -n $(NAMESPACE) exec -it deploy/molior -c molior-server -- su molior -c 'psql molior'

# rollout restart follows the Recreate strategy: the new pod starts when the old one is gone (kubectl delete pod lets the
# ReplicaSet start the new pod at once, next to the terminating one on the same volumes)
restart:  ## Restart the molior and aptly pods
	kubectl -n $(NAMESPACE) rollout restart deployment/molior deployment/aptly
	kubectl -n $(NAMESPACE) rollout status deployment/molior --timeout=600s
	kubectl -n $(NAMESPACE) rollout status deployment/aptly --timeout=600s

restart-molior:  ## Restart the molior pod
	kubectl -n $(NAMESPACE) rollout restart deployment/molior
	kubectl -n $(NAMESPACE) rollout status deployment/molior --timeout=600s

restart-aptly:  ## Restart the aptly pod
	kubectl -n $(NAMESPACE) rollout restart deployment/aptly
	kubectl -n $(NAMESPACE) rollout status deployment/aptly --timeout=600s

set-passwords:  ## Set the molior, aptly and registry passwords in the Secret molior-passwords (will ask for passwords)
	@NAMESPACE="$(NAMESPACE)" sh scripts/set-passwords

# hold-molior, release-molior: the hold file (after the next pod start only postgres runs), used by scripts/import-db;
# release-molior also after a failed import-db
hold-molior:
	kubectl -n $(NAMESPACE) exec deploy/molior -c molior-server -- touch /var/lib/molior/molior-hold

import-db:  ## Import a database dump (DUMP=<file> [FORCE=1]), molior will restart
	@test -n "$(DUMP)" || (echo "Usage: make import-db DUMP=<file>"; exit 1)
	NAMESPACE="$(NAMESPACE)" DUMP="$(DUMP)" FORCE="$(FORCE)" sh scripts/import-db

release-molior:
	kubectl -n $(NAMESPACE) exec deploy/molior -c molior-server -- rm -f /var/lib/molior/molior-hold

# Update with: echo .PHONY: `grep ^[a-z-]*: Makefile | cut -d: -f1` >> Makefile
.PHONY: help install-deps create-cluster docker-images docker-image-base docker-images-molior docker-images-aptly deploy deploy-molior install-helmchart reload redeploy uninstall-helmchart delete-cluster lint unit-tests system-tests set-version tag-images docker-images-prod push chart rsync install-nginx install-registry passwd-registry uninstall-registry install-docker install-containerd-trust configure-cluster install-local-path-provisioner list watch logs shell psql restart restart-molior restart-aptly set-passwords hold-molior import-db release-molior
