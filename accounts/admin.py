from django.contrib import admin

from notes.usage import assembly_seconds_for_user

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    ordering = ("email",)
    list_display = ("email", "minutes_used", "minute_cap", "is_staff", "is_active", "date_joined")
    search_fields = ("email",)
    list_filter = ("is_staff", "is_active", "is_superuser")
    readonly_fields = ("date_joined", "last_login", "mcp_token_prefix", "mcp_token_created_at")
    filter_horizontal = ("groups", "user_permissions")

    @admin.display(description="Minutes used (month)")
    def minutes_used(self, obj):
        return f"{assembly_seconds_for_user(obj) / 60:.1f}"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Allowance", {"fields": ("minute_cap", "billed_seconds")}),
        ("Ramble MCP", {"fields": ("mcp_token_prefix", "mcp_token_created_at")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
