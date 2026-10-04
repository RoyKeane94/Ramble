from notes.usage import usage_for_user


def minute_usage(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    return {"minute_usage": usage_for_user(user)}
