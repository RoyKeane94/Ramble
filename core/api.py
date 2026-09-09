from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .logging import log_app_error, log_model_usage


@api_view(["POST"])
@permission_classes([AllowAny])
def report_app_error(request):
    message = (request.data.get("message") or "").strip()
    if not message:
        return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)

    error_type = (request.data.get("error_type") or "").strip()
    traceback_text = (request.data.get("traceback") or "").strip()
    app_version = (request.data.get("app_version") or "").strip()
    metadata = request.data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    log_app_error(
        request=request,
        message=message,
        error_type=error_type,
        traceback_text=traceback_text,
        app_version=app_version,
        metadata=metadata,
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([AllowAny])
def report_model_usage(request):
    operation = (request.data.get("operation") or "").strip()
    model = (request.data.get("model") or "").strip()
    if not operation:
        return Response({"detail": "operation is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not model:
        return Response({"detail": "model is required."}, status=status.HTTP_400_BAD_REQUEST)

    success = request.data.get("success", True)
    if isinstance(success, str):
        success = success.lower() not in {"0", "false", "no"}

    frame_id = request.data.get("frame_id") or None
    metadata = request.data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    app_version = (request.data.get("app_version") or "").strip()

    def _optional_int(key):
        value = request.data.get(key)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _optional_float(key):
        value = request.data.get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    log_model_usage(
        request=request,
        operation=operation,
        model=model,
        success=bool(success),
        frame_id=frame_id,
        audio_seconds=_optional_float("audio_seconds"),
        input_chars=_optional_int("input_chars"),
        prompt_tokens=_optional_int("prompt_tokens"),
        completion_tokens=_optional_int("completion_tokens"),
        total_tokens=_optional_int("total_tokens"),
        latency_ms=_optional_int("latency_ms"),
        app_version=app_version,
        metadata=metadata,
    )
    return Response(status=status.HTTP_204_NO_CONTENT)
