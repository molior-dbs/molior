# CI image: molior-base (build dependencies of the deb packages: pytest, coverage, flake8, dpkg-buildpackage) plus the
# runtime python packages of molior-server that the unit tests import but the build does not need (FastAPI).
# The pipeline also uses it as molior-base:dev, the base of the molior images (they install molior-server, which
# depends on the same packages).
#
# Built by the "CI Image" job of .github/workflows/ci.yml. By hand (from the repo root):
#   docker build -f docker/molior/molior-base.Dockerfile -t molior-base:dev . && docker build -f docker/ci.Dockerfile -t molior-ci .
FROM molior-base:dev

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-fastapi python3-starlette python3-pydantic python3-python-multipart && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
