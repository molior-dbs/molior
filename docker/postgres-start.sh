#!/bin/sh

chown -R postgres:postgres /var/lib/postgresql/*

exec su postgres -c "exec /usr/lib/postgresql/11/bin/postgres -D /var/lib/postgresql/11/main -c config_file=/etc/postgresql/11/main/postgresql.conf"
