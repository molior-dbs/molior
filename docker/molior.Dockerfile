FROM molior-base:dev

RUN groupadd --system --gid 5432 postgres
RUN useradd --uid 5432 --system --home-dir /var/lib/postgresql --no-create-home --shell /bin/bash --gid 5432 --comment "PostgreSQL administrator" postgres

RUN useradd --uid 7777 -m --shell /bin/sh --home-dir /var/lib/molior molior

ADD scripts/start-molior /usr/local/sbin/start-molior

COPY . /work/src
WORKDIR /work/src

# Build debian package
RUN dpkg-buildpackage -us -uc -b

RUN export DEBIAN_FRONTEND=noninteractive; apt-get install -y --no-install-recommends /work/molior-server*deb /work/molior-common*deb&& \
    apt-get clean && rm -rf /var/lib/apt/lists/* /work
RUN ln -s /usr/lib/molior/create-docker.sh /etc/molior/mirror-hooks.d/03-create-docker
RUN rm /etc/molior/mirror-hooks.d/01-create-chroot

WORKDIR /
CMD ["start-molior"]
