from django.contrib.auth import authenticate

from notes.usage import usage_for_user
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .lockout import LOCKOUT_MESSAGE


def _token_payload(user):
    token, _ = Token.objects.get_or_create(user=user)
    payload = {"token": token.key, "email": user.email}
    payload.update(usage_for_user(user))
    return payload


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    email = (request.data.get("email") or "").strip()
    password = request.data.get("password") or ""
    # Use the Django request so django-axes can flag lockouts for middleware/handlers.
    django_request = getattr(request, "_request", request)
    user = authenticate(django_request, username=email, password=password)
    if getattr(django_request, "axes_locked_out", False):
        return Response({"detail": LOCKOUT_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if user is None:
        return Response({"detail": "Invalid email or password."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_token_payload(user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    payload = {"email": request.user.email}
    payload.update(usage_for_user(request.user))
    return Response(payload)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_account(request):
    user = request.user
    Token.objects.filter(user=user).delete()
    user.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
