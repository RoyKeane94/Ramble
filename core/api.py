from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .logging import log_app_error


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
