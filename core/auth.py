import base64
import hashlib
import hmac
import json
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.encoding import force_bytes
from rest_framework import authentication, exceptions


TOKEN_TTL_SECONDS = 60 * 60 * 24
ALGORITHM = "HS256"


def _b64url_encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("utf-8")


def _b64url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload):
    return hmac.new(
        force_bytes(settings.SECRET_KEY),
        force_bytes(payload),
        hashlib.sha256,
    ).digest()


def generate_access_token(user):
    now = int(time.time())
    header = {"alg": ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": str(user.pk),
        "email": user.email,
        "is_staff": user.is_staff,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }

    encoded_header = _b64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = _b64url_encode(_sign(signing_input))
    return f"{signing_input}.{signature}"


def decode_access_token(token):
    parts = token.split(".")
    if len(parts) != 3:
        raise exceptions.AuthenticationFailed("Malformed token.")

    encoded_header, encoded_payload, encoded_signature = parts
    signing_input = f"{encoded_header}.{encoded_payload}"

    expected_signature = _b64url_encode(_sign(signing_input))
    if not hmac.compare_digest(expected_signature, encoded_signature):
        raise exceptions.AuthenticationFailed("Invalid token signature.")

    try:
        payload = json.loads(_b64url_decode(encoded_payload))
    except (json.JSONDecodeError, ValueError) as exc:
        raise exceptions.AuthenticationFailed("Invalid token payload.") from exc

    exp = payload.get("exp")
    sub = payload.get("sub")
    if not exp or not sub:
        raise exceptions.AuthenticationFailed("Invalid token claims.")
    if int(time.time()) >= int(exp):
        raise exceptions.AuthenticationFailed("Token expired.")

    return payload


class BearerJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).decode("utf-8")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        payload = decode_access_token(parts[1])

        User = get_user_model()
        try:
            user = User.objects.get(pk=payload["sub"])
        except User.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("User no longer exists.") from exc

        if not user.is_active:
            raise exceptions.AuthenticationFailed("User is inactive.")

        return user, None
