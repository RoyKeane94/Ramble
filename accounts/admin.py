from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    ordering = ("email",)
    list_display = ("email", "minutes_used", "minute_cap", "is_staff", "is_active", "date_joined")
    search_fields = ("email",)
    list_filter = ("is_staff", "is_active", "is_superuser")
    readonly_fields = ("date_joined", "last_login")
    filter_horizontal = ("groups", "user_permissions")

    @admin.display(description="Minutes used")
    def minutes_used(self, obj):
        return f"{float(obj.billed_seconds or 0) / 60:.1f}"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Allowance", {"fields": ("minute_cap", "billed_seconds")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
