import traceback

from django.contrib.auth.models import AnonymousUser

from .models import ErrorLog, ModelUsageLog


def _request_user(request):
    user = getattr(request, "user", None)
    if user is None or isinstance(user, AnonymousUser) or not user.is_authenticated:
        return None
    return user


def _request_meta(request):
    return {
        "path": getattr(request, "path", "") or "",
        "method": getattr(request, "method", "") or "",
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
    }


def log_web_error(
    *,
    request,
    message,
    status_code=None,
    error_type="",
    exc=None,
    metadata=None,
):
    tb = ""
    if exc is not None:
        error_type = error_type or type(exc).__name__
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    meta = _request_meta(request)
    return ErrorLog.objects.create(
        source=ErrorLog.Source.WEB,
        status_code=status_code,
        error_type=error_type,
        message=message,
        traceback=tb,
        path=meta["path"],
        method=meta["method"],
        user=_request_user(request),
        user_agent=meta["user_agent"],
        metadata=metadata or {},
    )


def log_app_error(
    *,
    request,
    message,
    error_type="",
    traceback_text="",
    app_version="",
    metadata=None,
):
    meta = _request_meta(request)
    return ErrorLog.objects.create(
        source=ErrorLog.Source.APP,
        error_type=error_type,
        message=message,
        traceback=traceback_text,
        path=meta["path"],
        method=meta["method"],
        user=_request_user(request),
        user_agent=meta["user_agent"],
        app_version=app_version,
        metadata=metadata or {},
    )


def log_model_usage(
    *,
    request,
    operation,
    model,
    success=True,
    frame_id=None,
    audio_seconds=None,
    input_chars=None,
    prompt_tokens=None,
    completion_tokens=None,
    total_tokens=None,
    latency_ms=None,
    app_version="",
    metadata=None,
):
    return ModelUsageLog.objects.create(
        user=_request_user(request),
        frame_id=frame_id or None,
        operation=operation,
        model=model,
        success=success,
        audio_seconds=audio_seconds,
        input_chars=input_chars,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        app_version=app_version,
        metadata=metadata or {},
    )
