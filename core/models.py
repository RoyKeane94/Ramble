from django.conf import settings
from django.db import models


class ErrorLog(models.Model):
    class Source(models.TextChoices):
        WEB = "web", "Web"
        APP = "app", "App"

    source = models.CharField(max_length=8, choices=Source.choices, db_index=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error_type = models.CharField(max_length=120, blank=True, default="")
    message = models.TextField()
    traceback = models.TextField(blank=True, default="")
    path = models.CharField(max_length=2048, blank=True, default="")
    method = models.CharField(max_length=10, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="error_logs",
    )
    user_agent = models.TextField(blank=True, default="")
    app_version = models.CharField(max_length=40, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "-created_at"]),
        ]

    def __str__(self):
        label = self.get_source_display()
        code = f" {self.status_code}" if self.status_code else ""
        return f"[{label}{code}] {self.error_type or 'Error'} — {self.message[:80]}"


class ModelUsageLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="model_usage_logs",
    )
    frame_id = models.UUIDField(null=True, blank=True, db_index=True)
    operation = models.CharField(max_length=40, db_index=True)
    model = models.CharField(max_length=60, db_index=True)
    success = models.BooleanField(default=True, db_index=True)
    audio_seconds = models.FloatField(null=True, blank=True)
    input_chars = models.PositiveIntegerField(null=True, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    app_version = models.CharField(max_length=40, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["operation", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        status = "ok" if self.success else "fail"
        return f"{self.operation} ({self.model}) — {status}"


class TrafficHit(models.Model):
    """Anonymous page views, grouped so an IP is never stored.

    ``visitor_hash`` changes every day. Rows older than 90 days are removed.
    """

    day = models.DateField()
    path = models.CharField(max_length=200)
    referrer = models.CharField(max_length=255, blank=True, default="")
    visitor_hash = models.CharField(max_length=64)
    views = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["day", "path", "referrer", "visitor_hash"],
                name="traffic_hit_day_path_referrer_visitor",
            )
        ]
        indexes = [
            models.Index(fields=["day", "visitor_hash"]),
        ]

    def __str__(self):
        source = self.referrer or "direct"
        return f"{self.day} {self.path} ({source}) ×{self.views}"


class SupportRequest(models.Model):
    class Topic(models.TextChoices):
        ACCOUNT = "account", "Account & billing"
        SYNC = "sync", "Sync or missing takes"
        TRANSCRIPTION = "transcription", "Transcription or tidying"
        BUG = "bug", "Bug or crash"
        OTHER = "other", "Something else"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_requests",
    )
    email = models.EmailField()
    topic = models.CharField(max_length=20, choices=Topic.choices, default=Topic.OTHER)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} — {self.get_topic_display()}"
