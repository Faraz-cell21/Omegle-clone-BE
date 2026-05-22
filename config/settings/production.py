from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False

_secret = os.getenv("DJANGO_SECRET_KEY", "").strip()  # noqa: F405
if not _secret:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
SECRET_KEY = _secret

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")  # noqa: F405
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")  # noqa: F405
if not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("CORS_ALLOWED_ORIGINS must be set in production.")

CSRF_TRUSTED_ORIGINS = env_list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS",
    ",".join(CORS_ALLOWED_ORIGINS),
)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.StrictCorsMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]

# Never allow test/load bypass flags in production.
TURNSTILE_BYPASS = False
LOAD_TEST_BYPASS_LIMITS = False

# HTTPS (set SECURE_SSL_REDIRECT=False behind local TLS-terminating proxy in dev-staging if needed).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", "True")  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")  # noqa: F405
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", "True")  # noqa: F405
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),  # noqa: F405
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
