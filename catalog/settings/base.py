"""
Django settings for catalog project.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""
from __future__ import print_function

from pathlib import Path

import configparser
import logging
import os
import sys

from django.contrib.messages import constants as messages

DEBUG = False
config = configparser.ConfigParser()
config.read('/run/secrets/catalog_django_config')

# tweaking standard BASE_DIR because we're in the settings subdirectory.
BASE_DIR = os.path.dirname(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

# email configuration
DEFAULT_FROM_EMAIL = CATALOG_EMAIL = 'catalog@comses.net'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

ALLOWED_HOSTS = ('.comses.net', 'catalog.comses.net', 'localhost')
ADMINS = (
    ('CoMSES Net Admin', 'admin@comses.net'),
)
MANAGERS = ADMINS

DATA_DIR = 'data'

HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.solr_backend.SolrEngine',
        'URL': 'http://{0}:{1}/solr/{2}'.format(config.get('solr', 'HOST'),
                                                config.get('solr', 'PORT'),
                                                config.get('solr', 'CORE_NAME'))
    },
}

# Elasticsearch 8 endpoint: a single host:port derived from the
# environment (deployment injects these from the catalog secret). This
# endpoint is the inter-cluster cutover and rolls back independently by
# pointing it at the previous cluster. Sniffing is disabled: deployment
# owns cluster membership and the app must not reconfigure itself.
ELASTICSEARCH = {
    # The ES8 client requires a full URL (scheme://host:port). Deployments
    # may override the whole endpoint with ELASTICSEARCH_URL (e.g. from the
    # catalog secret) or compose it from ELASTICSEARCH_SCHEME/HOST/PORT.
    'hosts': [os.environ.get(
        'ELASTICSEARCH_URL',
        '{0}://{1}:{2}'.format(os.environ.get('ELASTICSEARCH_SCHEME', 'http'),
                               os.environ.get('ELASTICSEARCH_HOST', 'elasticsearch8'),
                               os.environ.get('ELASTICSEARCH_PORT', '9200')))
    ],
    'sniff_on_start': False,
    'sniff_on_node_failure': False,
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': config.get('db', 'HOST'),
        'NAME': config.get('db', 'NAME'),
        'PASSWORD': config.get('db', 'PASSWORD'),
        'PORT': config.get('db', 'PORT'),
        'USER': config.get('db', 'USER'),
    }
}

# Deliberate choice: citation's CitationConfig already opts its models into
# BigAutoField, and catalog.core defines no models, so this system default
# does not require any new migrations.
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://redis:6379/0",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

PIPELINE_COMPILERS = (
    'react.utils.pipeline.JSXCompiler',
)

# Haystack settings
HAYSTACK_SIGNAL_PROCESSOR = 'haystack.signals.RealtimeSignalProcessor'

HAYSTACK_SEARCH_RESULTS_PER_PAGE = 25

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'America/Phoenix'
USE_TZ = True

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = False

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.  Default is '/static/admin/'
# ADMIN_MEDIA_PREFIX = '/static/admin/'

# Salt used to generate token (SALT can remain public unlike SECRET_KEY)
SALT = '48&6uv*x'

LOGIN_REDIRECT_URL = '/curator/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Zotero API Key
ZOTERO_API_KEY = None

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.static',
                "django.template.context_processors.tz",
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'catalog.context_processors.debug',
                'catalog.context_processors.sentry_public_dsn',
            ],
        },
    },
]

MIDDLEWARE = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_cas_ng.middleware.CASMiddleware',
)

# FIXME: is Bokeh served in an iframe?
# X_FRAME_OPTIONS = 'DENY'

ROOT_URLCONF = 'catalog.urls'
WSGI_APPLICATION = 'catalog.wsgi.application'
# cookie storage vs session storage of django messages
# MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

DJANGO_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
)

THIRD_PARTY_APPS = (
    'bootstrap3',
    'haystack',
    'rest_framework',
    'django_extensions',
    'django_cas_ng',
)

CATALOG_APPS = ('catalog.core.apps.CoreConfig', 'citation.apps.CitationConfig',)

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + CATALOG_APPS

# activation window
ACCOUNT_ACTIVATION_DAYS = 30

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    'django_cas_ng.backends.CASBackend',
)

# CAS settings (django-cas-ng; replaces the abandoned django-cas-client)
CAS_SERVER_URL = 'https://weblogin.asu.edu/cas/'
CAS_VERSION = '2'
CAS_IGNORE_REFERER = True
CAS_REDIRECT_URL = '/curator/dashboard/'
CAS_LOGOUT_COMPLETELY = True
CAS_FORCE_SSL_SERVICE_URL = True
# django-cas-ng equivalent of the old CAS_AUTO_CREATE_USER: only pre-existing
# local accounts may log in through CAS.
CAS_CREATE_USER = False
# Resolve the verified CAS username against the local username field
# case-insensitively.
CAS_LOCAL_NAME_FIELD = 'username__iexact'
# URL names used by django_cas_ng.middleware.CASMiddleware for admin-area
# redirects; mapped to the catalog's public CAS endpoints.
CAS_LOGIN_URL_NAME = 'cas_login'
CAS_LOGOUT_URL_NAME = 'logout'
# The old CAS_RESPONSE_CALLBACKS entry pointed at
# catalog.core.util.create_cas_user, a debug-log no-op, so no equivalent
# post-authentication callback is wired under django-cas-ng.

MESSAGE_TAGS = {
    messages.DEBUG: 'alert alert-light',
    messages.SUCCESS: 'alert alert-success',
    messages.INFO: 'alert alert-info',
    messages.WARNING: 'alert alert-danger',
    messages.ERROR: 'alert alert-danger'
}

# static files configuration, see https://docs.djangoproject.com/en/1.9/ref/settings/#static-files

STATIC_URL = '/static/'
STATIC_ROOT = '/catalog/static/'
STATICFILES_DIRS = (os.path.join(BASE_DIR, 'catalog', 'static').replace('\\', '/'),)

# Media file configuration (for user uploads etc) ####

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = '/var/www/catalog/uploads'

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = 'https://catalog.comses.net/uploads/'


def is_accessible(directory_path):
    return os.path.isdir(directory_path) and os.access(directory_path, os.W_OK | os.X_OK)


LOG_DIRECTORY = '/shared/catalog/logs'

if not is_accessible(LOG_DIRECTORY):
    try:
        os.makedirs(LOG_DIRECTORY)
    except OSError:
        print("Unable to create log directory %s, setting to relative path logs" % LOG_DIRECTORY, file=sys.stderr)
        LOG_DIRECTORY = 'logs'
        if not is_accessible(LOG_DIRECTORY):
            try:
                os.makedirs(LOG_DIRECTORY)
            except OSError:
                print("Couldn't create any log directory, startup will fail", file=sys.stderr)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    # Sentry is configured via sentry_sdk.init() (see SENTRY_DSN below); the
    # sentry-sdk logging integration captures ERROR-level records that reach
    # the root logger, replacing the old raven SentryHandler.
    'root': {
        'level': 'INFO',
        'handlers': ['catalog.file', 'console'],
    },
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s [%(name)s|%(funcName)s:%(lineno)d] %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'catalog.file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': os.path.join(LOG_DIRECTORY, 'catalog.log'),
            'backupCount': 6,
            'maxBytes': 10000000,
        },
    },
    'loggers': {
        'django.db.backends': {
            'level': 'ERROR',
            'handlers': ['catalog.file', 'console'],
            'propagate': False,
        },
        'pysolr': {
            'level': 'WARNING',
            'handlers': ['catalog.file', 'console']
        },
        # ERROR records from these loggers propagate to the root logger, where
        # the sentry-sdk logging integration captures them for Sentry (the
        # root's file/console handlers produce the same output as before).
        'catalog': {
            'level': 'DEBUG',
            'handlers': [],
            'propagate': True,
        },
        'citation': {
            'level': 'DEBUG',
            'handlers': [],
            'propagate': True,
        },
        'bokeh': {
            'level': 'DEBUG',
            'handlers': ['console'],
            'propagate': False,
        },
    }
}

# reset in local.py to enable more verbose logging (e.g.,
# DISABLED_TEST_LOGLEVEL = logging.NOTSET)
DISABLED_TEST_LOGLEVEL = logging.WARNING

# TEST_RUNNER = 'catalog.core.tests.runner.CatalogTestRunner'

# DJANGO REST Framework's Pagination settings
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 15
}

# Sentry (sentry-sdk replaces the abandoned client). The existing
# RAVEN_* keys in /run/secrets/catalog_django_config are read as-is so no
# deployment configuration changes are required; empty values simply leave
# the client uninitialized (a no-op).
SENTRY_DSN = config.get('django', 'RAVEN_PRIVATE_DSN', fallback='')
SENTRY_PUBLIC_DSN = config.get('django', 'RAVEN_PUBLIC_DSN', fallback='')

SECRET_KEY = config.get('django', 'SECRET_KEY')

AUDIT_ACCOUNT_USERNAME = config.get('django', 'AUDIT_ACCOUNT_USERNAME')

def get_release_version():
    release_version_file = Path('release-version.txt')
    if release_version_file.is_file():
        with release_version_file.open() as f:
            return f.read()
    return 'undefined'


RELEASE_VERSION = get_release_version()

# Initialize sentry-sdk at settings import (startup). Only initialize when a
# DSN is actually configured so local/test environments stay side-effect free.
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN)
