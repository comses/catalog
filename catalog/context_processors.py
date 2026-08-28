from django.conf import settings


def debug(context):
    return {'DEBUG': settings.DEBUG}


def sentry_public_dsn(context):
    """Expose optional browser Sentry configuration to templates."""
    return {
        'sentry_public_dsn': getattr(settings, 'SENTRY_PUBLIC_DSN', ''),
        'release_version': getattr(settings, 'RELEASE_VERSION', ''),
    }
