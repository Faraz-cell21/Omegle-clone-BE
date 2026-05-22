from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.db import connection
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.auth import BearerJWTAuthentication, generate_access_token
from core.redis import redis_client
from core.turnstile import (
    TurnstileVerificationError,
    TURNSTILE_VERIFIED_TTL_SECONDS,
    get_client_ip,
    is_turnstile_enforced,
    mark_ip_captcha_verified,
    verify_turnstile_token,
)


class RegisterAdminView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        username = (request.data.get("username") or "").strip()

        if not email or not password:
            return Response(
                {"detail": "Both email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(password) < 8:
            return Response(
                {"detail": "Password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"detail": "A user with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not username:
            username = email.split("@")[0]

        base_username = username
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base_username}{suffix}"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_staff=True,
            is_superuser=True,
        )

        return Response(
            {
                "detail": "Admin user registered successfully.",
                "user": {
                    "id": user.pk,
                    "username": user.username,
                    "email": user.email,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""

        if not email or not password:
            return Response(
                {"detail": "Both email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if not user or not check_password(password, user.password):
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"detail": "User account is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        access_token = generate_access_token(user)
        return Response(
            {
                "token_type": "Bearer",
                "access_token": access_token,
                "expires_in": 60 * 60 * 24,
                "user": {
                    "id": user.pk,
                    "email": user.email,
                    "is_staff": user.is_staff,
                },
            },
            status=status.HTTP_200_OK,
        )


class CaptchaVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not is_turnstile_enforced():
            return Response(
                {
                    "validity": True,
                    "message": "Captcha verification not required.",
                    "expires_in": TURNSTILE_VERIFIED_TTL_SECONDS,
                },
                status=status.HTTP_200_OK,
            )

        token = (request.data.get("turnstile_token") or "").strip()
        client_ip = get_client_ip(request)

        try:
            verify_turnstile_token(token, client_ip)
        except TurnstileVerificationError as exc:
            return Response(
                {"validity": False, "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mark_ip_captcha_verified(client_ip)
        return Response(
            {
                "validity": True,
                "message": "Captcha verification succeeded.",
                "expires_in": TURNSTILE_VERIFIED_TTL_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Stateless JWT logout is handled client-side by deleting the token.
        return Response(
            {"detail": "Logged out successfully. Remove token on client."},
            status=status.HTTP_200_OK,
        )


class HealthCheckView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        checks: dict[str, str] = {}
        http_status = status.HTTP_200_OK

        try:
            connection.ensure_connection()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

        try:
            redis_client.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

        body = {
            "status": "ok" if http_status == status.HTTP_200_OK else "degraded",
            "checks": checks,
            "timestamp": timezone.now().isoformat(),
        }
        return Response(body, status=http_status)
