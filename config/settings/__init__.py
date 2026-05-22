import os

"""
Load settings by DJANGO_ENV:
  - development (default): local dev
  - production: deployed / staging with strict security
"""

_env = os.getenv("DJANGO_ENV", "development").strip().lower()

if _env == "production":
    from .production import *  # noqa: F403
else:
    from .development import *  # noqa: F403
