#!/bin/sh

MOLIOR_SERVER=$1
APTLY_SERVER=$2
PROJECT_NAME=$3
PROJECT_VERSION=$4
DEPLOYMENT_TYPE=$5
EXPECTED_SUFFIX=$6
MOLIOR_TOOLS_VERSION=$7

set -x

mkdir -p molior-deploy-output
cd molior-deploy-output
sudo molior-deploy -L -c -v $DEPLOYMENT_TYPE -n testproject -m $MOLIOR_SERVER -a $APTLY_SERVER $PROJECT_NAME $PROJECT_VERSION
if [ "$?" -ne 0 ]; then
  echo Failed: Error running molior-deploy
  exit 1
fi

# the deployment by its type (*_installer.iso, *_vbox.ova, ...), not by the version in its name
set -- *$EXPECTED_SUFFIX
if [ ! -e "$1" ]; then
    echo Failed: No deployment \*$EXPECTED_SUFFIX
    exit 1
fi
if [ $# -ne 1 ]; then
    echo Failed: More than one deployment \*$EXPECTED_SUFFIX: "$@"
    exit 1
fi

echo
echo Success: File $1 exists
ls -l "$1"

exit 0
