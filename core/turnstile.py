import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from core.redis import redis_client

logger = logging.getLogger(__name__)

TURNSTILE_VERIFIED_TTL_SECONDS = 30 * 60
CAPTCHA_VERIFIED_KEY_PREFIX = "captcha:verified:"


class TurnstileVerificationError(Exception):
    pass


def is_turnstile_enforced() -> bool:
    if getattr(settings, "TURNSTILE_BYPASS", False):
        return False
    return bool(getattr(settings, "TURNSTILE_SECRET_KEY", ""))


def get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def captcha_verified_key(ip_address: str) -> str:
    return f"{CAPTCHA_VERIFIED_KEY_PREFIX}{ip_address}"


def mark_ip_captcha_verified(ip_address: str) -> None:
    if ip_address == "unknown":
        return
    redis_client.set(
        captcha_verified_key(ip_address),
        "1",
        ex=TURNSTILE_VERIFIED_TTL_SECONDS,
    )


def is_ip_captcha_verified(ip_address: str) -> bool:
    if not is_turnstile_enforced():
        return True
    if ip_address == "unknown":
        return False
    return bool(redis_client.exists(captcha_verified_key(ip_address)))


def verify_turnstile_token(token: str, remote_ip: str | None = None) -> bool:
    if getattr(settings, "TURNSTILE_BYPASS", False):
        logger.info("Turnstile verification bypassed via TURNSTILE_BYPASS")
        return True

    if not token:
        raise TurnstileVerificationError("Turnstile token is required")

    secret = getattr(settings, "TURNSTILE_SECRET_KEY", "")
    if not secret:
        logger.warning("TURNSTILE_SECRET_KEY not configured")
        raise TurnstileVerificationError("Turnstile verification not configured")

    data = {
        "secret": secret,
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        settings.TURNSTILE_VERIFY_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        logger.error("Turnstile verification request failed: %s", exc)
        raise TurnstileVerificationError("Failed to verify Turnstile token") from exc
    except Exception as exc:
        logger.error("Turnstile verification error: %s", exc)
        raise TurnstileVerificationError("Turnstile verification error") from exc

    if result.get("success", False):
        logger.info("Turnstile verification successful")
        return True

    error_codes = result.get("error-codes", [])
    logger.warning("Turnstile verification failed: %s", error_codes)
    raise TurnstileVerificationError(
        f"Turnstile verification failed: {', '.join(error_codes)}"
    )
