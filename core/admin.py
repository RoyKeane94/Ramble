from django.contrib import admin

from .models import ErrorLog, ModelUsageLog


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "source",
        "status_code",
        "error_type",
        "message_preview",
        "user",
        "path_preview",
    )
    list_filter = ("source", "status_code", "error_type")
    search_fields = ("message", "path", "error_type", "user__email", "traceback")
    readonly_fields = (
        "source",
        "status_code",
        "error_type",
        "message",
        "traceback",
        "path",
        "method",
        "user",
        "user_agent",
        "app_version",
        "metadata",
        "created_at",
    )
    date_hierarchy = "created_at"

    @admin.display(description="Message")
    def message_preview(self, obj):
        return obj.message[:120]

    @admin.display(description="Path")
    def path_preview(self, obj):
        return obj.path[:80]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ModelUsageLog)
class ModelUsageLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "operation",
        "model",
        "success",
        "user",
        "frame_id",
        "audio_seconds",
        "total_tokens",
        "latency_ms",
    )
    list_filter = ("operation", "model", "success")
    search_fields = ("operation", "model", "user__email", "frame_id")
    readonly_fields = (
        "user",
        "frame_id",
        "operation",
        "model",
        "success",
        "audio_seconds",
        "input_chars",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "app_version",
        "metadata",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
