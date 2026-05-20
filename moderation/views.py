from datetime import timedelta

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.auth import BearerJWTAuthentication
from core.redis import redis_client
from matchmaking.queue import WAITING_USERS_KEY
from moderation.models import TemporaryBan


class IsStaffUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)


class AdminDashboardView(APIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]

    def get(self, request):
        active_ips = sorted(redis_client.smembers("active_ips"))
        visited_ips = sorted(redis_client.smembers("visited_ips"))
        queue_size = redis_client.llen(WAITING_USERS_KEY)
        active_sessions = len(redis_client.keys("presence:*"))

        active_bans_queryset = TemporaryBan.objects.filter(expires_at__gt=timezone.now())
        active_bans = [
            {
                "ip_address": ban.ip_address,
                "reason": ban.reason,
                "expires_at": ban.expires_at,
            }
            for ban in active_bans_queryset.order_by("expires_at")
        ]

        return Response(
            {
                "active_ips": {
                    "count": len(active_ips),
                    "values": active_ips,
                },
                "visited_ips": {
                    "count": len(visited_ips),
                    "values": visited_ips,
                },
                "current_queue_size": queue_size,
                "active_sessions": active_sessions,
                "active_soft_bans": {
                    "count": len(active_bans),
                    "values": active_bans,
                },
            },
            status=status.HTTP_200_OK,
        )


class SoftBanIPView(APIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]

    def post(self, request):
        ip_address = (request.data.get("ip_address") or "").strip()
        if not ip_address:
            return Response(
                {"detail": "ip_address is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expires_at = timezone.now() + timedelta(minutes=30)
        ban, _ = TemporaryBan.objects.update_or_create(
            ip_address=ip_address,
            defaults={
                "reason": "Soft banned by admin dashboard",
                "expires_at": expires_at,
            },
        )

        return Response(
            {
                "detail": "IP soft banned for 30 minutes.",
                "ip_address": ban.ip_address,
                "expires_at": ban.expires_at,
            },
            status=status.HTTP_200_OK,
        )
