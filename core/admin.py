from django.contrib import admin

from .models import ErrorLog


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
