import json
import logging

from accounts.models import User
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import OAuthAccessToken
from .oauth import resource_metadata_url
from .protocol import LATEST_PROTOCOL, handle_payload

logger = logging.getLogger(__name__)

ALLOW_HEADERS = "Authorization, Content-Type, Accept, MCP-Protocol-Version, Mcp-Session-Id"
ALLOW_METHODS = "POST, GET, DELETE, OPTIONS"


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE", "OPTIONS"])
def mcp_endpoint(request):
    """Claude MCP at /mcp — OAuth (or bearer token) with take/album tools only."""
    return _mcp_endpoint(request, surface="claude")


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE", "OPTIONS"])
def grok_mcp_endpoint(request):
    """Grok Bot MCP at /mcp/grok — bearer token; webhooks + CRM (superuser)."""
    return _mcp_endpoint(request, surface="grok")


def _mcp_endpoint(request, surface="claude"):
    if request.method == "OPTIONS":
        return _cors(request, HttpResponse(status=204))

    user, auth_method, error = _authenticate(request, surface=surface)
    if error is not None:
        return _cors(request, error)

    if request.method in {"GET", "DELETE"}:
        response = HttpResponse(status=405)
        response["Allow"] = "POST, OPTIONS"
        return _cors(request, response)

    try:
        payload = json.loads(request.body.decode("utf-8") or "null")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _cors(
            request,
            JsonResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error."}},
                status=400,
            ),
        )

    if payload is None:
        return _cors(
            request,
            JsonResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request."}},
                status=400,
            ),
        )

    result = handle_payload(user, payload, auth_method=auth_method, surface=surface)
    if result is None or result == []:
        return _cors(request, HttpResponse(status=202))
    return _cors(request, JsonResponse(result, safe=False))


def _authenticate(request, surface="claude"):
    raw = _bearer_token(request)
    if not raw:
        return None, None, _unauthorized(request, "missing_token", surface=surface)
    if surface == "grok":
        user = User.get_by_mcp_token(raw)
        if user is not None:
            return user, "mcp_token", None
        return None, None, _unauthorized(request, "invalid_token", surface=surface)
    user = User.get_by_mcp_token(raw)
    if user is not None:
        return user, "mcp_token", None
    user = OAuthAccessToken.get_valid_user(raw)
    if user is not None:
        return user, "oauth", None
    return None, None, _unauthorized(request, "invalid_token", surface=surface)


def _bearer_token(request):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if header.lower().startswith("token "):
        return header[6:].strip()
    return ""


def _unauthorized(request, error, surface="claude"):
    response = JsonResponse({"error": "unauthorized"}, status=401)
    if surface == "grok":
        response["WWW-Authenticate"] = f'Bearer realm="Ramble Grok MCP", error="{error}"'
    else:
        metadata = resource_metadata_url(request)
        response["WWW-Authenticate"] = (
            f'Bearer realm="Ramble MCP", error="{error}", '
            f'resource_metadata="{metadata}"'
        )
    return response


def _cors(request, response):
    origin = request.headers.get("Origin") or request.META.get("HTTP_ORIGIN")
    response["Access-Control-Allow-Origin"] = origin or "*"
    response["Access-Control-Allow-Methods"] = ALLOW_METHODS
    response["Access-Control-Allow-Headers"] = ALLOW_HEADERS
    response["Access-Control-Max-Age"] = "86400"
    response["MCP-Protocol-Version"] = LATEST_PROTOCOL
    if origin:
        response["Vary"] = "Origin"
    return response
