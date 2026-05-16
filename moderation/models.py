from django.db import models


class Report(models.Model):

    report_id = models.CharField(
        max_length=255,
        unique=True,
    )

    room_id = models.CharField(
        max_length=255,
    )

    reporter_session = models.CharField(
        max_length=255,
    )

    reason = models.TextField()

    matched_tags = models.JSONField(
        default=list,
    )

    messages = models.JSONField(
        default=list,
    )

    metadata = models.JSONField(
        default=dict,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.report_id


class TemporaryBan(models.Model):

    ip_address = models.CharField(
        max_length=255,
        unique=True,
    )

    reason = models.TextField()

    expires_at = models.DateTimeField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.ip_address


class ModerationAction(models.Model):

    ACTION_CHOICES = [
        ("warn", "Warn"),
        ("ban", "Ban"),
        ("unban", "Unban"),
    ]

    target_ip = models.CharField(
        max_length=255,
    )

    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
    )

    notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )