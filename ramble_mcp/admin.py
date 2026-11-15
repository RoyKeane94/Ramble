from django.contrib import admin

from .models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken


@admin.register(OAuthClient)
class OAuthClientAdmin(admin.ModelAdmin):
    list_display = ("client_name", "client_id", "token_endpoint_auth_method", "created_at")
    search_fields = ("client_id", "client_name")
    readonly_fields = ("client_id", "client_secret_hash", "created_at")


@admin.register(OAuthAccessToken)
class OAuthAccessTokenAdmin(admin.ModelAdmin):
    list_display = ("token_prefix", "user", "client", "expires_at", "revoked_at", "created_at")
    search_fields = ("token_prefix", "user__email", "client__client_id")
    readonly_fields = ("token_hash", "token_prefix", "created_at")


@admin.register(OAuthRefreshToken)
class OAuthRefreshTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "client", "expires_at", "revoked_at", "created_at")
    search_fields = ("user__email", "client__client_id")
    readonly_fields = ("token_hash", "created_at")


@admin.register(OAuthAuthorizationCode)
class OAuthAuthorizationCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "client", "expires_at", "used_at", "created_at")
    search_fields = ("user__email", "client__client_id")
    readonly_fields = ("code_hash", "created_at")
