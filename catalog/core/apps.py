from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'catalog.core'

    def ready(self):
        from . import search_sync  # noqa: F401
