import os
import pprint
import sys

import django

settings_environ = 'DJANGO_SETTINGS_MODULE'


def on_server_loaded(server_context):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "catalog.settings")
    sys.path.insert(2, '/code')
    pprint.pprint(sys.path)
    django.setup()
