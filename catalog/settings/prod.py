# Local Development Django settings for catalog
from .base import *

DEBUG = False

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Raven DSN access to sentry server, customize
RAVEN_CONFIG = {
    'dsn': 'https://public:secret@sentry.commons.asu.edu/4',
    # 'release': raven.fetch_git_sha(BASE_DIR),
}
