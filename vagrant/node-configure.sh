#!/bin/sh

set -e

# install SSH pub key from molior VM
cat /vagrant/vagrant/sshkeys/id_rsa.pub >> /home/vagrant/.ssh/authorized_keys

# make sure hostname is registered in DNS
ifdown eth0 2>/dev/null
ifup eth0 2>/dev/null

echo "Provisioning done!"
