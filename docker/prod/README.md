# Deploy Molior with docker-compose

Copy the [docker/prod](./) directory to a location on a docker-compose server and call it `molior/`:

```
molior/
├── config
│   ├── aptly.conf
│   ├── backend-docker.yml
│   └── molior.yml
├── docker-compose.yml
├── .env
├── Makefile
└── README.md
```

## Configuration

1. Configure initial settings

Adapt setting in the docker-compoer [.env](./.env) file. This is used for creating GPG keys for debian package signing and accounts for aptly and the registry.

### Configure Molior server

Adapt the settings in the `config/` directory:

- [molior.yml](config/molior.yml)
- [backend-docker.yml](config/backend-docker.yml)
- [aptly.conf](config/aptly.conf)

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

### See logs

To the log output of molior and aptly, run:
```
make logs
```
or run `docker-compose logs -f` directly.

## Access molior

Go to http://localhost:8000 and login with `admin` and login with configured ADMIN_PASSWORD.

