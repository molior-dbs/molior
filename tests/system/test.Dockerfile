# molior image for system tests: used instead of molior:dev in the test namespace.
# Same as docker/molior/molior-dev.Dockerfile (build and install the molior deb packages from the working copy),
# plus python test and coverage tools, and server-side coverage collection.
#
# Built by tests/system/system-tests.sh. By hand (from the repo root, needs molior-base:dev from `make docker-images-molior`):
#   docker build -f tests/system/test.Dockerfile -t molior-test:dev .
#
# Coverage: every python process that imports molior records coverage when COVERAGE_PROCESS_START is set
# (default below; `su molior -c` in start-molior keeps the environment). The data goes to
# /var/lib/molior/coverage (molior volume, survives a container restart, coverage creates the directory);
# it is written when the process exits (SIGTERM included). Collect it with:
#   python3 -m coverage combine && python3 -m coverage report   (with --rcfile=/etc/molior/coveragerc, as user molior)
# Set COVERAGE_PROCESS_START to an empty value to turn it off.
FROM molior-base:dev

RUN groupadd --system --gid 5432 postgres
RUN useradd --uid 5432 --system --home-dir /var/lib/postgresql --no-create-home --shell /bin/bash --gid 5432 --comment "PostgreSQL administrator" postgres

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

ADD docker/molior/start-molior /usr/local/sbin/start-molior

COPY . /work/src
WORKDIR /work/src

# Build debian package
RUN dpkg-buildpackage -us -uc -b

# molior packages, and the test tools (pytest, coverage and pytest-cov come with molior-base as build dependencies)
RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && \
    apt-get install -y --no-install-recommends /work/molior-server*deb /work/molior-common*deb \
        python3-coverage python3-pytest python3-pytest-cov python3-pytest-xdist python3-pytest-timeout \
        python3-requests python3-httpx python3-websockets && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /work
RUN ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker
RUN rm /etc/molior/mirror-hooks.d/01-create-chroot

# Server-side coverage: a .pth file starts coverage in every python process when COVERAGE_PROCESS_START is set.
# Only the installed molior package is measured; parallel mode gives one data file per process.
RUN printf '%s\n' \
        '[run]' \
        'source = molior' \
        'parallel = true' \
        'sigterm = true' \
        'data_file = /var/lib/molior/coverage/.coverage' \
        '' \
        '[report]' \
        'show_missing = true' \
        > /etc/molior/coveragerc && \
    echo 'import coverage; coverage.process_startup()' > /usr/lib/python3/dist-packages/molior-coverage.pth
ENV COVERAGE_PROCESS_START=/etc/molior/coveragerc

WORKDIR /
CMD start-molior
