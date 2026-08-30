from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'catalog.core'

    # No Elasticsearch wiring at startup: the ES8 client is built lazily
    # on first use from ``settings.ELASTICSEARCH`` (see
    # ``catalog.core.search_indexes.get_es_client``).
