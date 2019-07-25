<div align="center"><img src="doc/img/moliorlogo_large.png"/><p>Debian Build System</p></div>

# Purpose

The purpose of molior is to build Debian packages out of git repositories based on a mirror of a specific Debian version
and with that paving the way for reproducible builds. Build environments are structured into projects and versions,
which may include mirrors and versions of other projects.

Molior performs the following tasks:
- create mirrors of Debian repositories
- create projects based on a Debian mirror, include dependencies to other projects or mirrors
- build packages into project repositories (i386, amd64, armhf, arm64)
- create deployments of projects (ISO Installer, VirtualBox, images, ...)

# Components

The molior Debian Build System consists of the following components:

- molior-server
  - based on aiohttp
  - manages git repositories
  - manages project and versions
  - manages Debien repositories (aptly)
  - creates Debian source packages
  - provides REST API
  - provides build and deployment environments (schroot, debootstrap)
  - uses aptly REST API
  - uses PostgreSQL database
- molior-web
  - based on AngularJS, nodejs
  - uses molior REST API
- aptly
  - see http://aptly.info
  - manages Debian repository mirrors
  - manages Debian project repositories
  - provides REST API
  - contains molior specific API improvements
- molior-client
  - based on aiohttp
  - runs on build nodes
  - uses molior REST API
  - uses build environment
- molior-tools
  - create releases
  - create deployments
  - automation scripts


# Installation

Molior can be installed from APT sources, or with ISO installers.

## Prerequisites

Debian stretch installations with stretch-backports, depending on the setup:
- molior server machine
- aptly server machine (might be on the same installation as molior server)
- build node(s) (amd64 or arm64)

## APT Sources

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

## ISO Installers

Molior is available as ISO installer for test and development purposes.

Download molior and aptly server installer:
- http://molior.info/installers/molior_1.3_1.3.2_installer-dev.iso

Download amd64 build node installer:
- http://molior.info/installers/molior_1.3_1.3.2_installer-node-amd64.iso

Install molior server and build node on VMs or bare metal and follow the Configuration chapter below.

User and Password for these installers is: admin/molior-dev

In order to see the IP address aquired via DHCP, login in the text console and run:
```
ip addr show eth0
```

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

# Usage

## Login to the Web UI

Point your browser to the URL of the molior server, login with admin and the password defined in /etc/molior/molior/yml.

## Creating Mirrors

### Use apt-cacher-ng (optional)

Install apt-cacher-ng in order to speed up mirroring.

For mirroring stretch, you might want to add the following to /etc/apt-cacher-ng/acng.conf:
```
PfilePatternEx: \.asc$
```

### Debian base mirror

The following will mirror Debian/stretch for amd64 and arm64. It will take approx. 73GB of disk space.

- Click on Mirror, New Mirror
- Name: stretch
- Version: 9.9
- Continue
- Check: Basemirror
- UnCheck: Mirror Source
- Uncheck: Mirror Installer
- Distribution: stretch
- Select Architectures: amd64, arm64
- Components: main
- Source: http://httpredir.debian.org/debian (or use apt-cacher-ng URL)
- Select: Use Mirror Key
- Continue
- Add the three keys (separately): EF0F382A1A7B6500 8B48AD6246925553 7638D0442B90D010
- Key Server: hkp://keyserver.ubuntu.com:80
- Confirm

Depending on the network and disk performance, this might take a 2-3 hours.

Note: if you are mirroring Debian/buster use these keys: 04EE7237B7D453EC 648ACFD622F3D138 DCC9EFBF77E11517)

## Create a project


- Name: test
- Click new
- Project Version: 1.0
- Choose base mirror
- Choose amd64, arm64 arhcitecutres

## Add a source repo

- Click project: test
- Click project version: 1.0
- Click Repositories
- Click NEW REPOSITORY
- URL: https://github.com/neolynx/sold.git
- Click Continue
- Click Continue

## Create a non-base mirror (optional)

Molior can create mirror of APT repositories, for example mono:

```
Name: mono
Version: 5.2
Dist: stretch
Archs: amd64
Source: http://download.mono-project.com/repo/debian
Keys: 3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF
Key Server: hkp://keyserver.ubuntu.com:80
```

or Docker:

```
Name: docker
Version: 17.09
Dist: stretch
Archs: amd64
Mirror source packages: no
Base mirror: no
Components: stable
Source: https://download.docker.com/linux/debian
Key URL: https://download.docker.com/linux/debian/gpg
```


## Integration

### Tigger builds from gitlab

In GitLab:
- Go to Settings/Integrations (or Administration/System-Hooks)
- Enter URL: http://moliorserver/api/build/gitlab (replace with your molior instance)
- Choose secret token id authenticated triggers are desired
  - Configure secret token in /etc/molior/molior/yml (gitlab/auth_token)
- Select "Push events" if CI builds are desired
- Select "Tag push events"

### Build notification hooks

Molior can trigger a REST API when build states change.

```
    POST https://remoteserver/api/{{build.commit|urlencode}}

    {
        "key":"molior-{{platform.distrelease}}-{{platform.version}}-{{platform.architecture}}-{{project.name}}-{{project.version}}",

        "name":"Molior {{platform.architecture}} / {{platform.version}} / {{platform.distrelease}} Build for {{build.commit}}",
        {% if build.status == "building" %}
        "state":"INPROGRESS",
        {% elif build.status == "successful" %}
        "state":"SUCCESSFUL",
        {% else %}
        "state":"FAILED",
        {% endif %}
        "description":"{{build.status}}",
        "url":"{{build.url}}"
    }
```

# Contributing

You are welcome to contribute to the project !

- Feel free to open issues with questions, suggestions and improvements
- Pull requests are welcome, please consider the following:
    - Follow the rules of [PEP8](http://legacy.python.org/dev/peps/pep-0008/)
    - Use [Google docstrings](http://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html). (for automated docs generation)
    - Make changes backward compatible and upgradeable (especially the database changes)
    - Unit test the changes, whenever possible

The following chapters describe how to setup a development environment.
For building Debian packages in molior, the creation of a Debian mirror is required. This needs approximately 80GB of free disk space.

## Clone the source repositories

The following source respositories are needed:

```shell
mkdir molior-dev
cd molior-dev
git clone https://github.com/molior-dbs/molior.git
git clone https://github.com/molior-dbs/molior-web.git
git clone https://github.com/molior-dbs/aptlydeb.git

git clone https://github.com/neolynx/launchy.git
git clone https://github.com/neolynx/cirrina.git
git clone https://github.com/neolynx/aiohttp_jrpc.git
git clone https://github.com/neolynx/aiohttp-session.git
git clone https://github.com/neolynx/aiohttp-swagger.git

cd aptlydeb
git submodule init
git submodule update
cd ..
```

## Create a development environment

The molior development environment currently consists of two LXC containers managed by vagrant (>= 2.0.0):
- node (build node i386/amd64)
- molior (molior server, aptly server)

The source repositories cloned above will be mounted into the vagrant machines (via bind mounts). They will be built and installed with the steps below.

- Apparmor and LXC might need to be configured depending on your distribution. The following chapters describe the configuration for the supported distributions.

### Debian stretch

On Debian stretch make sure the stretch-backports APT source is available and perform the following steps:
- Make sure the following packages are installed:

```shell
sudo apt-get install vagrant/stretch-backports apparmor lxc lxc-templates ruby-dev
```

- Download the LXC vagrant image (from the molior source code directory):
```shell
cd molior
vagrant box update
```

- Edit the following file accordignly (rename utsname, uncomment selinux line):
~/.vagrant.d/boxes/debian-VAGRANTSLASH-stretch64/9.1.0/lxc/lxc-config
```
...
# Container specific configuration
lxc.tty.max = 4
lxc.utsname = stretch-base
lxc.arch = amd64
#lxc.selinux.context = unconfined_u:unconfined_r:lxc_t:s0-s0:c0.c1023
```

- Create a LXC default network by creating the following file:
/etc/lxc/default.conf
```
lxc.network.type = empty
lxc.network.type = veth
lxc.network.link = lxcbr0
lxc.network.flags = up
lxc.network.hwaddr = 00:16:3e:xx:xx:xx
```

### Ubuntu 18.04

On Ubuntu 18.04 perform the following steps:
- Make sure the following packages are installed:

```shell
sudo apt-get install vagrant apparmor lxc lxc-templates ruby-dev
```

- Add the following configuration to /etc/apparmor.d/lxc/lxc-default-cgns:
```
profile lxc-container-default-cgns flags=(attach_disconnected,mediate_deleted) {
[...]

  # molior vagrant-lxc
  mount options=(rw,private), # schroot /sys
  mount options=(rw,bind),    # schroot /proc
  mount options=(rw,rbind),   # timedatectl
  mount options=(rw,rslave),  # timedatectl
  mount options=(ro,remount,noatime,nodiratime,bind),  # timedatectl
  mount options=(ro,remount,bind),  # timedatectl
  mount options=(ro,nosuid,nodev,remount,bind),  # timedatectl
  mount options=(ro,nosuid,nodev,noexec,remount,bind),  # timedatectl
  mount options=(rw,rshared),  # timedatectl

}
```

- Reload apparmor:
```shell
sudo service apparmor reload
```

### Ubuntu 19.04 Vagrant fixes

On Ubuntu 19.04 perform the following steps:
- Make sure the following packages are installed:

```shell
sudo apt-get install vagrant apparmor lxc lxc-templates ruby-dev
```

- Fix the systemd networkd control of the Debian node in vagrant.

```shell
sudo vim /usr/share/rubygems-integration/all/gems/vagrant-2.2.3/plugins/guests/debian/cap/change_host_name.rb
```

- Set the nettools detection to systemd_networkd and cut the given interface name.

Change the first if statement and the first restart_command accordingly:
```ruby
        def self.restart_each_interface(machine, logger)
          comm = machine.communicate
          interfaces = VagrantPlugins::GuestLinux::Cap::NetworkInterfaces.network_interfaces(machine)
          nettools = true
          if systemd_networkd?(comm)
            @logger.debug("Attempting to restart networking with systemctl")
            nettools = false
          else
            @logger.debug("Attempting to restart networking with ifup/down nettools")
          end

          interfaces.each do |iface|
            logger.debug("Restarting interface #{iface} on guest #{machine.name}")
            if nettools
             restart_command = "ifdown #{iface[/[^@]+/]};ifup #{iface[/[^@]+/]}"
            else
             restart_command = "systemctl stop ifup@#{iface}.service;systemctl start ifup@#{iface}.service"
            end
            comm.sudo(restart_command)
          end
        end

```

## Create the vagrant machines

This will create two vagrant boxes, a build node and the molior server. It will also build and install all molior components.

```shell
cd molior
make
```

## Login to the molior machine
```
vagrant ssh molior
```

## Login to the Web UI

Point your browser to the URL shown after login.

## Build molior

The following command will build all molior components:
```
build
```

Alternatively the components can be built individually:
```
build molior-web # or molior, aptlydeb
```

## Demo Project
```
git clone https://github.com/molior-dbs/curitiba.git
```

## Watch the logs
```
log
```

## Toubleshooting

See output of aptly tasks:
```
wget -O- -q http://localhost:8000/api/tasks/11/output
```

# Authors

- André Roth
- Benjamin Fassbind
