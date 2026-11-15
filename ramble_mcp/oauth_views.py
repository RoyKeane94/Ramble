"""OAuth endpoints for Claude MCP connectors."""

from __future__ import annotations

import base64
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken, hash_secret
from .oauth import (
    append_query,
    authorization_server_metadata,
    client_display_name,
    issue_authorization_code,
    issue_token_pair,
    mcp_resource_url,
    normalize_scope,
    protected_resource_metadata,
    public_base_url,
    redirect_uri_allowed,
    rotate_refresh_token,
    verify_pkce,
)

logger = logging.getLogger(__name__)


def _cors_json(request, payload, status=200):
    response = JsonResponse(payload, status=status)
    origin = request.headers.get("Origin") or request.META.get("HTTP_ORIGIN")
    response["Access-Control-Allow-Origin"] = origin or "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept"
    response["Access-Control-Max-Age"] = "86400"
    if origin:
        response["Vary"] = "Origin"
    return response


def _cors_empty(request, status=204):
    response = HttpResponse(status=status)
    origin = request.headers.get("Origin") or request.META.get("HTTP_ORIGIN")
    response["Access-Control-Allow-Origin"] = origin or "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept"
    response["Access-Control-Max-Age"] = "86400"
    if origin:
        response["Vary"] = "Origin"
    return response


def _oauth_error(request, error, description="", status=400):
    body = {"error": error}
    if description:
        body["error_description"] = description
    return _cors_json(request, body, status=status)


@require_GET
def oauth_protected_resource(request, resource_path=""):
    """RFC 9728 protected resource metadata."""
    return _cors_json(request, protected_resource_metadata(request))


@require_GET
def oauth_authorization_server(request):
    """RFC 8414 authorization server metadata."""
    return _cors_json(request, authorization_server_metadata(request))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def oauth_register(request):
    """RFC 7591 Dynamic Client Registration."""
    if request.method == "OPTIONS":
        return _cors_empty(request)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _oauth_error(request, "invalid_client_metadata", "Body must be JSON.")

    if not isinstance(payload, dict):
        return _oauth_error(request, "invalid_client_metadata", "Body must be a JSON object.")

    redirect_uris = payload.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _oauth_error(request, "invalid_redirect_uri", "redirect_uris is required.")

    try:
        client, plain_secret = OAuthClient.register(
            client_name=str(payload.get("client_name") or ""),
            redirect_uris=[str(u) for u in redirect_uris],
            token_endpoint_auth_method=str(payload.get("token_endpoint_auth_method") or "none"),
            grant_types=payload.get("grant_types"),
            response_types=payload.get("response_types"),
        )
    except ValueError as exc:
        return _oauth_error(request, "invalid_client_metadata", str(exc))

    body = {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": client.response_types,
        "token_endpoint_auth_method": client.token_endpoint_auth_method,
    }
    if plain_secret:
        body["client_secret"] = plain_secret
    return _cors_json(request, body, status=201)


@login_required
@require_http_methods(["GET", "POST"])
def oauth_authorize(request):
    """Authorization endpoint — login + consent, then redirect with code."""
    params = request.GET if request.method == "GET" else request.POST
    client_id = (params.get("client_id") or "").strip()
    redirect_uri = (params.get("redirect_uri") or "").strip()
    response_type = (params.get("response_type") or "").strip()
    state = params.get("state")
    scope = normalize_scope(params.get("scope"))
    code_challenge = (params.get("code_challenge") or "").strip()
    code_challenge_method = (params.get("code_challenge_method") or "S256").strip()
    resource = (params.get("resource") or "").strip()

    client = OAuthClient.objects.filter(client_id=client_id).first() if client_id else None
    if client is None:
        return HttpResponseBadRequest("Unknown client_id.")

    if response_type != "code":
        return HttpResponseBadRequest("Only response_type=code is supported.")

    if not redirect_uri_allowed(client.redirect_uris, redirect_uri):
        return HttpResponseBadRequest("redirect_uri is not registered for this client.")

    if not code_challenge or code_challenge_method != "S256":
        # Redirect error when we can safely send the user back.
        return HttpResponseRedirect(
            append_query(
                redirect_uri,
                {
                    "error": "invalid_request",
                    "error_description": "PKCE S256 code_challenge is required.",
                    "state": state,
                },
            )
        )

    expected_resource = mcp_resource_url(request)
    if resource and resource.rstrip("/") != expected_resource.rstrip("/"):
        return HttpResponseRedirect(
            append_query(
                redirect_uri,
                {
                    "error": "invalid_target",
                    "error_description": "resource does not match this MCP server.",
                    "state": state,
                },
            )
        )

    if request.method == "GET":
        return render(
            request,
            "ramble_mcp/oauth_consent.html",
            {
                "client_name": client_display_name(client),
                "client_id": client.client_id,
                "redirect_uri": redirect_uri,
                "redirect_host": _redirect_host(redirect_uri),
                "scope": scope,
                "state": state or "",
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "resource": resource or expected_resource,
                "response_type": response_type,
            },
        )

    decision = (request.POST.get("decision") or "").strip()
    if decision != "approve":
        return HttpResponseRedirect(
            append_query(
                redirect_uri,
                {
                    "error": "access_denied",
                    "error_description": "The user denied the request.",
                    "state": state,
                },
            )
        )

    code = issue_authorization_code(
        client=client,
        user=request.user,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        resource=resource or expected_resource,
    )
    return HttpResponseRedirect(
        append_query(
            redirect_uri,
            {
                "code": code,
                "state": state,
                "iss": public_base_url(request),
            },
        )
    )


def _redirect_host(redirect_uri: str) -> str:
    from urllib.parse import urlsplit

    try:
        return urlsplit(redirect_uri).hostname or redirect_uri
    except ValueError:
        return redirect_uri


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def oauth_token(request):
    """Token endpoint — authorization_code + refresh_token."""
    if request.method == "OPTIONS":
        return _cors_empty(request)

    grant_type = (request.POST.get("grant_type") or "").strip()
    client, client_error = _authenticate_client(request)
    if client_error:
        return client_error

    if grant_type == "authorization_code":
        return _token_authorization_code(request, client)
    if grant_type == "refresh_token":
        return _token_refresh(request, client)
    return _oauth_error(request, "unsupported_grant_type", "Use authorization_code or refresh_token.")


def _authenticate_client(request):
    from urllib.parse import unquote

    client_id = (request.POST.get("client_id") or "").strip()
    client_secret = (request.POST.get("client_secret") or "").strip()

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
            basic_id, basic_secret = decoded.split(":", 1)
            client_id = unquote(basic_id)
            client_secret = unquote(basic_secret)
        except Exception:
            return None, _oauth_error(
                request, "invalid_client", "Malformed Authorization header.", status=401
            )

    if not client_id:
        return None, _oauth_error(request, "invalid_client", "client_id is required.", status=401)

    client = OAuthClient.objects.filter(client_id=client_id).first()
    if client is None:
        return None, _oauth_error(request, "invalid_client", "Unknown client.", status=401)

    if not client.is_public:
        if not client_secret or not secrets_compare(
            client.client_secret_hash, hash_secret(client_secret)
        ):
            return None, _oauth_error(
                request, "invalid_client", "Invalid client credentials.", status=401
            )

    return client, None


def secrets_compare(stored_hash: str, candidate_hash: str) -> bool:
    import secrets as secrets_mod

    return bool(stored_hash) and secrets_mod.compare_digest(stored_hash, candidate_hash)


def _token_authorization_code(request, client):
    code = (request.POST.get("code") or "").strip()
    redirect_uri = (request.POST.get("redirect_uri") or "").strip()
    code_verifier = (request.POST.get("code_verifier") or "").strip()
    resource = (request.POST.get("resource") or "").strip()

    if not code or not redirect_uri or not code_verifier:
        return _oauth_error(request, "invalid_request", "code, redirect_uri, and code_verifier are required.")

    row = OAuthAuthorizationCode.objects.select_related("user", "client").filter(code_hash=hash_secret(code)).first()
    if row is None or row.client_id != client.id:
        return _oauth_error(request, "invalid_grant", "Invalid authorization code.")
    if row.is_used:
        return _oauth_error(request, "invalid_grant", "Authorization code already used.")
    if row.is_expired:
        return _oauth_error(request, "invalid_grant", "Authorization code expired.")
    if row.redirect_uri != redirect_uri:
        return _oauth_error(request, "invalid_grant", "redirect_uri mismatch.")
    if not verify_pkce(code_verifier, row.code_challenge, row.code_challenge_method):
        return _oauth_error(request, "invalid_grant", "PKCE verification failed.")

    if resource and row.resource and resource.rstrip("/") != row.resource.rstrip("/"):
        return _oauth_error(request, "invalid_target", "resource mismatch.")

    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])

    tokens = issue_token_pair(
        client=client,
        user=row.user,
        scope=row.scope,
        resource=resource or row.resource or mcp_resource_url(request),
    )
    return _cors_json(request, tokens)


def _token_refresh(request, client):
    refresh = (request.POST.get("refresh_token") or "").strip()
    resource = (request.POST.get("resource") or "").strip()
    if not refresh:
        return _oauth_error(request, "invalid_request", "refresh_token is required.")

    row = (
        OAuthRefreshToken.objects.select_related("user", "client", "access_token")
        .filter(token_hash=hash_secret(refresh), revoked_at__isnull=True)
        .first()
    )
    if row is None or row.client_id != client.id:
        return _oauth_error(request, "invalid_grant", "Invalid refresh token.")
    if not row.is_valid:
        return _oauth_error(request, "invalid_grant", "Refresh token expired or revoked.")

    if resource and row.resource and resource.rstrip("/") != row.resource.rstrip("/"):
        return _oauth_error(request, "invalid_target", "resource mismatch.")

    tokens = rotate_refresh_token(row)
    return _cors_json(request, tokens)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def oauth_revoke(request):
    """RFC 7009 token revocation (best-effort)."""
    if request.method == "OPTIONS":
        return _cors_empty(request)

    client, client_error = _authenticate_client(request)
    if client_error:
        return client_error

    token = (request.POST.get("token") or "").strip()
    if not token:
        return _oauth_error(request, "invalid_request", "token is required.")

    hashed = hash_secret(token)
    now = timezone.now()
    access = OAuthAccessToken.objects.filter(token_hash=hashed, client=client).first()
    if access and access.revoked_at is None:
        access.revoked_at = now
        access.save(update_fields=["revoked_at"])
    refresh = OAuthRefreshToken.objects.filter(token_hash=hashed, client=client).first()
    if refresh and refresh.revoked_at is None:
        refresh.revoked_at = now
        refresh.save(update_fields=["revoked_at"])
    return _cors_empty(request, status=200)
