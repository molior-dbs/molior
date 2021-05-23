
VERSION := $(shell cd .. && dpkg-parsechangelog -S Version | tr '~' '-')

all:
	docker build . -f Dockerfile.molior -t molior:${VERSION}
	docker build . -f Dockerfile.aptly -t molior-aptly:${VERSION}

	sed s/VERSION/${VERSION}/ < docker-compose.yml.in >docker-compose.yml

