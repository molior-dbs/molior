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
elif [ "$1" != "remove" -a "$#" -lt 4 ]; then
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
DEBOOTSTRAP_DIR="/var/lib/molior/upload/dockerbase/$DEBOOTSTRAP_NAME"
DEBOOTSTRAP_TAR="/var/lib/molior/upload/dockerbase/$DEBOOTSTRAP_NAME.tar"

set -e
#set -x

build_docker()
{
  target=$DEBOOTSTRAP_DIR

  if [ -d $target ]; then
    rm -rf $target
  fi
  mkdir -p $target

  echo
  message="Creating docker base $DEBOOTSTRAP_NAME"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  printf "| %-44s %s |\n" "$message" "`date -R`"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  echo

  echo " * running docker base for $DIST_NAME/$DIST_VERSION $ARCH"

  echo I: Using APT repository $REPO_URL

  if [ -n "$COMPONENTS" ]; then
      COMPONENTS="--components main,$COMPONENTS"
  fi
#  INCLUDE="--include=gnupg1"

  keydir=`mktemp -d /tmp/molior-chrootkeys.XXXXXX`
  i=1
  for KEY in $KEYS
  do
      if echo $KEY | grep -q '#'; then
          keyserver=`echo $KEY | cut -d# -f1`
          keyids=`echo $KEY | cut -d# -f2 | tr ',' ' '`
          echo I: Downloading gpg public key: $keyserver $keyids
          flock /root/.gnupg.molior gpg --no-default-keyring --keyring=trustedkeys.gpg --keyserver $keyserver --recv-keys $keyids
          gpg --no-default-keyring --keyring=trustedkeys.gpg --export --armor $keyids > "$keydir/$i.asc"
      else
          echo I: Downloading gpg public key: $KEY
          keyfile="$keydir/$i.asc"
          wget -q $KEY -O $keyfile
          cat $keyfile | flock /root/.gnupg.molior gpg --import --no-default-keyring --keyring=trustedkeys.gpg
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
    name=`basename $keyfile .asc`
    mv $keyfile $keydir/$name
    gpg --dearmour $keydir/$name
    mv $keydir/$name.gpg $target//etc/apt/trusted.gpg.d/
  done
  rm -rf $keydir

  echo I: Created docker base successfully
}

publish_docker()
{
  rm -f $DEBOOTSTRAP_TAR

  echo I: Compressing docker base image
  cd $DEBOOTSTRAP_DIR
  tar -cf $DEBOOTSTRAP_TAR .
  cd - > /dev/null
  rm -rf $DEBOOTSTRAP_DIR

  set -x

  CONTAINER_NAME=molior
  CONTAINER_VERSION=$DIST_VERSION

  echo I: Importing docker base image
  docker import $DEBOOTSTRAP_TAR $CONTAINER_NAME:$CONTAINER_VERSION
    if [ $? -ne 0 ]; then
      echo "docker import failed"
      exit 4
    fi

  rm -f $DEBOOTSTRAP_TAR

  REGISTRY=localhost:5000

  if [ -f /etc/molior/docker-registry.conf ]; then
      . /etc/molior/docker-registry.conf
  fi

  if [ -n "$DOCKER_USER" ]; then
      echo I: Logging in to docker registry $REGISTRY
      echo "$DOCKER_PASSWORD" | docker login --username $DOCKER_USER --password-stdin $REGISTRY
  fi
  docker tag $CONTAINER_NAME:$CONTAINER_VERSION $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION
  echo I: Publishing docker base image
  docker push $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION
  docker rmi $CONTAINER_NAME:$CONTAINER_VERSION $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION
  echo I: docker base $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION is published
}

case "$ACTION" in
  info)
    echo "docker base container for building"
    ;;
  build)
    build_docker
    ;;
  publish)
    publish_docker
    ;;
  remove)
    rm -rf $DEBOOTSTRAP_DIR $DEBOOTSTRAP_TAR
    ;;
  *)
    echo "Unknown action $ACTION"
    exit 1
    ;;
esac

