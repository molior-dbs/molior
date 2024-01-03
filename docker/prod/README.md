# Deploy Molior with docker-compose

Download the [molior](./) directory.

## Configuration

### Configure Molior server

Adapt the settings in the `config/` directory:

- [molior.yml]
- `backend-docker.yml`
- `aptly.conf`


### Configure GPG key and user/password creation

Adapt setting in the docker-compoer [.env](./.env) file.

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

