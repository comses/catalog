# Local Development Django settings for catalog
from .base import *

DEBUG = False

HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.solr_backend.SolrEngine',
        'URL': 'http://localhost:8983/solr/catalog_core0'
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'comses_catalog',
        'USER': 'catalog',
        'PASSWORD': 'CUSTOMIZE_ME',
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'customize this local secret key'

# Enter Zotero API key here
ZOTERO_API_KEY = None

# Raven DSN access to sentry server, customize
RAVEN_CONFIG = {
    'dsn': 'https://public:secret@vcsentry.asu.edu/2',
    # 'release': raven.fetch_git_sha(BASE_DIR),
}
