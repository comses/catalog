#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

CONFIG_INI=deploy/conf/config.ini
CONFIG_TEMPLATE_INI=deploy/conf/config.template.ini
POSTGRES_PASSWORD_FILE=deploy/conf/postgres_password

export DB_USER=catalog
export DB_NAME=comses_catalog
export DB_PASSWORD=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c60)
export SECRET_KEY=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c100)

if [ -f "$CONFIG_INI" ]; then
    echo $PWD
    echo "Config file config.ini already exists"
    echo "Replacing $CONFIG_INI will change the db password. Continue?"
    select response in "Yes" "No"; do
        case "${response}" in
            Yes) break;;
            No) echo "Aborting build"; exit;;
        esac
    done
    backup_name=config-backup-$(date '+%Y-%m-%d.%H-%M-%S').ini
    mv ${CONFIG_INI} ./deploy/conf/${backup_name}
    echo "Backed up old config file to $backup_name"
fi

echo "Creating config.ini"
cat "$CONFIG_TEMPLATE_INI" | envsubst > "$CONFIG_INI"
echo $DB_PASSWORD > ${POSTGRES_PASSWORD_FILE}

# docker-compose up -d db
# sleep 10;
# docker-compose exec db bash -c "psql -U ${DB_USER} -d ${DB_NAME} -c \"ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}'\""
echo "Change password by running % docker-compose exec db bash -c \"psql -U ${DB_USER} -d ${DB_NAME} -c \"ALTER USER ${DB_USER} WITH PASSWORD \'${DB_PASSWORD}\'\""

