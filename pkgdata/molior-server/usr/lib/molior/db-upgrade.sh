#!/bin/sh

set -e

exec >&2

DB_NAME="molior"
DB_USER="molior"
DB_DIR="/usr/share/molior/database/"

if [ -n "$1" ]; then
    DB_DIR=$1
fi

if ! su postgres -c "psql -q -d $DB_NAME -l" >/dev/null 2>&1; then
    echo "Creating $DB_NAME database ..."
    su postgres -c "createuser $DB_USER"
    su postgres -c "psql -q -f $DB_DIR/$DB_NAME.db" >/dev/null
fi

while true
do
    found=0
    db_version=`su postgres -c "psql -q $DB_NAME -At -c \"select value from metadata where name = 'db_version';\""`
    new_version=`echo $db_version + 1 | bc`

    if [ $found -eq 0 ]; then
      echo "Found DB version $db_version"
    fi

    if [ -f "$DB_DIR/upgrade-$db_version.pre" ]; then
        found=1
        su postgres -c "$DB_DIR/upgrade-$db_version.pre" >/dev/null
    fi

    if [ -f "$DB_DIR/upgrade-$db_version" ]; then
        echo "Upgrating to DB version $new_version"
        found=1
        su postgres -c "$DB_DIR/upgrade-$db_version" >/dev/null
    fi

    if [ -f "$DB_DIR/upgrade-$db_version.post" ]; then
        found=1
        su postgres -c "$DB_DIR/upgrade-$db_version.post" >/dev/null
    fi

    if [ $found -eq 0 ]; then
        break
    fi
    su postgres -c "psql $DB_NAME -q -c \"UPDATE metadata SET value = '$new_version' WHERE name = 'db_version';\""
done
