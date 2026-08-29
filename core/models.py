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
