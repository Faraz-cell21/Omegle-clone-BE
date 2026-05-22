from .base import *  # noqa: F403

DEBUG = True

SECRET_KEY = os.getenv(  # noqa: F405
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me",
)

ALLOWED_HOSTS = env_list(  # noqa: F405
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1",
)

CSRF_TRUSTED_ORIGINS = env_list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:3002,http://127.0.0.1:3002",
)

# Dev-only: allow any origin (do not use in production).
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.AllowAllCorsMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

TURNSTILE_BYPASS = env_bool("TURNSTILE_BYPASS", "False")  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
