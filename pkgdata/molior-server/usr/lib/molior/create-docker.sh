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
target="/var/lib/molior/upload/dockerbase/$DEBOOTSTRAP_NAME"
DEBOOTSTRAP_TAR="/var/lib/molior/upload/dockerbase//$DEBOOTSTRAP_NAME.tar"

set -e
#set -x

build_docker()
{
  rm -f $DEBOOTSTRAP_TAR
  rm -rf $target
  mkdir -p $target

  echo
  message="Creating docker base $DEBOOTSTRAP_NAME"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  printf "| %-44s %s |\n" "$message" "`date -R`"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  echo

  echo I: Using APT repository $REPO_URL

  if [ -n "$COMPONENTS" ]; then
      COMPONENTS="--components main,$COMPONENTS"
  fi

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

  rm -rf $target/
  echo I: Debootstrapping $DIST_RELEASE/$ARCH from $REPO_URL
  if [ "$ARCH" = "armhf" -o "$ARCH" = "arm64" ]; then
    debootstrap --foreign --arch $ARCH --variant=buildd --keyring=/root/.gnupg/trustedkeys.gpg $INCLUDE $COMPONENTS $DIST_RELEASE $target $REPO_URL
    if [ "$ARCH" = "armhf" ]; then
      cp /usr/bin/qemu-arm-static $target/usr/bin/
    else
      cp /usr/bin/qemu-aarch64-static $target/usr/bin/
    fi
    chroot $target /debootstrap/debootstrap --second-stage --no-check-gpg
  else
    debootstrap --variant=buildd --arch $ARCH --keyring=/root/.gnupg/trustedkeys.gpg $INCLUDE $COMPONENTS $DIST_RELEASE $target $REPO_URL
  fi

  echo I: Configuring chroot
  echo 'APT::Install-Recommends "false";' >$target/etc/apt/apt.conf.d/77molior
  echo 'APT::Install-Suggests "false";'  >>$target/etc/apt/apt.conf.d/77molior
  echo 'APT::Acquire::Retries "3";'      >>$target/etc/apt/apt.conf.d/77molior
  echo 'Acquire::Languages "none";'      >>$target/etc/apt/apt.conf.d/77molior

  # Disable debconf questions so that automated builds won't prompt
  echo set debconf/frontend Noninteractive | chroot $target debconf-communicate
  echo set debconf/priority critical | chroot $target debconf-communicate

  # Disable daemons in chroot:
  cat >> $target/usr/sbin/policy-rc.d <<EOM
#!/bin/sh
while true; do
    case "\$1" in
      -*) shift ;;
      makedev) exit 0;;
      x11-common) exit 0;;
      *) exit 101;;
    esac
done
EOM
  chmod +x $target/usr/sbin/policy-rc.d

  # Set up expected /dev entries
  if [ ! -r $target/dev/stdin ];  then ln -s /proc/self/fd/0 $target/dev/stdin;  fi
  if [ ! -r $target/dev/stdout ]; then ln -s /proc/self/fd/1 $target/dev/stdout; fi
  if [ ! -r $target/dev/stderr ]; then ln -s /proc/self/fd/2 $target/dev/stderr; fi

  echo I: Adding gpg public keys to chroot
  for keyfile in $keydir/*
  do
    name=`basename $keyfile .asc`
    mv $keyfile $keydir/$name
    gpg --dearmour $keydir/$name
    mv $keydir/$name.gpg $target//etc/apt/trusted.gpg.d/
  done
  rm -rf $keydir

  echo I: Installing build environment
  cp /etc/hosts $target/etc/hosts  # needed if host.docker.internal is used
  chroot $target apt-get update
  chroot $target apt-get -y --force-yes install build-essential fakeroot eatmydata libfile-fcntllock-perl lintian devscripts curl git
  chroot $target apt-get clean
  rm -f $target/etc/hosts
  rm -f $target/var/lib/apt/lists/*Packages* $target/var/lib/apt/lists/*Release*

  mkdir $target/app
  chroot $target useradd -m --shell /bin/sh --home-dir /app build
  cp -a /usr/lib/molior/build-docker $target/app/
  cp -a /usr/lib/molior/find-package-dir.pl $target/app/
  cp -a /usr/lib/molior/dsc-get-files.pl $target/app/

  echo I: Created docker base successfully
}

publish_docker()
{
  rm -f $DEBOOTSTRAP_TAR

  echo I: Compressing docker base image
  cd $target
  tar -cf $DEBOOTSTRAP_TAR .
  cd - > /dev/null
  rm -rf $target

  CONTAINER_NAME=molior
  CONTAINER_VERSION=$DIST_VERSION-$ARCH

  echo I: Importing docker base image
  su molior -c "docker import $DEBOOTSTRAP_TAR $CONTAINER_NAME:$CONTAINER_VERSION"
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
      echo "$DOCKER_PASSWORD" | su molior -c "docker login --username $DOCKER_USER --password-stdin $REGISTRY"
  fi
  su molior -c "docker tag $CONTAINER_NAME:$CONTAINER_VERSION $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION"
  echo I: Publishing docker base image
  su molior -c "docker push $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION"
  su molior -c "docker rmi $CONTAINER_NAME:$CONTAINER_VERSION $REGISTRY/$CONTAINER_NAME:$CONTAINER_VERSION"
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
    rm -rf $target $DEBOOTSTRAP_TAR
    ;;
  *)
    echo "Unknown action $ACTION"
    exit 1
    ;;
esac
