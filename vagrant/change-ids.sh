#!/bin/sh

set -e

if [ -z "$1" ]; then
  echo No user ID specified
  exit 1
fi

if [ -z "$2" ]; then
  echo No group ID specified
  exit 1
fi

# change vagrant user ID to make bind mounts writable
sed -i "s/^vagrant:x:1000:1000/vagrant:x:$1:$2/" /etc/passwd
sed -i "s/^vagrant:x:1000:/vagrant:x:$2/" /etc/group
chown -R $1:$2 /home/vagrant
