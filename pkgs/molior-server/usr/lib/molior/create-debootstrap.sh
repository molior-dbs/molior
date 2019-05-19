#!/bin/bash

function parse_yaml {
   local prefix=$2
   local s='[[:space:]]*' w='[a-zA-Z0-9_]*' fs=$(echo @|tr @ '\034')
   sed -ne "s|^\($s\):|\1|" \
        -e "s|^\($s\)\($w\)$s:$s[\"']\(.*\)[\"']$s\$|\1$fs\2$fs\3|p" \
        -e "s|^\($s\)\($w\)$s:$s\(.*\)$s\$|\1$fs\2$fs\3|p"  $1 |
   awk -F$fs '{
      indent = length($1)/2;
      vname[indent] = $2;
      for (i in vname) {if (i > indent) {delete vname[i]}}
      if (length($3) > 0) {
         vn=""; for (i=0; i<indent; i++) {vn=(vn)(vname[i])("_")}
         printf("%s%s%s=\"%s\"\n", "'$prefix'",vn, $2, $3);
      }
   }'
}

CONFIG_FILE=/etc/molior/molior.yml

# Reads the config yaml and sets env variables
eval $(parse_yaml $CONFIG_FILE)
APTLY=$aptly__apt_url
APTLY_KEY=$aptly__key

if [ "$#" -ne 5 ]; then
  echo "Usage: $0 build|publish <distrelease> <name> <version> <architecture>" >&2
  exit 1
fi

ACTION=$1
DIST_RELEASE=$2
DIST_NAME=$3
DIST_VERSION=$4
ARCH=$5

DEBOOTSTRAP_NAME="${DIST_NAME}_${DIST_VERSION}_${ARCH}"
DEBOOTSTRAP="/var/lib/molior/debootstrap/${DEBOOTSTRAP_NAME}"

build_debootstrap()
{
  target="/var/lib/molior/debootstrap/${DIST_NAME}_${DIST_VERSION}_$ARCH"
  include="gnupg1"

  if [ -d $target ]; then
    rm -rf $target
  fi

  echo "I: Creating debootstrap for $DIST_RELEASE $DEBOOTSTRAP_NAME"

  MIRROR="$APTLY/$DIST_NAME/$DIST_VERSION/"

  echo " * running debootstrap for $DIST_NAME/$DIST_VERSION $ARCH"

  echo I: Using APT repository $MIRROR

  KEY_URL=`echo $APTLY/$APTLY_KEY | sed 's/ //g'`
  echo I: Downloading gpg public key: $KEY_URL
  wget -q $KEY_URL -O- | flock /root/.gnupg.molior gpg1 --import --no-default-keyring --keyring=trustedkeys.gpg

  if echo $ARCH | grep -q arm; then
    debootstrap --foreign --arch $ARCH --keyring=/root/.gnupg/trustedkeys.gpg --variant=minbase --include=$include $DIST_RELEASE $target $MIRROR
    if [ $? -ne 0 ]; then
      echo "debootstrap failed"
      exit 1
    fi
    if [ "$ARCH" = "armhf" ]; then
      cp /usr/bin/qemu-arm-static $target/usr/bin/
    else
      cp /usr/bin/qemu-aarch64-static $target/usr/bin/
    fi
    chroot $target /debootstrap/debootstrap --second-stage --no-check-gpg
    if [ $? -ne 0 ]; then
      echo "debootstrap failed"
      exit 2
    fi
  else
    debootstrap --arch $ARCH --keyring=/root/.gnupg/trustedkeys.gpg --variant=minbase --include=$include $DIST_RELEASE $target $MIRROR
    if [ $? -ne 0 ]; then
      echo "debootstrap failed"
      exit 3
    fi
  fi

  echo I: Configuring debootstrap
  if chroot $target dpkg -s > /dev/null 2>&1; then
    # The package tzdata cannot be --excluded in debootstrap, so remove it here
    # In order to use debconf for configuring the timezone, the tzdata package
    # needs to be installer later as a dependency, i.e. after the config package
    # preseeding debconf.
    chroot $target apt-get purge --yes tzdata
    rm -f $target/etc/timezone
  fi

  chroot $target apt-get clean

  rm -f $target/var/lib/apt/lists/*Packages* $target/var/lib/apt/lists/*Release*

  echo I: Created debootstrap successfully
}

publish_debootstrap()
{
  if [ -e "$DEBOOTSTRAP.tar.xz" ]; then
    echo "E: $DEBOOTSTRAP.tar.xz already exists; aborting" >&2
    exit 1
  fi

  echo I: Creating debootstrap tar
  cd $DEBOOTSTRAP
  tar -I pxz -cf ../$DEBOOTSTRAP_NAME.tar.xz .
  cd - > /dev/null
  rm -rf $DEBOOTSTRAP

  echo I: debootstrap $DEBOOTSTRAP is ready
}

case "$ACTION" in
  build)
    build_debootstrap
    ;;
  publish)
    publish_debootstrap
    ;;
  *)
    echo "Unknown action $ACTION"
    exit 1
    ;;
esac

