# Deploy molior with docker-compose

## Configuration

### 1. Adapt the settings in the `config/` directory:

- `molior.yml`
- `backend-docker.yml`
- `aptly.conf`


### 2. Edit .env file and adapt settings:

```
# Molior docker compose env file

# Make sure docker compose uses 'molior' as project name, instead of directory name
COMPOSE_PROJECT_NAME=molior

# the following settings are for creating credentials and keys on first startup

# debian package signing keys

DEBSIGN_NAME=molior
DEBSIGN_EMAIL=debsign@molior
# Note: make sure debsign_gpg_email in config/molior.yml matches DEBSIGN_EMAIL

REPOSIGN_NAME=molior
REPOSIGN_EMAIL=reposign@molior
# Note: make sure aptly/gpg_key in config/molior.yml matches REPOSIGN_EMAIL

# Create docker registry login
REGISTRY_USER=molior
REGISTRY_PASSWORD=molior-dev
# Note: make sure registry:user/password in config/backend-docker.yml match these settings

# Create aptly login
APTLY_USER=molior
APTLY_PASSWORD=molior-dev
# Note: make sure aptly:api_user/api_pass in config/molior.yml match these settings
```

## Running molior

For convenience, there is a Makefile offering the following:
```
$ make help
help                           Print this help
logs                           Show logs
pull                           Pull new images and start
start                          Start containers
status                         Show status (default)
stop                           Stop containers
```

### Start molior

To start molior, run:
```
make start
```

or run `docker-compose up -d` directly.

## Access molior

Go to http://localhost:8000 and login with `admin` and login with configured ADMIN_PASSWORD.

## See logs

```
make logs
```

or run `docker-compose logs -f` directly.

