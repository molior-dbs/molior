
status:  ## Show status (default)
	@docker-compose ps

logs:  ## Show logs
	@docker-compose logs -f aptly molior

pull:  ## Pull new images and start
	@docker-compose pull
	@docker-compose up -d

start:  ## Start containers
	@docker-compose up -d

stop:  ## Stop containers
	@docker-compose stop

# Self-documenting Makefile
# https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'


