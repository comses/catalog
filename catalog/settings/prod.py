# Local Development Django settings for catalog
from .base import *

DEBUG = False
os.environ.setdefault('DB_USER', 'catalog')
os.environ.setdefault('DB_NAME', 'comses_catalog')
os.environ.setdefault('DB_HOST', 'db')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('SOLR_HOST', 'solr')
os.environ.setdefault('SOLR_PORT', '8983')
os.environ.setdefault('SOLR_CORE_NAME', 'catalog_core')

HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.solr_backend.SolrEngine',
        'URL': 'http://{0}:{1}/solr/{2}'.format(os.environ.get('SOLR_HOST'),
                                                os.environ.get('SOLR_PORT'),
                                                os.environ.get('SOLR_CORE_NAME'))
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': 'CHANGEME_CATALOG_DB_PASSWORD',
        'NAME': os.environ.get('DB_NAME'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT'),
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'customize this local secret key'

# Enter Zotero API key here
ZOTERO_API_KEY = None

# Raven DSN access to sentry server, customize
RAVEN_CONFIG = {
    'dsn': 'https://public:secret@sentry.commons.asu.edu/4',
    # 'release': raven.fetch_git_sha(BASE_DIR),
}
