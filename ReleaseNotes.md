# New in version 1.5.0

- docker-compose based deployment
- support docker build containers (no bare metal build nodes needed anymore)
- support running on arm64
- support publishing projectversions to S3
- prevent building older package versions
- removed obsolete build hooks
- daily/weekly cleanup: remove older package builds with configureable retention criteria
- support configureable git tag version prefixes (v1.0.0, release/1.0.0)
- use upstream aptly version
- build for bookworm
- make running litian configureable
- fix allow uploading external build for no adm64 architectures
- support mirriring flat repos
- improved dev environment using docker-compose and life reload servers for molior, altpy and web
- provide Admin page for configuration
- fix API documentation
- bugfixes and small improvement, cleanup
