import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .emails import send_welcome_email
from .models import PendingSignup, ProcessedStripeEvent

log = logging.getLogger("ramble.stripe")

User = get_user_model()

SUBSCRIPTION_AMOUNT_GBP = Decimal("9.99")
SUBSCRIPTION_AMOUNT_PENCE = 999
SUBSCRIPTION_LABEL = "Ramble"
INTEGRATION_IDENTIFIER = "ramble_signup_web_0001"
TRIAL_PERIOD_DAYS = 7

# Events to register on the Stripe webhook destination.
WEBHOOK_EVENTS = [
    # Recommended
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    # Optional
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "payment_intent.succeeded",
    "setup_intent.succeeded",
]


class StripeNotConfigured(Exception):
    pass


def configure_stripe():
    secret = getattr(settings, "STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise StripeNotConfigured("Stripe is not configured.")
    stripe.api_key = secret
    return stripe


def publishable_key():
    key = getattr(settings, "STRIPE_PUBLISHABLE_KEY", "").strip()
    if not key:
        raise StripeNotConfigured("Stripe publishable key is not configured.")
    return key


def checkout_line_items():
    price_id = getattr(settings, "STRIPE_PRICE_ID", "").strip()
    if price_id:
        return [{"price": price_id, "quantity": 1}]
    return [
        {
            "price_data": {
                "currency": "gbp",
                "unit_amount": SUBSCRIPTION_AMOUNT_PENCE,
                "recurring": {"interval": "month"},
                "product_data": {
                    "name": SUBSCRIPTION_LABEL,
                    "description": "Ramble monthly subscription",
                },
            },
            "quantity": 1,
        }
    ]


def create_checkout_session(*, pending: PendingSignup, return_url: str):
    """Create an embedded Checkout form session (ui_mode=form)."""
    configure_stripe()
    return stripe.checkout.Session.create(
        mode="subscription",
        ui_mode="form",
        customer_email=pending.email,
        client_reference_id=str(pending.pk),
        line_items=checkout_line_items(),
        return_url=return_url,
        billing_address_collection="auto",
        payment_method_collection="always",
        submit_type="auto",
        integration_identifier=INTEGRATION_IDENTIFIER,
        metadata={
            "pending_signup_id": str(pending.pk),
            "email": pending.email,
        },
        subscription_data={
            "trial_period_days": TRIAL_PERIOD_DAYS,
            "metadata": {
                "pending_signup_id": str(pending.pk),
                "email": pending.email,
            },
        },
        allow_promotion_codes=True,
    )


def retrieve_checkout_session(session_id: str):
    configure_stripe()
    return stripe.checkout.Session.retrieve(session_id)


def create_billing_portal_session(*, customer_id: str, return_url: str):
    configure_stripe()
    if not customer_id:
        raise StripeNotConfigured("No Stripe customer on this account.")
    params = {
        "customer": customer_id,
        "return_url": return_url,
    }
    configuration = getattr(settings, "STRIPE_PORTAL_CONFIGURATION_ID", "").strip()
    if configuration:
        params["configuration"] = configuration
    return stripe.billing_portal.Session.create(**params)


def construct_webhook_event(payload: bytes, signature: str):
    configure_stripe()
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise StripeNotConfigured("Stripe webhook secret is not configured.")
    return stripe.Webhook.construct_event(payload, signature, secret)


def ensure_webhook_endpoint(url: str):
    """Create or update a Stripe webhook destination for this integration."""
    configure_stripe()
    existing = stripe.WebhookEndpoint.list(limit=100).data
    for endpoint in existing:
        if endpoint.url == url:
            updated = stripe.WebhookEndpoint.modify(
                endpoint.id,
                enabled_events=WEBHOOK_EVENTS,
                description="Ramble signup & billing",
            )
            return updated, False
    created = stripe.WebhookEndpoint.create(
        url=url,
        enabled_events=WEBHOOK_EVENTS,
        description="Ramble signup & billing",
    )
    return created, True


def _obj_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _id_value(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return getattr(value, "id", "") or ""


def _subscription_id_from_session(session) -> str:
    return _id_value(_obj_get(session, "subscription"))


def _customer_id_from_session(session) -> str:
    return _id_value(_obj_get(session, "customer"))


def _session_value(session, key, default=""):
    value = _obj_get(session, key, default)
    return value if value is not None else default


def _initial_subscription_status(session) -> str:
    """Free-trial checkouts complete with no charge due yet."""
    if _session_value(session, "payment_status") == "no_payment_required":
        return "trialing"
    return "active"


def _user_for_customer(customer_id: str):
    if not customer_id:
        return None
    return User.objects.filter(stripe_customer_id=customer_id).first()


def _user_for_subscription(subscription_id: str):
    if not subscription_id:
        return None
    return User.objects.filter(stripe_subscription_id=subscription_id).first()


def _apply_account_active(user, *, active: bool, updates: list[str]) -> None:
    if user.account_active != active:
        user.account_active = active
        updates.append("account_active")


def _cancellation_details(subscription):
    details = _obj_get(subscription, "cancellation_details") or {}
    if hasattr(details, "to_dict"):
        details = details.to_dict()
    if not isinstance(details, dict):
        return {}
    return details


def cancellation_requested(subscription) -> bool:
    """
    True when the customer has asked to cancel.

    Paid plans often use cancel_at_period_end=True. Trials commonly keep
    cancel_at_period_end=False and instead set cancel_at / canceled_at.
    """
    if bool(_obj_get(subscription, "cancel_at_period_end")):
        return True
    if _obj_get(subscription, "canceled_at"):
        return True
    if _obj_get(subscription, "cancel_at"):
        return True
    reason = (_cancellation_details(subscription).get("reason") or "").strip()
    return reason == "cancellation_requested"


def sync_subscription(subscription) -> None:
    sub_id = _id_value(_obj_get(subscription, "id"))
    customer_id = _id_value(_obj_get(subscription, "customer"))
    status = _obj_get(subscription, "status") or ""
    if not sub_id:
        return

    user = _user_for_subscription(sub_id) or _user_for_customer(customer_id)
    if user is None:
        log.info("No user for subscription=%s customer=%s", sub_id, customer_id)
        return

    if status == "canceled":
        deactivate_account_for_cancelled_subscription(subscription)
        return

    # Cancel requested in Stripe/portal — pause recording immediately (access until period
    # end is a billing concern; product entitlement ends when they cancel).
    if cancellation_requested(subscription):
        updates = []
        if customer_id and user.stripe_customer_id != customer_id:
            user.stripe_customer_id = customer_id
            updates.append("stripe_customer_id")
        if user.stripe_subscription_id != sub_id:
            user.stripe_subscription_id = sub_id
            updates.append("stripe_subscription_id")
        if user.subscription_status != "cancelling":
            user.subscription_status = "cancelling"
            updates.append("subscription_status")
        _apply_account_active(user, active=False, updates=updates)
        if updates:
            user.save(update_fields=updates)
        log.info(
            "Marked account inactive after cancel scheduled user=%s subscription=%s",
            user.email,
            sub_id,
        )
        return

    display_status = status

    updates = []
    if customer_id and user.stripe_customer_id != customer_id:
        user.stripe_customer_id = customer_id
        updates.append("stripe_customer_id")
    if user.stripe_subscription_id != sub_id:
        user.stripe_subscription_id = sub_id
        updates.append("stripe_subscription_id")
    if user.subscription_status != display_status:
        user.subscription_status = display_status
        updates.append("subscription_status")
    if status in {"active", "trialing", "past_due"}:
        _apply_account_active(user, active=True, updates=updates)
    if updates:
        user.save(update_fields=updates)
        log.info(
            "Synced subscription user=%s subscription=%s status=%s",
            user.email,
            sub_id,
            display_status,
        )


def refresh_user_subscription(user) -> bool:
    """
    Pull the latest Stripe subscription for this user and sync local status.
    Used when returning from the billing portal (webhooks may lag or miss localhost).
    """
    customer_id = (getattr(user, "stripe_customer_id", "") or "").strip()
    subscription_id = (getattr(user, "stripe_subscription_id", "") or "").strip()
    if not customer_id and not subscription_id:
        return False

    try:
        configure_stripe()
        subscription = None
        if subscription_id:
            try:
                subscription = stripe.Subscription.retrieve(subscription_id)
            except stripe.error.InvalidRequestError:
                subscription = None
        if subscription is None and customer_id:
            listed = stripe.Subscription.list(customer=customer_id, status="all", limit=10)
            # Prefer an open subscription; otherwise the most recent.
            open_statuses = {"active", "trialing", "past_due", "unpaid", "paused"}
            open_subs = [s for s in listed.data if (s.status or "") in open_statuses]
            subscription = open_subs[0] if open_subs else (listed.data[0] if listed.data else None)
        if subscription is None:
            return False
        sync_subscription(subscription)
        user.refresh_from_db()
        return True
    except StripeNotConfigured:
        return False
    except Exception:
        log.exception("Failed to refresh Stripe subscription for user=%s", getattr(user, "email", ""))
        return False


def deactivate_account_for_cancelled_subscription(subscription) -> None:
    """Mark the Ramble account inactive when the Stripe subscription ends."""
    sub_id = _id_value(_obj_get(subscription, "id"))
    customer_id = _id_value(_obj_get(subscription, "customer"))
    user = _user_for_subscription(sub_id) or _user_for_customer(customer_id)
    if user is None:
        log.info(
            "No user to deactivate for cancelled subscription=%s customer=%s",
            sub_id,
            customer_id,
        )
        return

    updates = []
    if user.subscription_status != "canceled":
        user.subscription_status = "canceled"
        updates.append("subscription_status")
    if user.stripe_subscription_id:
        user.stripe_subscription_id = ""
        updates.append("stripe_subscription_id")
    _apply_account_active(user, active=False, updates=updates)
    if updates:
        user.save(update_fields=updates)
    log.info(
        "Marked account inactive after subscription cancelled email=%s user_id=%s subscription=%s",
        user.email,
        user.pk,
        sub_id,
    )


def handle_invoice_paid(invoice) -> None:
    customer_id = _id_value(_obj_get(invoice, "customer"))
    subscription_id = _id_value(_obj_get(invoice, "subscription"))
    user = _user_for_customer(customer_id) or _user_for_subscription(subscription_id)
    if user is None:
        log.info("invoice.paid with no matching user customer=%s", customer_id)
        return

    updates = []
    if customer_id and user.stripe_customer_id != customer_id:
        user.stripe_customer_id = customer_id
        updates.append("stripe_customer_id")
    if subscription_id and user.stripe_subscription_id != subscription_id:
        user.stripe_subscription_id = subscription_id
        updates.append("stripe_subscription_id")
    if user.subscription_status != "active":
        user.subscription_status = "active"
        updates.append("subscription_status")
    _apply_account_active(user, active=True, updates=updates)
    if updates:
        user.save(update_fields=updates)
    log.info("invoice.paid user=%s invoice=%s", user.email, _obj_get(invoice, "id"))


def handle_invoice_payment_failed(invoice) -> None:
    customer_id = _id_value(_obj_get(invoice, "customer"))
    subscription_id = _id_value(_obj_get(invoice, "subscription"))
    user = _user_for_customer(customer_id) or _user_for_subscription(subscription_id)
    if user is None:
        log.info("invoice.payment_failed with no matching user customer=%s", customer_id)
        return

    updates = []
    if subscription_id and user.stripe_subscription_id != subscription_id:
        user.stripe_subscription_id = subscription_id
        updates.append("stripe_subscription_id")
    if user.subscription_status != "past_due":
        user.subscription_status = "past_due"
        updates.append("subscription_status")
    if updates:
        user.save(update_fields=updates)
    log.warning(
        "invoice.payment_failed user=%s invoice=%s",
        user.email,
        _obj_get(invoice, "id"),
    )


@transaction.atomic
def fulfill_checkout_session(session):
    """Create the user after Stripe confirms payment. Idempotent."""
    metadata = _session_value(session, "metadata", {}) or {}
    if hasattr(metadata, "to_dict"):
        metadata = metadata.to_dict()
    pending_id = metadata.get("pending_signup_id") or _session_value(session, "client_reference_id")
    payment_status = _session_value(session, "payment_status")
    status = _session_value(session, "status")

    if status != "complete" or payment_status not in {"paid", "no_payment_required"}:
        log.info(
            "Skipping incomplete checkout session=%s payment_status=%s status=%s",
            _session_value(session, "id"),
            payment_status,
            status,
        )
        return None

    if not pending_id:
        log.warning("Checkout session missing pending_signup_id session=%s", _session_value(session, "id"))
        return None

    pending = (
        PendingSignup.objects.select_for_update()
        .filter(pk=pending_id)
        .first()
    )
    if pending is None:
        log.warning("Pending signup not found id=%s", pending_id)
        return None

    session_id = _session_value(session, "id")
    customer_id = _customer_id_from_session(session)
    subscription_id = _subscription_id_from_session(session)

    subscription_status = _initial_subscription_status(session)

    existing = User.objects.filter(email__iexact=pending.email).first()
    if existing is not None:
        updates = []
        if customer_id and existing.stripe_customer_id != customer_id:
            existing.stripe_customer_id = customer_id
            updates.append("stripe_customer_id")
        if subscription_id and existing.stripe_subscription_id != subscription_id:
            existing.stripe_subscription_id = subscription_id
            updates.append("stripe_subscription_id")
        if existing.subscription_status != subscription_status:
            existing.subscription_status = subscription_status
            updates.append("subscription_status")
        _apply_account_active(existing, active=True, updates=updates)
        if updates:
            existing.save(update_fields=updates)
        if pending.completed_at is None:
            pending.completed_at = timezone.now()
            pending.stripe_checkout_session_id = session_id or pending.stripe_checkout_session_id
            pending.save(update_fields=["completed_at", "stripe_checkout_session_id"])
        return existing

    user = User(
        email=pending.email,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status=subscription_status,
        account_active=True,
    )
    user.password = pending.password_hash
    user.save()

    pending.completed_at = timezone.now()
    pending.stripe_checkout_session_id = session_id or pending.stripe_checkout_session_id
    pending.save(update_fields=["completed_at", "stripe_checkout_session_id"])
    log.info("Created user from Stripe checkout email=%s session=%s", user.email, session_id)
    welcome_email = user.email
    transaction.on_commit(lambda: send_welcome_email(email=welcome_email))
    return user


@transaction.atomic
def handle_webhook_event(event) -> bool:
    """
    Process a verified Stripe event. Returns False if this event was already handled.
    """
    event_id = _obj_get(event, "id") or ""
    event_type = _obj_get(event, "type") or ""
    if not event_id:
        raise ValueError("Stripe event missing id")

    _, created = ProcessedStripeEvent.objects.get_or_create(
        event_id=event_id,
        defaults={"event_type": event_type},
    )
    if not created:
        log.info("Skipping duplicate Stripe event id=%s type=%s", event_id, event_type)
        return False

    data = _obj_get(event, "data") or {}
    data_object = _obj_get(data, "object")
    if data_object is None and isinstance(event, dict):
        data_object = (event.get("data") or {}).get("object")

    if event_type == "checkout.session.completed":
        fulfill_checkout_session(data_object)
    elif event_type == "invoice.paid":
        handle_invoice_paid(data_object)
    elif event_type == "invoice.payment_failed":
        handle_invoice_payment_failed(data_object)
    elif event_type == "customer.subscription.deleted":
        deactivate_account_for_cancelled_subscription(data_object)
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
    }:
        sync_subscription(data_object)
    elif event_type in {"payment_intent.succeeded", "setup_intent.succeeded"}:
        log.info(
            "Recorded %s id=%s customer=%s",
            event_type,
            _obj_get(data_object, "id"),
            _id_value(_obj_get(data_object, "customer")),
        )
    else:
        log.info("Unhandled Stripe event type=%s id=%s", event_type, event_id)

    return True
