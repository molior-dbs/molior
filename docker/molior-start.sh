#!/bin/sh

if [ -z "$DEBSIGN_EMAIL" ]; then
    DEBSIGN_EMAIL=debsign@molior.info
fi

if [ -z "$DEBSIGN_NAME" ]; then
    DEBSIGN_NAME="Molior Debsign"
fi

create-molior-keys $DEBSIGN_NAME $DEBSIGN_EMAIL
su molior -c "gpg --armor --export $DEBSIGN_EMAIL | gpg --import --no-default-keyring --keyring=trustedkeys.gpg"

sed -i 's/127.0.0.1/molior/' /etc/molior/molior.yml
sed -i "s/\( \+apt_url: \).*/\1'http:\/\/aptly:3142'/" /etc/molior/molior.yml
sed -i "s/\( \+api_url: \).*/\1'http:\/\/aptly:8080\/api'/" /etc/molior/molior.yml
sed -i "s/\(debsign_gpg_email: \).*/\1'$DEBSIGN_EMAIL'/" /etc/molior/molior.yml
sed -i "s/\( \+pass: \).*/\1'$MOLIOR_ADMIN_PASSWD'/" /etc/molior/molior.yml
sed -i "s#.*apt_url_public: .*#    apt_url_public: '$APTLY_PUBLIC_URL'#" /etc/molior/molior.yml
sed -i "s/\( \+gpg_key: \).*/\1'$REPOSIGN_EMAIL'/" /etc/molior/molior.yml
sed -i "s/\( \+api_user: \).*/\1'$APTLY_USER'/" /etc/molior/molior.yml
sed -i "s/\( \+api_pass: \).*/\1'$APTLY_PASS'/" /etc/molior/molior.yml

# wait a bit for database and aptly
sleep 5

/usr/lib/molior/db-upgrade.sh
su molior -c "/usr/bin/python3 -m molior.molior.server --host=molior --port=8888"
