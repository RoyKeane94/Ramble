import logging

from .tools import (
    ToolError,
    as_tool_result,
    call_tool,
    crm_allowed,
    tool_definitions,
    webhook_allowed,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "ramble"
SERVER_VERSION = "1.0.0"
LATEST_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Ramble is a camera roll for speech. Each take has a stable id and an updated timestamp. "
    "Use search_takes for questions about what the user said. "
    "Use list_recent_takes for a daily or weekly digest. "
    "Use get_take for full text. "
    "Use update_take to file a take into an album or star it. "
    "Use create_album when you need a new album. "
    "Pass updated_since when you only want what changed."
)
WEBHOOK_INSTRUCTIONS = (
    " You can register a take-ready webhook with save_take_ready_webhook so Ramble POSTs "
    "{event: take.ready, take_id} when a take first becomes ready; then call get_take. "
    "Use get_take_ready_webhook_status / clear_take_ready_webhook to check or remove it."
)
CRM_INSTRUCTIONS = (
    " You also have Ramble CRM tools for outreach contacts: "
    "list_crm_contacts, get_crm_contact, create_crm_contact, update_crm_contact, delete_crm_contact. "
    "These manage the same contacts as the /crm/ dashboard (superuser only)."
)


class MethodNotFound(Exception):
    pass


def handle_payload(user, payload, auth_method="oauth", surface="claude"):
    if isinstance(payload, list):
        return [
            item
            for item in (
                handle_message(
                    user, entry, auth_method=auth_method, surface=surface
                )
                for entry in payload
            )
            if item is not None
        ]
    return handle_message(user, payload, auth_method=auth_method, surface=surface)


def handle_message(user, message, auth_method="oauth", surface="claude"):
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid request.")
    if message.get("jsonrpc") != "2.0":
        return _error(message.get("id"), -32600, "jsonrpc must be 2.0.")

    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    is_notification = "id" not in message

    if not method:
        return None if is_notification else _error(msg_id, -32600, "Missing method.")

    try:
        result = _dispatch(
            user,
            method,
            params if isinstance(params, dict) else {},
            auth_method=auth_method,
            surface=surface,
        )
    except MethodNotFound:
        if is_notification:
            return None
        return _error(msg_id, -32601, f"Method not found: {method}")
    except ToolError as exc:
        if is_notification:
            return None
        if method == "tools/call":
            return _ok(msg_id, as_tool_result(str(exc), is_error=True))
        return _error(msg_id, -32602, str(exc))
    except TypeError as exc:
        if is_notification:
            return None
        if method == "tools/call":
            return _ok(msg_id, as_tool_result(str(exc), is_error=True))
        return _error(msg_id, -32602, str(exc))
    except Exception:
        logger.exception("MCP %s failed for %s", method, user.email)
        if is_notification:
            return None
        return _error(msg_id, -32603, "Internal error.")

    if is_notification:
        return None
    return _ok(msg_id, result)


def _dispatch(user, method, params, auth_method="oauth", surface="claude"):
    if method == "initialize":
        requested = params.get("protocolVersion") or LATEST_PROTOCOL
        version = requested if requested in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
        instructions = INSTRUCTIONS
        if webhook_allowed(surface):
            instructions += WEBHOOK_INSTRUCTIONS
        if crm_allowed(user, auth_method=auth_method, surface=surface):
            instructions += CRM_INSTRUCTIONS
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "ramble-grok" if surface == "grok" else SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "instructions": instructions,
        }
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return {}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {
            "tools": tool_definitions(
                user, auth_method=auth_method, surface=surface
            )
        }
    if method == "tools/call":
        name = params.get("name")
        if not name:
            raise ToolError("Tool name is required.")
        logger.info(
            "mcp tool=%s user=%s auth=%s surface=%s",
            name,
            user.email,
            auth_method,
            surface,
        )
        data = call_tool(
            user,
            name,
            params.get("arguments") or {},
            auth_method=auth_method,
            surface=surface,
        )
        return as_tool_result(data)
    raise MethodNotFound(method)


def _ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }
