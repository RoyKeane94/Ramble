from django.contrib import admin

from notes.usage import assembly_seconds_for_user

from .models import CrmContact, User


@admin.register(CrmContact)
class CrmContactAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "business_name",
        "contact_type",
        "region",
        "country",
        "email",
        "tracking_slug",
        "updated_at",
    )
    search_fields = (
        "first_name",
        "business_name",
        "email",
        "tracking_slug",
        "website",
        "region",
        "country",
    )
    list_filter = ("contact_type", "country", "region")
    readonly_fields = ("created_at", "updated_at")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    ordering = ("email",)
    list_display = (
        "email",
        "minutes_used",
        "minute_cap",
        "account_active",
        "subscription_status",
        "is_staff",
        "is_active",
        "date_joined",
    )
    search_fields = ("email", "stripe_customer_id", "stripe_subscription_id")
    list_filter = (
        "account_active",
        "is_staff",
        "is_active",
        "is_superuser",
        "subscription_status",
    )
    readonly_fields = (
        "date_joined",
        "last_login",
        "mcp_token_prefix",
        "mcp_token_created_at",
        "take_ready_webhook_saved_at",
        "stripe_customer_id",
        "stripe_subscription_id",
    )
    filter_horizontal = ("groups", "user_permissions")

    @admin.display(description="Minutes used (month)")
    def minutes_used(self, obj):
        return f"{assembly_seconds_for_user(obj) / 60:.1f}"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Allowance", {"fields": ("minute_cap", "billed_seconds")}),
        (
            "Billing",
            {
                "fields": (
                    "account_active",
                    "subscription_status",
                    "stripe_customer_id",
                    "stripe_subscription_id",
                )
            },
        ),
        ("Ramble MCP", {"fields": ("mcp_token_prefix", "mcp_token_created_at")}),
        (
            "Take-ready webhook",
            {
                "fields": (
                    "take_ready_webhook_url",
                    "take_ready_webhook_key",
                    "take_ready_webhook_saved_at",
                )
            },
        ),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
