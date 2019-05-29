# Production django settings for catalog
from .base import *

DEBUG = False

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config.get('email', 'EMAIL_HOST', fallback='smtp.sparkpostmail.com')
EMAIL_PORT = config.get('email', 'EMAIL_PORT', fallback='587')
EMAIL_HOST_USER = config.get('email', 'EMAIL_HOST_USER', fallback='SMTP_Injection')
EMAIL_HOST_PASSWORD = config.get('email', 'EMAIL_HOST_PASSWORD', fallback='')
EMAIL_SUBJECT_PREFIX = config.get('email', 'EMAIL_SUBJECT_PREFIX', fallback='[comses.net]')
EMAIL_USE_TLS = True
