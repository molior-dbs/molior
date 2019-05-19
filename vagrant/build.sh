#!/bin/sh

DOING="Initializing"
SUCCESS=0

log_info()
{
  DOING="$@"
  /bin/echo -e "\e[36m\e[1mI: $@ ...\e[0m"
}

log_notice()
{
  /bin/echo -e "\e[32m\e[1mN: $@\e[0m"
}

log_warn()
{
  /bin/echo -e "\e[33m\e[1mW: $@\e[0m"
}

log_error()
{
  /bin/echo -e "\e[31m\e[1mE: $@\e[0m"
  exit 1
}

if [ `id -u` -eq 0 ]; then
  log_error "$0: Do not run as root"
fi

set -e

exithandler() {
  if [ "$SUCCESS" -eq 0 ]; then
    log_error "$@ failed"
  fi
}

trap 'exithandler $DOING' EXIT

#set -E # allow ERR trap

PACKAGES=$@
if [ -z "$PACKAGES" ]; then
  PACKAGES="molior molior-web aptlydeb"
else
  # remove potential (trailing) / from cmdline
  PACKAGES=`echo $PACKAGES | tr -d /`
fi

log_info "Removing existing deb files"
cd
rm -f *.deb *.changes *.build

mkdir -p ~/.molior-client

if [ ! -e ~/.build_deps_installed ]; then
  log_info "Building and installing python dependencies"

  for p in aiohttp_jrpc aiohttp-session aiohttp-swagger cirrina launchy
  do
    if [ -d $p ]; then
      cd $p
      debuild -uc -us -b
      cd ..
      sudo dpkg -i *.deb

      if [ $p = "launchy" ]; then
        # save launchy for molior-client installation
        mv *.deb ~/.molior-client
      fi
      rm -f *.deb *.changes *.build
    fi
  done

	touch ~/.build_deps_installed
else
	log_notice "Not installing build deps, ~/.build_deps_installed exists"
fi

log_info "Building packages $PACKAGES"
for d in $PACKAGES
do
  log_info "Building $d"
  cd $d
    debuild -us -uc -b
  cd - >/dev/null
done

if echo $PACKAGES | sed 's/ /\n/g' | grep -q "^molior$"; then
  log_info "Installing molior-server package"
  sudo gdebi -n molior-backend-http*_all.deb
  sudo gdebi -n molior-server_*_all.deb
  sudo gdebi -n molior-doc_*_all.deb

  log_info "Installing molior client packages"
  rm -f ~/.molior-client/molior-client*_all.deb
  cp molior-client*_all.deb ~/.molior-client

  log_info "Creating signing key for .dsc and .changes files"
  sudo create-molior-keys "Molior Debsign" debsign@molior.info

  installed=0
  if sudo ping -c1 -q node1 2>/dev/null; then
    ssh -o StrictHostKeyChecking=no node1 "rm -f *.deb"
    scp -o StrictHostKeyChecking=no ~/.molior-client/* node1:
    ssh -o StrictHostKeyChecking=no node1 "sudo dpkg -i *.deb" || true
    ssh -o StrictHostKeyChecking=no node1 "sudo apt-get -f --yes install"
    installed=1

    if ! ssh -o StrictHostKeyChecking=no node1 "sudo -u molior grep -q molior@molior /var/lib/molior/.ssh/authorized_keys 2>/dev/null"; then
      log_info "install molior SSH pub key to build node"
      ssh -o StrictHostKeyChecking=no node1 "sudo mkdir -p /var/lib/molior/.ssh/"
      ssh -o StrictHostKeyChecking=no node1 "sudo chmod 700 /var/lib/molior/.ssh/"
      ssh -o StrictHostKeyChecking=no node1 "sudo chown -R molior:nogroup /var/lib/molior/.ssh/"
      sudo cat ~molior/.ssh/id_rsa.pub | ssh -o StrictHostKeyChecking=no node1 "sudo tee -a /var/lib/molior/.ssh/authorized_keys" > /dev/null
    fi

    log_info "install GPG pub key on build node"
    sudo -u molior gpg1 --armor --export debsign@molior.info | ssh -o StrictHostKeyChecking=no node1 "sudo -u molior gpg1 --import --no-default-keyring --keyring=trustedkeys.gpg"
  fi

  if [ "$installed" -eq 1 ]; then
    rm -f ~/.molior-client/*
  fi
fi

if echo $PACKAGES | sed 's/ /\n/g' | grep -q "^molior-web$"; then
  log_info "Installing molior-web package"
  sudo gdebi -n molior-web_*_all.deb
  log_info "Configuring molior-web package"
  sudo rm -f /etc/nginx/sites-enabled/default
  sudo service nginx reload
fi

if echo $PACKAGES | sed 's/ /\n/g' | grep -q "^aptlydeb$"; then
  log_info "Installing aptly package"
  sudo gdebi -n aptly_*_amd64.deb
  log_info "Configuring aptly"
  sudo create-aptly-passwd molior molior-dev 2>/dev/null
  sudo sed s/80/3142/ -i /etc/nginx/sites-enabled/aptly
  sudo service nginx restart
  log_info "Creating signing key for aptly repos"
  sudo create-aptly-keys "Molior Reposign" reposign@molior.info || true
fi


log_info "Cleanup"
rm -f *.deb *.changes *.build *.buildinfo

echo
SUCCESS=1
log_notice "Done !"
IP=`/sbin/ifconfig eth0 | grep "inet " | awk '{print $2}'`
echo
echo "===> WebUI: http://$IP/"
echo
