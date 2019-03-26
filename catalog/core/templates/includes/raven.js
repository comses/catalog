{% load raven %}

Raven.config('{% sentry_public_dsn %}').install();