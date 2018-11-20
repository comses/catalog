from django.apps import AppConfig
from django.conf import settings
from elasticsearch_dsl.connections import connections


class CoreConfig(AppConfig):
    name = 'catalog.core'

    def ready(self):
        connections.configure(**settings.ELASTICSEARCH)
