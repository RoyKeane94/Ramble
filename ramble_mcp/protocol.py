import logging

from .tools import ToolError, as_tool_result, call_tool, tool_definitions

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
    "Pass updated_since when you only want what changed."
)


class MethodNotFound(Exception):
    pass


def handle_payload(user, payload):
    if isinstance(payload, list):
        return [item for item in (handle_message(user, entry) for entry in payload) if item is not None]
    return handle_message(user, payload)


def handle_message(user, message):
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
        result = _dispatch(user, method, params if isinstance(params, dict) else {})
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


def _dispatch(user, method, params):
    if method == "initialize":
        requested = params.get("protocolVersion") or LATEST_PROTOCOL
        version = requested if requested in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return {}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_definitions()}
    if method == "tools/call":
        name = params.get("name")
        if not name:
            raise ToolError("Tool name is required.")
        logger.info("mcp tool=%s user=%s", name, user.email)
        data = call_tool(user, name, params.get("arguments") or {})
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
