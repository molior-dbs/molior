create-cluster:
	k3d cluster create molior --port "8000:80@loadbalancer"

delete-cluster:
	k3d cluster delete molior

import: import-aptly import-molior import-nginx import-postgres import-nginx import-web import-registry

import-web:
	k3d image import --cluster molior molior_web
import-registry:
	k3d image import --cluster molior molior_registry
import-nginx:
	k3d image import --cluster molior molior_nginx
import-postgres:
	k3d image import --cluster molior molior_postgres
import-molior:
	k3d image import --cluster molior molior_molior
import-aptly:
	k3d image import --cluster molior molior_aptly

package:
	helm package molior

install: package
	helm install molior molior-0.0.1.tgz
	rm -f molior-0.0.1.tgz

uninstall:
	helm uninstall molior

update: package
	helm upgrade molior molior-0.0.1.tgz

list:
	kubectl get pods -A


.PHONY: create-cluster delete-cluster import import-aptly import-molior import-nginx import-postgres import-registry import-web install list package uninstall update

