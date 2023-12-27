# Running molior in docker compose


## Configuration

Edit .env file and adapt settings:
```
COMPOSE_PROJECT_NAME=molior

# WebUI admin password
ADMIN_PASSWORD=molior-dev

# URL where the APT repositories are reachable (also from docker build nodes)
APT_URL_PUBLIC=http://host.docker.internal:8080

# docker registry
REGISTRY_USER=molior
REGISTRY_PASSWORD=molior-dev

# aptly api
APTLY_USER=molior
APTLY_PASSWORD=molior-dev

# gpg keys
DEBSIGN_NAME=molior
DEBSIGN_EMAIL=debsign@molior
REPOSIGN_NAME=molior
REPOSIGN_EMAIL=reposign@molior
```

## Start molior

```
docker-compose up -d
```

## Access molior

Go to http://localhost:8000 and login with `admin` and login with configured ADMIN_PASSWORD.

## See logs

```
docker-compose logs -f
```
