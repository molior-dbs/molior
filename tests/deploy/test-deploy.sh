#!/bin/sh

MOLIOR_SERVER=$1
APTLY_SERVER=$2
PROJECT_NAME=$3
PROJECT_VERSION=$4
DEPLOYMENT_TYPE=$5
EXPECTED_SUFFIX=$6
MOLIOR_TOOLS_VERSION=$7

IMG_FILE=${PROJECT_NAME}_${PROJECT_VERSION}_3.0.12${EXPECTED_SUFFIX}

set -x

mkdir -p molior-deploy-output
cd molior-deploy-output
sudo molior-deploy -L -c -v $DEPLOYMENT_TYPE -n testproject -m $MOLIOR_SERVER -a $APTLY_SERVER $PROJECT_NAME $PROJECT_VERSION
if [ "$?" -ne 0 ]; then
  echo Failed: Error running molior-deploy
  exit 1
fi

if [ ! -e "$IMG_FILE" ]; then
    echo Failed: File $IMG_FILE does not exist
    exit 1
fi

echo
echo Success: File $IMG_FILE exists
ls -l $IMG_FILE

exit 0
