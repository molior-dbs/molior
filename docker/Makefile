
VERSION := $(shell cd .. && dpkg-parsechangelog -S Version | tr '~' '-')

all:
	docker build . -f Dockerfile.molior -t molior:${VERSION}
	docker build . -f Dockerfile.aptly -t molior-aptly:${VERSION}

	sed s/VERSION/${VERSION}/ < docker-compose.yml.in >docker-compose.yml

publish:
	docker tag molior:${VERSION} neolynx/molior:${VERSION}
	docker tag molior-aptly:${VERSION} neolynx/molior-aptly:${VERSION}
	docker push neolynx/molior:${VERSION}
	docker push neolynx/molior-aptly:${VERSION}


destroy:
	docker rmi -f molior:${VERSION} neolynx/molior:${VERSION} molior-aptly:${VERSION} neolynx/molior-aptly:${VERSION}
