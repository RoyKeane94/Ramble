"""OAuth helpers for Ramble MCP (Claude connector + PKCE)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.utils import timezone

from .models import (
    ACCESS_TOKEN_PREFIX,
    AUTH_CODE_PREFIX,
    MCP_SCOPE,
    REFRESH_TOKEN_PREFIX,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthRefreshToken,
    hash_secret,
)

ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
AUTH_CODE_TTL = timedelta(minutes=10)

def public_base_url(request=None) -> str:
    base = getattr(settings, "PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base:
        return base
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return "https://yourramble.com"


def mcp_resource_url(request=None) -> str:
    return f"{public_base_url(request)}/mcp"


def protected_resource_metadata(request=None) -> dict:
    base = public_base_url(request)
    resource = mcp_resource_url(request)
    return {
        "resource": resource,
        "authorization_servers": [base],
        "scopes_supported": [MCP_SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Ramble MCP",
        "resource_documentation": f"{base}/settings/",
    }


def authorization_server_metadata(request=None) -> dict:
    base = public_base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": [MCP_SCOPE, "offline_access"],
        "authorization_response_iss_parameter_supported": True,
    }


def resource_metadata_url(request=None) -> str:
    return f"{public_base_url(request)}/.well-known/oauth-protected-resource"


def normalize_scope(raw: str | None) -> str:
    parts = [p for p in (raw or "").split() if p]
    if not parts:
        return MCP_SCOPE
    # Always grant mcp; keep offline_access if requested (refresh tokens).
    ordered = []
    if MCP_SCOPE in parts or True:
        ordered.append(MCP_SCOPE)
    if "offline_access" in parts:
        ordered.append("offline_access")
    return " ".join(ordered)


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    verifier = (code_verifier or "").strip()
    challenge = (code_challenge or "").strip()
    if not verifier or not challenge:
        return False
    if method != "S256":
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, challenge)


def _loopback_hosts() -> set[str]:
    return {"localhost", "127.0.0.1", "[::1]"}


def redirect_uri_allowed(registered_uris: list[str], redirect_uri: str) -> bool:
    """Exact match, plus port-agnostic loopback matching for Claude Code."""
    candidate = (redirect_uri or "").strip()
    if not candidate:
        return False
    registered = [(u or "").strip() for u in registered_uris if (u or "").strip()]
    if candidate in registered:
        return True

    try:
        cand = urlsplit(candidate)
    except ValueError:
        return False
    if cand.scheme != "http" or cand.hostname not in _loopback_hosts():
        return False

    for uri in registered:
        try:
            reg = urlsplit(uri)
        except ValueError:
            continue
        if reg.scheme != "http":
            continue
        if reg.hostname not in _loopback_hosts():
            continue
        # Port-agnostic: match path (+ query) ignoring host port.
        if cand.path != reg.path:
            continue
        if (cand.query or "") != (reg.query or ""):
            continue
        return True
    return False


def issue_authorization_code(
    *,
    client: OAuthClient,
    user,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    scope: str = MCP_SCOPE,
    resource: str = "",
) -> str:
    plain = AUTH_CODE_PREFIX + secrets.token_urlsafe(32)
    OAuthAuthorizationCode.objects.create(
        code_hash=hash_secret(plain),
        client=client,
        user=user,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method or "S256",
        scope=normalize_scope(scope),
        resource=(resource or "").strip(),
        expires_at=timezone.now() + AUTH_CODE_TTL,
    )
    return plain


def issue_token_pair(
    *,
    client: OAuthClient,
    user,
    scope: str = MCP_SCOPE,
    resource: str = "",
) -> dict:
    access_plain = ACCESS_TOKEN_PREFIX + secrets.token_urlsafe(32)
    access = OAuthAccessToken.objects.create(
        token_hash=hash_secret(access_plain),
        token_prefix=access_plain[:12],
        client=client,
        user=user,
        scope=normalize_scope(scope),
        resource=(resource or "").strip(),
        expires_at=timezone.now() + ACCESS_TOKEN_TTL,
    )
    refresh_plain = REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(32)
    OAuthRefreshToken.objects.create(
        token_hash=hash_secret(refresh_plain),
        client=client,
        user=user,
        access_token=access,
        scope=access.scope,
        resource=access.resource,
        expires_at=timezone.now() + REFRESH_TOKEN_TTL,
    )
    return {
        "access_token": access_plain,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh_plain,
        "scope": access.scope,
    }


def rotate_refresh_token(old: OAuthRefreshToken) -> dict:
    old.revoked_at = timezone.now()
    old.save(update_fields=["revoked_at"])
    if old.access_token_id and old.access_token.revoked_at is None:
        old.access_token.revoked_at = timezone.now()
        old.access_token.save(update_fields=["revoked_at"])
    return issue_token_pair(
        client=old.client,
        user=old.user,
        scope=old.scope,
        resource=old.resource,
    )


def append_query(redirect_uri: str, params: dict) -> str:
    parts = urlsplit(redirect_uri)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def client_display_name(client: OAuthClient) -> str:
    name = (client.client_name or "").strip()
    if name:
        return name
    return "Claude"
