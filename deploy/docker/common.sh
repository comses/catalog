#!/bin/sh

LOCAL_PY_TEMPLATE=${1-"/code/catalog/settings/local.py.example"}
LOCAL_PY="/code/catalog/settings/local.py"


sleep 10;
sh /code/deploy/solr/config.sh
if [ ! -f $LOCAL_PY ]; then
    echo "Copying $LOCAL_PY_TEMPLATE to $LOCAL_PY"
    cp -p $LOCAL_PY_TEMPLATE $LOCAL_PY
fi
