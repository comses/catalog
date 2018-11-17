FROM comses/solr:6.6

COPY ./deploy/solr/conf /catalog-solr-conf
COPY ./deploy/solr/init.d/solr.in.sh /opt/solr/bin/solr.in.sh