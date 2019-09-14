# Installation

Molior can be installed from APT sources, or with ISO installers.

Since molior is creating and using chroot environments (i.e. debootstrap, sbuild, schroot),
operation in a unpriviledged container (i.e. docker, lxd) is currently not supported.

<!-- vim-markdown-toc GFM -->

* [Prerequisites](#prerequisites)
* [Installation via APT sources](#installation-via-apt-sources)
    * [Debian buster](#debian-buster)
    * [Debian stretch](#debian-stretch)
    * [Configure APT](#configure-apt)
    * [Install molior](#install-molior)
    * [Install aptly](#install-aptly)
    * [Install build node](#install-build-node)
    * [Install molior-tools](#install-molior-tools)
* [ISO Installers / VMs](#iso-installers--vms)
    * [Debian buster](#debian-buster-1)
    * [Debian stretch](#debian-stretch-1)
* [Configuration](#configuration)
    * [Configure molior server](#configure-molior-server)
    * [Configure aptly server](#configure-aptly-server)
    * [Configure build nodes](#configure-build-nodes)

<!-- vim-markdown-toc -->

## Prerequisites

Debian stretch installations with stretch-backports, depending on the setup:
- molior server machine
- aptly server machine (might be on the same installation as molior server)
- build node(s) (amd64 or arm64)

## Installation via APT sources

### Debian buster

- Add the molior apt source:
```
cat >/etc/apt/sources.list.d/molior.list <<EOF
deb [arch=amd64,arm64] http://molior.info/1.3/buster stable main
EOF
```

### Debian stretch

- Make sure you have stretch-backports configured
```
cat >/etc/apt/sources.list.d/stretch-backports.list <<EOF
deb http://deb.debian.org/debian stretch-backports main
EOF
```
- Add the molior apt source:
```
cat >/etc/apt/sources.list.d/molior.list <<EOF
deb [arch=amd64,arm64] http://molior.info/1.3/stretch stable main
EOF
```

### Configure APT

- Add repository key
```
wget -q -O- http://molior.info/archive-keyring.asc | apt-key add -
```

- Update APT sources
```
apt update
```

### Install molior

```
apt install debootstrap/stretch-backports molior-server molior-web
```

### Install aptly

```
apt install aptly
```

### Install build node

On your build machines (amd64 or arm64), install molior-client-http:
```
apt install molior-client-http
```

### Install molior-tools

In your working environment (Debian/Ubuntu) configure the molior APT sources, and install:

```
apt install molior-tools
```

This will provide tools like:
- create-release
- molior-deploy

## ISO Installers / VMs

Molior is available as ISO installer for test and development purposes.

Install molior/aptly server and build node on VMs or bare metal and follow the Configuration chapter below.

User and Password for these installers is: admin/molior-dev

In order to see the IP address aquired via DHCP, login in the text console and run:
```
ip addr show eth0
```

### Debian buster

Download molior and aptly server installer:
- http://molior.info/installers/molior_1.3-buster_1.3.3_installer-dev.iso

Download molior and aptly server as VirtualBox Appliance:
- http://molior.info/installers/molior_1.3-buster_1.3.3_vbox-dev.ova

Download amd64 build node installer:
- http://molior.info/installers/molior_1.3-buster_1.3.3_iso-installer-node-amd64.iso

Download EFI installer for amd64 or arm64:
- http://molior.info/installers/molior_1.3-buster_1.3.3_efi-installer-node-amd64.iso
- http://molior.info/installers/molior_1.3-buster_1.3.3_efi-installer-node-arm64.iso

### Debian stretch

Download molior and aptly server installer:
- http://molior.info/installers/molior_1.3_1.3.3_installer-dev.iso

Download molior and aptly server as VirtualBox Appliance:
- http://molior.info/installers/molior_1.3_1.3.3_vbox-dev.ova

Download amd64 build node installer:
- http://molior.info/installers/molior_1.3_1.3.3_iso-installer-node-amd64.iso

Download EFI installer for amd64 or arm64:
- http://molior.info/installers/molior_1.3_1.3.3_efi-installer-node-amd64.iso
- http://molior.info/installers/molior_1.3_1.3.3_efi-installer-node-arm64.iso


## Configuration

### Configure molior server

- Login to the molior server via SSH
- Change password:
```
passwd
```
- Configure your timezone if needed:
```
sudo dpkg-reconfigure tzdata

# list postgresql timezones:
sudo -u postgres psql molior -c "SELECT * FROM pg_timezone_names"
# set molior database timezone:
sudo -u postgres psql molior -c "ALTER DATABASE molior SET timezone TO 'Europe/Zurich'"
sudo service molior-server restart
```
- Create SSH and GPG Keys
  Molior uses 2 GPG key pairs, one for signing the source package (molior user) and one for signing the Debian repositories (aptly user).
  These keys cannot easily be changes once Molior has created and signed mirrors and packages.
  If desired, create custom gpg key pairs accoring to what the scripts below perform, or use the provided scripts directly for testing purposes.
  These scripts also create SSH keys used by molior for accessing the git repositories and the build nodes.
```
sudo create-molior-keys "Molior Debsign" debsign@molior.info
sudo create-aptly-keys "Molior Reposign" reposign@molior.info
sudo create-aptly-passwd molior molior-dev
sudo service nginx reload
```
- Edit /etc/molior/molior.yml and configure:
  - hostname: the fqdn of the server or its IP address
  - debsign_gpg_email: the email provided to create-molior-keys above
  - admin/pass: set a new password
  - aptly/apt_url: URL of molior repository server
  - aptly/api_url: URL of aptly server
  - aptly API user and passwd
  - aptly/gpg_key: the email provided to create-aptly-keys above
- Remember the SSH public key of the molior user:
```
sudo -u molior cat ~molior/.ssh/id_rsa.pub
```
  This key needs to be added to the ~molior/.ssh/authorized_keys on the build nodes (see below), and the git repositories needs to grant read access to this key.

### Configure aptly server

If you run aptly on a separate machine, you might want to configure it:

- Login on a build node via SSH
- Change the password
- Change password:
```
passwd
```
- Configure your timezone if needed:
```
sudo dpkg-reconfigure tzdata
```

### Configure build nodes

- Login on a build node via SSH
- Change password:
```
passwd
```
- Configure your timezone if needed:
```
sudo dpkg-reconfigure tzdata
```
- Copy the molior SSH public key from the molior server to the molior user on each build machine
```
sudo -u molior mkdir ~molior/.ssh
sudo chmod 700 ~molior/.ssh
sudo -u molior sh -c "cat >~molior/.ssh/authorized_keys" <<EOF
(paste the SSH public key of the molior user from the molior server)
EOF
```

- Edit /etc/default/molior-client and set the MOLIOR_SERVER (i.e. hostname of the molior server).
- Restart the client service on the build node:
```
sudo service molior-client-http restart
```
- Export source signing public key to the build nodes
The build nodes need the public key which molior uses to sing the source packages. The build process will verify the signature of source packages.

From the molior server, execute the following for each build machine IP in order to add the gpg public key for source package verification (replace NODE_IPS, separated by blank):
```
DEBSIGN_KEY=debsign@molior.info
for molior_node in NODE_IPS
do
  sudo -u molior gpg1 --armor --export $DEBSIGN_KEY | sudo -u molior ssh -o StrictHostKeyChecking=no $molior_node "gpg1 --import --no-default-keyring --keyring=trustedkeys.gpg"
done
```


