#!/bin/sh

set -e

exec >&2

MOLIOR_DB_NAME="molior"
MOLIOR_DB_USER="molior"

if ! su postgres -c "psql -q -d molior -l" >/dev/null 2>&1; then
    echo "Creating $MOLIOR_DB_NAME database ..."
    su postgres -c "createuser $MOLIOR_DB_USER"
    su postgres -c "psql -q -f /usr/share/molior/database/molior.db" >/dev/null
fi

while true
do
    found=0
    db_version=`su postgres -c "psql -q molior -At -c \"select value from metadata where name = 'db_version';\""`
    new_version=`echo $db_version + 1 | bc`

    if [ $found -eq 0 ]; then
      echo "Found DB version $db_version"
    fi

    if [ -f "/usr/share/molior/database/upgrade-$db_version.pre" ]; then
        found=1
        su postgres -c "/usr/share/molior/database/upgrade-$db_version.pre" >/dev/null
    fi

    if [ -f "/usr/share/molior/database/upgrade-$db_version" ]; then
        echo "Upgrating to DB version $new_version"
        found=1
        su postgres -c "/usr/share/molior/database/upgrade-$db_version" >/dev/null
    fi

    if [ -f "/usr/share/molior/database/upgrade-$db_version.post" ]; then
        found=1
        su postgres -c "/usr/share/molior/database/upgrade-$db_version.post" >/dev/null
    fi

    if [ $found -eq 0 ]; then
        break
    fi
    su postgres -c "psql molior -q -c \"UPDATE metadata SET value = '$new_version' WHERE name = 'db_version';\""
done
