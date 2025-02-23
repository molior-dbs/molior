
NAMESPACE := molior

export HELM_NAMESPACE=$(NAMESPACE)

help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

create-cluster:  ## Create k3d cluster
	#k3d cluster create --config k3d/cluster.yaml
	k3d cluster create molior --port "8000:80@loadbalancer" --port "8080:30080" --port "5000:30500" --registry-config k3d/registry.yaml
	kubectl config set-context --current --namespace=$(NAMESPACE)

delete-cluster:  ## Delete k3d cluster
	k3d cluster delete molior

import:  ## Import local prod images into k3d
	k3d image import --cluster molior molior_web molior_registry molior_nginx molior_postgres molior_molior molior_aptly

import-web:  ## Import web image into k3d
	k3d image import --cluster molior molior_web
import-registry:  ## Import registry image into k3d
	k3d image import --cluster molior molior_registry
import-nginx:  ## Import nginx image into k3d
	k3d image import --cluster molior molior_nginx
import-postgres:  ## Import postgres image into k3d
	k3d image import --cluster molior molior_postgres
import-molior:  ## Import molior image into k3d
	k3d image import --cluster molior molior_molior
import-aptly:  ## Import aptly image into k3d
	k3d image import --cluster molior molior_aptly

package:  ## Create molior helm package
	helm package molior

install: ## Install molior helm chart
	helm install --create-namespace molior molior/

uninstall:  ## Uninstall molior helm package
	helm uninstall molior

update: package  ## Update molior helm chart
	helm upgrade molior molior-0.0.1.tgz

list:  ## List pods
	kubectl get pods -A

watch:  ## Watch pods
	watch kubectl get pods -A

.PHONY: create-cluster delete-cluster import import-aptly import-molior import-nginx import-postgres import-registry import-web install list package uninstall update

