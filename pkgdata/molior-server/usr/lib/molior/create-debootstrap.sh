#!/bin/bash

usage()
{
  echo "Usage: $0 build|publish|remove <distrelease> <name> <version> <architecture> components <mirror url> keys" 1>&2
  echo "       $0 info" 1>&2
  exit 1
}

if [ "$1" == "build" -a "$#" -lt 7 ]; then
  usage
elif [ "$1" != "publish" -a "$#" -lt 4 ]; then
  usage
fi

ACTION=$1
DIST_RELEASE=$2
DIST_NAME=$3
DIST_VERSION=$4
ARCH=$5
COMPONENTS=$6 # separated by comma
REPO_URL=$7
KEYS="$8"  # separated by space

DEBOOTSTRAP_NAME="${DIST_NAME}_${DIST_VERSION}_$ARCH"
DEBOOTSTRAP="/var/lib/molior/debootstrap/$DEBOOTSTRAP_NAME"

set -e

build_debootstrap()
{
  target=$DEBOOTSTRAP

  if [ -d $target ]; then
    rm -rf $target
  fi

  echo
  message="Creating debootstrap $DEBOOTSTRAP_NAME"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  printf "| %-44s %s |\n" "$message" "`date -R`"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  echo

  echo " * running debootstrap for $DIST_NAME/$DIST_VERSION $ARCH"

  echo I: Using APT repository $REPO_URL

  if [ -n "$COMPONENTS" ]; then
      COMPONENTS="--components main,$COMPONENTS"
  fi
  INCLUDE="--include=gnupg1"

  keydir=`mktemp -d /tmp/molior-chrootkeys.XXXXXX`
  i=1
  for KEY in $KEYS
  do
      if echo $KEY | grep -q '#'; then
          keyserver=`echo $KEY | cut -d# -f1`
          keyids=`echo $KEY | cut -d# -f2 | tr ',' ' '`
          echo I: Downloading gpg public key: $keyserver $keyids
          flock /root/.gnupg.molior gpg1 --no-default-keyring --keyring=trustedkeys.gpg --keyserver $keyserver --recv-keys $keyids
          gpg1 --no-default-keyring --keyring=trustedkeys.gpg --export --armor $keyids > "$keydir/$i.asc"
      else
          echo I: Downloading gpg public key: $KEY
          keyfile="$keydir/$i.asc"
          wget -q $KEY -O $keyfile
          cat $keyfile | flock /root/.gnupg.molior gpg1 --import --no-default-keyring --keyring=trustedkeys.gpg
      fi
      i=$((i + 1))
  done

  if echo $ARCH | grep -q arm; then
    debootstrap --foreign --arch $ARCH --keyring=/root/.gnupg/trustedkeys.gpg --variant=minbase $INCLUDE $COMPONENTS $DIST_RELEASE $target $REPO_URL
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
    debootstrap --arch $ARCH --keyring=/root/.gnupg/trustedkeys.gpg --variant=minbase $INCLUDE $COMPONENTS $DIST_RELEASE $target $REPO_URL
    if [ $? -ne 0 ]; then
      echo "debootstrap failed"
      exit 3
    fi
  fi

  echo I: Configuring debootstrap
  if chroot $target dpkg -s > /dev/null 2>&1; then
    # The package tzdata cannot be --excluded in debootstrap, so remove it here
    # In order to use debconf for configuring the timezone, the tzdata package
    # needs to be installed later as a dependency, i.e. after the config package
    # preseeding debconf.
    chroot $target apt-get purge --yes tzdata
    rm -f $target/etc/timezone
  fi

  chroot $target apt-get clean

  rm -f $target/var/lib/apt/lists/*Packages* $target/var/lib/apt/lists/*Release*

  echo I: Adding gpg public keys to chroot
  for keyfile in $keydir/*
  do
    cat $keyfile | chroot $target apt-key add - >/dev/null
  done
  rm -rf $keydir

  echo I: Created debootstrap successfully
}

publish_debootstrap()
{
  rm -f $DEBOOTSTRAP.tar.xz

  echo I: Creating debootstrap tar
  cd $DEBOOTSTRAP
  XZ_OPT="--threads=`nproc --ignore=1`" tar -cJf ../$DEBOOTSTRAP_NAME.tar.xz .
  cd - > /dev/null
  rm -rf $DEBOOTSTRAP

  echo I: debootstrap $DEBOOTSTRAP is ready
}

case "$ACTION" in
  info)
    echo "debootstrap minimal rootfs"
    ;;
  build)
    build_debootstrap
    ;;
  publish)
    publish_debootstrap
    ;;
  remove)
    rm -rf $DEBOOTSTRAP $DEBOOTSTRAP.tar.xz
    ;;
  *)
    echo "Unknown action $ACTION"
    exit 1
    ;;
esac

