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


def _serialize_soft_ban(ban, now):
    remaining_seconds = max(0, int((ban.expires_at - now).total_seconds()))
    return {
        "ip_address": ban.ip_address,
        "reason": ban.reason,
        "expires_at": ban.expires_at.isoformat(),
        "created_at": ban.created_at.isoformat(),
        "remaining_seconds": remaining_seconds,
        "remaining_minutes": round(remaining_seconds / 60, 1),
    }


class AdminDashboardView(APIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]

    def get(self, request):
        now = timezone.now()
        active_ips = sorted(redis_client.smembers("active_ips"))
        visited_ips = sorted(redis_client.smembers("visited_ips"))
        queue_size = redis_client.llen(WAITING_USERS_KEY)
        active_sessions = len(redis_client.keys("presence:*"))

        active_bans_queryset = TemporaryBan.objects.filter(
            expires_at__gt=now,
        ).order_by("expires_at")
        active_soft_bans = [
            _serialize_soft_ban(ban, now)
            for ban in active_bans_queryset
        ]
        banned_ip_set = {b["ip_address"] for b in active_soft_bans}

        return Response(
            {
                "generated_at": now.isoformat(),
                "stats": {
                    "active_ips_count": len(active_ips),
                    "visited_ips_count": len(visited_ips),
                    "queue_size": queue_size,
                    "active_sessions": active_sessions,
                    "active_soft_bans_count": len(active_soft_bans),
                },
                "active_ips": active_ips,
                "visited_ips": visited_ips,
                "active_soft_bans": active_soft_bans,
                "banned_ip_addresses": sorted(banned_ip_set),
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

        remaining_seconds = max(
            0,
            int((ban.expires_at - timezone.now()).total_seconds()),
        )
        return Response(
            {
                "detail": "IP soft banned for 30 minutes.",
                "ban": {
                    "ip_address": ban.ip_address,
                    "reason": ban.reason,
                    "expires_at": ban.expires_at.isoformat(),
                    "remaining_seconds": remaining_seconds,
                    "remaining_minutes": round(remaining_seconds / 60, 1),
                },
            },
            status=status.HTTP_200_OK,
        )
