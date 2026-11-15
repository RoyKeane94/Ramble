"""OAuth models for Claude / MCP connector auth."""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

ACCESS_TOKEN_PREFIX = "rmoa_"
REFRESH_TOKEN_PREFIX = "rmor_"
AUTH_CODE_PREFIX = "rmac_"
MCP_SCOPE = "mcp"


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class OAuthClient(models.Model):
    """Dynamically registered or manually created OAuth public client."""

    client_id = models.CharField(max_length=64, unique=True, db_index=True)
    client_secret_hash = models.CharField(max_length=64, blank=True, default="")
    client_name = models.CharField(max_length=255, blank=True, default="")
    redirect_uris = models.JSONField(default=list)
    token_endpoint_auth_method = models.CharField(max_length=64, default="none")
    grant_types = models.JSONField(default=list)
    response_types = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.client_name or self.client_id

    @property
    def is_public(self) -> bool:
        return self.token_endpoint_auth_method == "none" or not self.client_secret_hash

    @classmethod
    def register(
        cls,
        *,
        client_name: str = "",
        redirect_uris: list[str] | None = None,
        token_endpoint_auth_method: str = "none",
        grant_types: list[str] | None = None,
        response_types: list[str] | None = None,
        client_secret: str | None = None,
    ) -> tuple["OAuthClient", str | None]:
        uris = [u.strip() for u in (redirect_uris or []) if (u or "").strip()]
        if not uris:
            raise ValueError("redirect_uris is required")
        grants = grant_types or ["authorization_code", "refresh_token"]
        responses = response_types or ["code"]
        method = (token_endpoint_auth_method or "none").strip() or "none"
        plain_secret = None
        secret_hash = ""
        if method != "none":
            plain_secret = client_secret or secrets.token_urlsafe(32)
            secret_hash = hash_secret(plain_secret)
        client = cls.objects.create(
            client_id=secrets.token_urlsafe(24),
            client_secret_hash=secret_hash,
            client_name=(client_name or "").strip()[:255],
            redirect_uris=uris,
            token_endpoint_auth_method=method,
            grant_types=grants,
            response_types=responses,
        )
        return client, plain_secret


class OAuthAuthorizationCode(models.Model):
    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="codes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_codes",
    )
    redirect_uri = models.CharField(max_length=500)
    code_challenge = models.CharField(max_length=128)
    code_challenge_method = models.CharField(max_length=16, default="S256")
    scope = models.CharField(max_length=255, default=MCP_SCOPE)
    resource = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_used(self) -> bool:
        return self.used_at is not None


class OAuthAccessToken(models.Model):
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    token_prefix = models.CharField(max_length=12, blank=True, default="")
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="access_tokens")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_access_tokens",
    )
    scope = models.CharField(max_length=255, default=MCP_SCOPE)
    resource = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and timezone.now() < self.expires_at

    @classmethod
    def get_valid_user(cls, raw: str):
        token = (raw or "").strip()
        if not token:
            return None
        row = (
            cls.objects.select_related("user")
            .filter(token_hash=hash_secret(token), revoked_at__isnull=True)
            .first()
        )
        if row is None or not row.is_valid:
            return None
        if not row.user.is_active:
            return None
        return row.user


class OAuthRefreshToken(models.Model):
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="refresh_tokens")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_refresh_tokens",
    )
    access_token = models.ForeignKey(
        OAuthAccessToken,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=255, default=MCP_SCOPE)
    resource = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and timezone.now() < self.expires_at
