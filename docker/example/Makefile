.PHONY: help status perms logs pull start stop

# Self-documenting Makefile
# https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
help:  ## Print this help
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-10s\033[0m %s\n", $$1, $$2}'

start: perms   ## Start containers
	@docker-compose up -d

stop:  ## Stop containers
	@docker-compose stop

status:  ## Show status
	@docker-compose ps

logs:  ## Show logs
	@docker-compose logs -f aptly molior

pull: perms  ## Pull new images and start
	@docker-compose pull
	@docker-compose up -d --remove-orphans

perms:  # fix perms of config files
	chmod 600 config/*
