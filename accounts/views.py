import json
import logging
from datetime import timedelta
from urllib.parse import urlencode

import segno
from django.conf import settings as django_settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.traffic import normalize_period, traffic_report
from notes.models import Note
from notes.usage import usage_for_user

from .forms import (
    CrmContactForm,
    CrmOutreachEmailForm,
    EmailAuthenticationForm,
    SignupForm,
    StyledPasswordChangeForm,
    TakeReadyWebhookForm,
)
from .kpi import format_duration, user_kpis
from .models import CrmContact, PendingSignup
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
        # Keep ?ref= so CRM open-tracking still runs after the signed-in redirect.
        ref = (request.GET.get("ref") or "").strip()
        if ref:
            return redirect(f"{reverse(django_settings.LOGIN_REDIRECT_URL)}?{urlencode({'ref': ref})}")
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
    grok_mcp_url = request.build_absolute_uri("/mcp/grok").rstrip("/")
    return render(
        request,
        "accounts/settings.html",
        {
            "note_count": notes.count(),
            "last_synced": latest.updated_at if latest else None,
            "minute_usage": usage_for_user(request.user),
            "mcp_url": mcp_url,
            "grok_mcp_url": grok_mcp_url,
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
    period = normalize_period(request.GET.get("period"))
    view = request.GET.get("view", "table").strip().lower()
    if view not in {"table", "graph"}:
        view = "table"
    traffic = traffic_report(period=period)
    traffic["view"] = view
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
            "traffic": traffic,
            "nav_section": "kpi",
        },
    )


CRM_PAGE_SIZE = 50
CRM_OPEN_CONFIRM_SECONDS = 3


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _crm_open_request_ignored(request):
    purpose = (
        request.META.get("HTTP_SEC_PURPOSE", "")
        or request.META.get("HTTP_PURPOSE", "")
    ).lower()
    if purpose == "prefetch":
        return True
    from core.traffic import _is_bot

    return _is_bot(request.META.get("HTTP_USER_AGENT", ""))


def _crm_type_filter(request):
    value = (request.GET.get("type") or request.POST.get("type") or "").strip()
    allowed = {choice for choice, _label in CrmContact.ContactType.choices}
    if value and value not in allowed:
        return ""
    return value


def _crm_list_url(page=None, contact_type=""):
    url = reverse("crm")
    params = []
    if contact_type:
        params.append(f"type={contact_type}")
    try:
        number = int(page)
    except (TypeError, ValueError):
        number = 1
    if number > 1:
        params.append(f"page={number}")
    if not params:
        return url
    return f"{url}?{'&'.join(params)}"


def _crm_queryset(contact_type=""):
    contacts = CrmContact.objects.all()
    if contact_type:
        contacts = contacts.filter(contact_type=contact_type)
    return contacts


def _crm_page(request, queryset):
    return Paginator(queryset, CRM_PAGE_SIZE).get_page(request.GET.get("page"))


def _crm_list_context(request, *, form, editing=None, crm_modal_open=False):
    contact_type = _crm_type_filter(request)
    page_obj = _crm_page(request, _crm_queryset(contact_type))
    return {
        "contacts": page_obj.object_list,
        "page_obj": page_obj,
        "form": form,
        "nav_section": "crm",
        "editing": editing,
        "crm_modal_open": crm_modal_open,
        "crm_return_page": page_obj.number,
        "crm_type_filter": contact_type,
        "crm_type_choices": CrmContact.ContactType.choices,
    }


@login_required
def crm_list(request):
    _require_superuser(request)
    form = CrmContactForm()
    if request.method == "POST":
        form = CrmContactForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(_crm_list_url(contact_type=_crm_type_filter(request)))
    return render(
        request,
        "accounts/crm.html",
        _crm_list_context(
            request,
            form=form,
            editing=None,
            crm_modal_open=bool(form.errors),
        ),
    )


@login_required
def crm_edit(request, pk):
    _require_superuser(request)
    contact = get_object_or_404(CrmContact, pk=pk)
    form = CrmContactForm(instance=contact)
    page = request.GET.get("page") or request.POST.get("page")
    contact_type = _crm_type_filter(request)
    if request.method == "POST":
        form = CrmContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            return redirect(_crm_list_url(page=page, contact_type=contact_type))
    return render(
        request,
        "accounts/crm.html",
        _crm_list_context(
            request,
            form=form,
            editing=contact,
            crm_modal_open=True,
        ),
    )


@login_required
@require_POST
def crm_delete(request, pk):
    _require_superuser(request)
    contact = get_object_or_404(CrmContact, pk=pk)
    contact.delete()
    return redirect(
        _crm_list_url(
            page=request.POST.get("page") or request.GET.get("page"),
            contact_type=_crm_type_filter(request),
        )
    )


def _crm_return_from_request(request):
    return _crm_list_url(
        page=request.POST.get("page") or request.GET.get("page"),
        contact_type=_crm_type_filter(request),
    )


CRM_INLINE_FIELDS = frozenset(
    {
        "first_name",
        "business_name",
        "region",
        "country",
        "notes",
    }
)


def _clean_crm_inline_value(contact, field, value):
    form = CrmContactForm(instance=contact)
    django_field = form.fields[field]
    cleaned = django_field.clean(value)
    cleaner = getattr(form, f"clean_{field}", None)
    if cleaner is not None:
        form.cleaned_data = {field: cleaned}
        cleaned = cleaner()
    return cleaned


@login_required
@require_POST
def crm_field_update(request, pk):
    """Save a single CRM table cell via click-to-edit."""
    _require_superuser(request)
    contact = get_object_or_404(CrmContact, pk=pk)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)
    field = (payload.get("field") or "").strip()
    if field not in CRM_INLINE_FIELDS:
        return JsonResponse({"ok": False, "error": "Unknown field"}, status=400)
    raw = payload.get("value", "")
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raw = str(raw)
    try:
        cleaned = _clean_crm_inline_value(contact, field, raw)
    except ValidationError as exc:
        message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return JsonResponse({"ok": False, "error": message or "Invalid value"}, status=400)
    setattr(contact, field, cleaned)
    contact.save(update_fields=[field, "updated_at"])
    return JsonResponse({"ok": True, "field": field, "value": cleaned})


def _save_outreach_email(contact, *, subject, body, status):
    contact.outreach_email_subject = subject
    contact.outreach_email_body = body
    contact.outreach_email_status = status
    contact.ensure_tracking_url_in_body()
    contact.save(
        update_fields=[
            "outreach_email_subject",
            "outreach_email_body",
            "outreach_email_status",
            "updated_at",
        ]
    )


@login_required
@require_POST
def crm_email_save(request, pk):
    _require_superuser(request)
    contact = get_object_or_404(CrmContact, pk=pk)
    form = CrmOutreachEmailForm(request.POST)
    if not form.is_valid():
        return redirect(_crm_return_from_request(request))
    _save_outreach_email(
        contact,
        subject=form.cleaned_data["outreach_email_subject"],
        body=form.cleaned_data["outreach_email_body"],
        status=CrmContact.OutreachEmailStatus.DRAFT,
    )
    return redirect(_crm_return_from_request(request))


@login_required
@require_POST
def crm_email_approve(request, pk):
    _require_superuser(request)
    contact = get_object_or_404(CrmContact, pk=pk)
    form = CrmOutreachEmailForm(request.POST)
    if form.is_valid():
        subject = form.cleaned_data["outreach_email_subject"]
        body = form.cleaned_data["outreach_email_body"]
    else:
        subject = contact.outreach_email_subject
        body = contact.outreach_email_body
    if not (subject or body):
        return redirect(_crm_return_from_request(request))
    _save_outreach_email(
        contact,
        subject=subject,
        body=body,
        status=CrmContact.OutreachEmailStatus.APPROVED,
    )
    return redirect(_crm_return_from_request(request))


@csrf_exempt
@require_POST
def crm_tracking_open_start(request, slug):
    """Begin a CRM email open timer for ?ref=<slug> visits."""
    if _crm_open_request_ignored(request):
        return HttpResponse(status=204)
    contact = CrmContact.objects.filter(tracking_slug=slug).first()
    if contact is None:
        return HttpResponse(status=204)
    if contact.outreach_email_opened_at:
        return JsonResponse({"status": "opened"})
    if contact.outreach_email_open_started_at is None:
        contact.outreach_email_open_started_at = timezone.now()
        contact.save(update_fields=["outreach_email_open_started_at", "updated_at"])
    return JsonResponse({"status": "started"})


@csrf_exempt
@require_POST
def crm_tracking_open_confirm(request, slug):
    """Confirm a CRM email open after the visitor has stayed ~3 seconds."""
    if _crm_open_request_ignored(request):
        return HttpResponse(status=204)
    contact = CrmContact.objects.filter(tracking_slug=slug).first()
    if contact is None:
        return HttpResponse(status=204)
    if contact.outreach_email_opened_at:
        return JsonResponse({"status": "opened"})
    now = timezone.now()
    started = contact.outreach_email_open_started_at
    if started is None:
        # Confirm arrived before start finished — begin the timer and ask to retry.
        contact.outreach_email_open_started_at = now
        contact.save(update_fields=["outreach_email_open_started_at", "updated_at"])
        return JsonResponse(
            {
                "status": "too_soon",
                "retry_after_ms": CRM_OPEN_CONFIRM_SECONDS * 1000,
            },
            status=409,
        )
    elapsed = now - started
    needed = timedelta(seconds=CRM_OPEN_CONFIRM_SECONDS)
    if elapsed < needed:
        remaining_ms = int((needed - elapsed).total_seconds() * 1000)
        return JsonResponse(
            {
                "status": "too_soon",
                "retry_after_ms": max(remaining_ms, 250),
            },
            status=409,
        )
    contact.outreach_email_opened_at = now
    contact.save(update_fields=["outreach_email_opened_at", "updated_at"])
    return JsonResponse({"status": "opened"})
