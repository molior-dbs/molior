
VERSION := $(shell cd .. && dpkg-parsechangelog -S Version | tr '~' '-')

all:
	docker build . -f Dockerfile.molior -t molior:${VERSION}
	docker build . -f Dockerfile.aptly -t molior-aptly:${VERSION}

publish:
	docker tag molior:${VERSION} neolynx/molior:latest
	docker tag molior-aptly:${VERSION} neolynx/molior-aptly:latest
	docker push neolynx/molior:latest
	docker push neolynx/molior-aptly:latest


destroy:
	docker rmi -f molior:${VERSION} neolynx/molior:latest molior-aptly:${VERSION} neolynx/molior-aptly:latest
