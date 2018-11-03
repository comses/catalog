import os
import sys

import django


def on_server_loaded(server_context):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "catalog.settings.dev")
    sys.path.insert(2, '/code')
    sys.path.insert(3, os.path.dirname(os.path.abspath(__file__)))
    django.setup()
    import data_access
