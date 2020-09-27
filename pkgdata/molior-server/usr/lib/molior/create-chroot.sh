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
DEBSIGN_GPG_EMAIL=$debsign_gpg_email

# Workaround obsolete pxz package on buster
xzversion=`dpkg -s xz-utils | grep ^Version: | sed 's/^Version: //'`
if dpkg --compare-versions "$xzversion" lt 5.2.4-1; then
  TAR_PXZ="-Ipxz"
else
  TAR_PXZ=""
fi


if [ "$1" != "info" -a "$#" -lt 5 ]; then
  echo "Usage: $0 build|publish|remove <distrelease> <name> <version> <architecture> [components,]" 1>&2
  echo "       $0 info" 1>&2
  exit 1
fi

ACTION=$1
DIST_RELEASE=$2
DIST_NAME=$3
DIST_VERSION=$4
ARCH=$5
COMPONENTS=$6

CHROOT_NAME="${DIST_NAME}-$DIST_VERSION-${ARCH}"
target="/var/lib/schroot/chroots/${CHROOT_NAME}"

set -e

build_chroot()
{
  rm -f $target.tar.xz
  mkdir -p "$target"

  echo
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  message="Creating schroot $CHROOT_NAME"
  printf "| %-44s %s |\n" "$message" "`date -R`"
  echo "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
  echo

  REPO="$APTLY/$DIST_NAME/$DIST_VERSION/"
  echo I: Using APT repository $REPO

  if [ -n "$COMPONENTS" ]; then
      COMPONENTS="--components main,$COMPONENTS"
  fi
  INCLUDE="--include=gnupg1"
  KEY_URL=`echo $APTLY/$APTLY_KEY | sed 's/ //g'`
  echo I: Downloading gpg public key: $KEY_URL
  keyfile=`mktemp /tmp/molior-repo.asc.XXXXXX`
  wget -q $KEY_URL -O $keyfile
  cat $keyfile | flock /root/.gnupg.molior gpg --import --no-default-keyring --keyring=trustedkeys.gpg

  rm -rf $target/
  echo I: Debootstrapping $DIST_RELEASE/$ARCH from $REPO
  if [ "$ARCH" = "armhf" -o "$ARCH" = "arm64" ]; then
    debootstrap --foreign --arch $ARCH --variant=buildd --keyring=/root/.gnupg/trustedkeys.gpg $INCLUDE $COMPONENTS $DIST_RELEASE $target $REPO
    if [ "$ARCH" = "armhf" ]; then
      cp /usr/bin/qemu-arm-static $target/usr/bin/
    else
      cp /usr/bin/qemu-aarch64-static $target/usr/bin/
    fi
    chroot $target /debootstrap/debootstrap --second-stage --no-check-gpg
  else
    debootstrap --variant=buildd --arch $ARCH --keyring=/root/.gnupg/trustedkeys.gpg $INCLUDE $COMPONENTS $DIST_RELEASE $target $REPO
  fi

  echo I: Configuring chroot
  echo 'APT::Install-Recommends "false";' >$target/etc/apt/apt.conf.d/77molior
  echo 'APT::Install-Suggests "false";'  >>$target/etc/apt/apt.conf.d/77molior
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

  echo I: Adding gpg public key to chroot
  # Add APT Repo signing key
  cat $keyfile | chroot $target apt-key add - >/dev/null
  cat $keyfile | chroot $target gpg1 -q --import --no-default-keyring --keyring=trustedkeys.gpg
  # Add Molior Source signing key
  su molior -c "gpg1 --export --armor $DEBSIGN_GPG_EMAIL" | chroot $target gpg1 --import --no-default-keyring --keyring=trustedkeys.gpg

  echo I: Installing build environment
  chroot $target apt-get update
  chroot $target apt-get -y --force-yes install build-essential fakeroot eatmydata libfile-fcntllock-perl
  chroot $target apt-get clean

  rm -f $target/var/lib/apt/lists/*Packages* $target/var/lib/apt/lists/*Release*

  echo I: Creating schroot config
  CHROOT_D=/var/lib/schroot/chroots/chroot.d
  mkdir -p $CHROOT_D
  cat > $CHROOT_D/sbuild-$CHROOT_NAME <<EOM
[$CHROOT_NAME]
description=Molior $CHROOT_NAME schroot
type=directory
directory=$target
groups=sbuild
root-groups=sbuild
profile=sbuild
command-prefix=eatmydata
EOM

  echo I: schroot $target created
}

publish_chroot()
{
  rm -f $target.tar.xz

  echo I: Creating schroot tar
  cd $target
  tar $TAR_PXZ -cf ../$CHROOT_NAME.tar.xz .
  cd - > /dev/null
  rm -rf $target

  echo I: schroot $target is ready
}

case "$ACTION" in
  info)
    echo "schroot build environment"
    ;;
  build)
    build_chroot
    ;;
  publish)
    publish_chroot
    ;;
  remove)
    rm -rf $target $target.tar.xz
    ;;
  *)
    echo "Unknown action $ACTION"
    exit 1
    ;;
esac

