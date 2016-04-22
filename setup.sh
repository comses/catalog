#!/usr/bin/env bash

export JAVA_HOME=/opt/jdk1.8.0_77/
SOLR_VERSION="6.0.0"
HOME=/home/vagrant

. $HOME/.virtualenvs/catalog/bin/activate
./solr-${SOLR_VERSION}/bin/solr start -noprompt

fab setup_solr
fab restore_from_dump
