import logging

import segno
from django.conf import settings as django_settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.traffic import traffic_report
from notes.models import Note
from notes.usage import usage_for_user

from .forms import (
    EmailAuthenticationForm,
    SignupForm,
    StyledPasswordChangeForm,
    TakeReadyWebhookForm,
)
from .kpi import format_duration, user_kpis
from .models import PendingSignup
from .stripe_billing import (
    SUBSCRIPTION_AMOUNT_GBP,
    StripeNotConfigured,
    construct_webhook_event,
    create_billing_portal_session,
    create_checkout_session,
    fulfill_checkout_session,
    handle_webhook_event,
    publishable_key,
    refresh_user_subscription,
    retrieve_checkout_session,
)

log = logging.getLogger("ramble.stripe")


class RambleLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["app_store_url"] = getattr(
            django_settings,
            "APP_STORE_URL",
            "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
        )
        return context


class RambleLogoutView(LogoutView):
    next_page = reverse_lazy("login")


def signup(request):
    if request.user.is_authenticated:
        return redirect(django_settings.LOGIN_REDIRECT_URL)

    form = SignupForm()
    error = ""
    checkout = None

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            pending = PendingSignup.create_for_credentials(
                form.cleaned_data["email"],
                form.cleaned_data["password1"],
            )
            # Append the Stripe placeholder after build_absolute_uri so braces stay unencoded.
            return_url = (
                request.build_absolute_uri(reverse("signup_success"))
                + "?session_id={CHECKOUT_SESSION_ID}"
            )
            try:
                pk = publishable_key()
                session = create_checkout_session(
                    pending=pending,
                    return_url=return_url,
                )
            except StripeNotConfigured:
                pending.delete()
                error = "Payments are not available right now. Please try again later."
            except Exception:
                log.exception("Failed to create Stripe checkout session")
                pending.delete()
                error = "Could not start checkout. Please try again."
            else:
                pending.stripe_checkout_session_id = session.id
                pending.save(update_fields=["stripe_checkout_session_id"])
                checkout = {
                    "publishable_key": pk,
                    "client_secret": session.client_secret,
                    "email": pending.email,
                }

    return render(
        request,
        "accounts/signup.html",
        {
            "form": form,
            "error": error,
            "checkout": checkout,
            "price_label": f"£{SUBSCRIPTION_AMOUNT_GBP}",
            "app_store_url": getattr(
                django_settings,
                "APP_STORE_URL",
                "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
            ),
        },
    )


def signup_success(request):
    session_id = (request.GET.get("session_id") or "").strip()
    if not session_id:
        return redirect("signup")

    try:
        session = retrieve_checkout_session(session_id)
        user = fulfill_checkout_session(session)
    except StripeNotConfigured:
        return render(
            request,
            "accounts/signup_result.html",
            {
                "title": "Almost there",
                "message": "Payment succeeded, but account setup is delayed. Please contact support if you cannot sign in.",
            },
            status=503,
        )
    except Exception:
        log.exception("Signup success fulfillment failed session=%s", session_id)
        return render(
            request,
            "accounts/signup_result.html",
            {
                "title": "Almost there",
                "message": "Payment went through. We’re finishing your account — try signing in in a moment.",
            },
            status=503,
        )

    if user is None:
        return render(
            request,
            "accounts/signup_result.html",
            {
                "title": "Payment pending",
                "message": "Stripe has not confirmed payment yet. If you were charged, try signing in shortly.",
            },
        )

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return render(
        request,
        "accounts/signup_welcome.html",
        _app_store_context(email=user.email),
    )


def _app_store_context(*, email=""):
    app_store_url = getattr(
        django_settings,
        "APP_STORE_URL",
        "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
    )
    qr = segno.make(app_store_url, error="m")
    return {
        "app_store_url": app_store_url,
        "app_store_qr": qr.svg_data_uri(scale=5, border=1),
        "account_email": email,
    }


def signup_cancel(request):
    return render(
        request,
        "accounts/signup_result.html",
        {
            "title": "Checkout cancelled",
            "message": "No account was created. You can start again whenever you’re ready.",
            "show_retry": True,
        },
    )


@csrf_exempt
@require_POST
def stripe_webhook(request):
    signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = construct_webhook_event(request.body, signature)
    except StripeNotConfigured:
        return HttpResponse(status=503)
    except Exception as exc:
        log.warning("Stripe webhook rejected: %s", exc)
        return HttpResponseBadRequest("Invalid payload")

    try:
        handle_webhook_event(event)
    except Exception:
        log.exception("Stripe webhook handler failed type=%s", getattr(event, "type", None))
        return HttpResponse(status=500)

    return HttpResponse(status=200)


@login_required
@require_POST
def billing_portal(request):
    customer_id = (request.user.stripe_customer_id or "").strip()
    if not customer_id:
        return redirect("settings")

    return_url = request.build_absolute_uri(reverse("settings"))
    try:
        session = create_billing_portal_session(
            customer_id=customer_id,
            return_url=return_url,
        )
    except StripeNotConfigured:
        log.warning("Billing portal unavailable — Stripe not configured")
        return redirect("settings")
    except Exception:
        log.exception("Failed to create billing portal session user=%s", request.user.email)
        return redirect("settings")
    return redirect(session.url, permanent=False)


@login_required
def settings(request):
    mcp_token_plain = None
    webhook_form = TakeReadyWebhookForm()
    webhook_saved = False
    webhook_cleared = False
    show_webhook_form = False

    if request.method == "POST":
        intent = request.POST.get("intent")
        if intent == "mcp_token":
            mcp_token_plain = request.user.issue_mcp_token()
        elif intent == "take_ready_webhook":
            show_webhook_form = True
            webhook_form = TakeReadyWebhookForm(request.POST)
            if webhook_form.is_valid():
                request.user.save_take_ready_webhook(
                    webhook_form.cleaned_data["url"],
                    webhook_form.cleaned_data["key"],
                )
                webhook_saved = True
                webhook_form = TakeReadyWebhookForm()
                show_webhook_form = False
        elif intent == "clear_take_ready_webhook":
            request.user.clear_take_ready_webhook()
            webhook_cleared = True
            show_webhook_form = True
        elif intent == "edit_take_ready_webhook":
            show_webhook_form = True
    elif (request.user.stripe_customer_id or "").strip():
        # Portal returns here; sync so cancel shows up even if webhooks are delayed.
        refresh_user_subscription(request.user)

    if not request.user.has_take_ready_webhook:
        show_webhook_form = True

    notes = Note.objects.filter(user=request.user)
    latest = notes.order_by("-updated_at").first()
    mcp_url = request.build_absolute_uri("/mcp").rstrip("/")
    return render(
        request,
        "accounts/settings.html",
        {
            "note_count": notes.count(),
            "last_synced": latest.updated_at if latest else None,
            "minute_usage": usage_for_user(request.user),
            "mcp_url": mcp_url,
            "mcp_token_plain": mcp_token_plain,
            "can_manage_billing": bool((request.user.stripe_customer_id or "").strip()),
            "subscription_status": (request.user.subscription_status or "").strip(),
            "account_active": bool(request.user.account_active),
            "webhook_form": webhook_form,
            "webhook_saved": webhook_saved,
            "webhook_cleared": webhook_cleared,
            "show_webhook_form": show_webhook_form,
        },
    )


@login_required
def change_password(request):
    password_form = StyledPasswordChangeForm(request.user)
    password_saved = False

    if request.method == "POST":
        password_form = StyledPasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            password_saved = True
            password_form = StyledPasswordChangeForm(request.user)

    return render(
        request,
        "accounts/change_password.html",
        {
            "password_form": password_form,
            "password_saved": password_saved,
        },
    )


@login_required
def kpi_dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    rows = [
        {
            "email": row.email,
            "date_joined": row.date_joined,
            "take_count": row.take_count,
            "signup_to_first": format_duration(row.signup_to_first),
            "first_to_second": format_duration(row.first_to_second),
            "last_take_at": row.last_take_at,
            "days_since_last": row.days_since_last,
            "active_days": row.active_days,
            "current_streak": row.current_streak,
        }
        for row in user_kpis()
    ]
    return render(
        request,
        "accounts/kpi.html",
        {
            "kpi_rows": rows,
            "traffic": traffic_report(),
            "nav_section": "kpi",
        },
    )
