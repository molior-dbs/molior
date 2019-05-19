#!/bin/sh

cd `dirname $0`

if [ ! -d sshkeys ]; then
  mkdir sshkeys
  chmod 700 sshkeys
  ssh-keygen -q -t rsa -N "" -f sshkeys/id_rsa
fi


