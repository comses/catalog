from django.apps import AppConfig
from elasticsearch_dsl.connections import connections


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        connections.create_connection(hosts=['elasticsearch:9200'], timeout=60, sniff_on_start=True,
                                      sniff_on_connection_fail=True, sniffer_timeout=60, sniff_timeout=10)
