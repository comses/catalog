# Local Development Django settings for catalog
from .base import *

DEBUG = False

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

BOKEH_SERVE_SETTINGS = {
    'url': '/bokeh/visualization',
    'relative_urls': True
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'