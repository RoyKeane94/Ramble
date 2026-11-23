from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from notes.models import Note

from .emails import (
    greeting_name,
    schedule_check_in_email_for_user,
    send_check_in_email,
    send_welcome_email,
)
from .kpi import format_duration, user_kpis
from .models import CrmContact, PendingSignup, ProcessedStripeEvent
from .stripe_billing import (
    TRIAL_PERIOD_DAYS,
    create_checkout_session,
    fulfill_checkout_session,
    handle_webhook_event,
)

User = get_user_model()


class AuthPageTests(TestCase):
    def test_login_autocomplete(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertNotContains(response, 'autocomplete="off"')
        self.assertContains(response, reverse("signup"))
        self.assertContains(response, "Use the same login in the iPhone app")
        self.assertContains(response, "download-on-the-app-store.svg")
        self.assertContains(response, settings.APP_STORE_URL)

    def test_register_page_is_gone(self):
        response = self.client.get("/register/")
        self.assertEqual(response.status_code, 404)

    def test_register_api_is_gone(self):
        response = self.client.post(
            "/api/auth/register/",
            {"email": "new@example.com", "password": "password12"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_signup_page_shows_price(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create account")
        self.assertContains(response, "Start your 7 day free trial")
        self.assertContains(response, "By signing up, you are agreeing to our")
        self.assertContains(response, "Terms of Use")
        self.assertContains(response, reverse("notes:terms"))
        self.assertContains(response, "Secure payment with Stripe")
        self.assertContains(response, "Give your thoughts somewhere to go.")
        self.assertContains(response, "An iPhone app, plus the web.")
        self.assertContains(response, "Talk into your phone. Read it anywhere, same words.")
        self.assertContains(response, "7 days free, then £9.99 a month")
        self.assertContains(response, "Cancel any time.")
        self.assertContains(response, "Includes the free iPhone app")
        self.assertContains(response, "download-on-the-app-store.svg")
        self.assertNotContains(response, "£100 a year")


class SignupCheckoutTests(TestCase):
    @override_settings(
        STRIPE_SECRET_KEY="sk_test_x",
        STRIPE_PUBLISHABLE_KEY="pk_test_x",
        STRIPE_PRICE_ID="price_test_x",
    )
    @patch("accounts.views.create_checkout_session")
    def test_signup_embeds_stripe_checkout(self, mock_create):
        mock_create.return_value = MagicMock(
            id="cs_test_123",
            client_secret="cs_test_123_secret_abc",
        )
        response = self.client.post(
            reverse("signup"),
            {
                "email": "new@example.com",
                "password1": "password12",
                "password2": "password12",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="checkout-form"')
        self.assertContains(response, "cs_test_123_secret_abc")
        self.assertContains(response, "pk_test_x")
        self.assertContains(response, "js.stripe.com/endive/stripe.js")
        self.assertContains(response, "js/signup-checkout.js")
        pending = PendingSignup.objects.get(email="new@example.com")
        self.assertEqual(pending.stripe_checkout_session_id, "cs_test_123")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertIn("return_url", kwargs)
        self.assertIn("{CHECKOUT_SESSION_ID}", kwargs["return_url"])

    def test_signup_does_not_create_account_without_stripe(self):
        response = self.client.post(
            reverse("signup"),
            {
                "email": "new@example.com",
                "password1": "password12",
                "password2": "password12",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payments are not available")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())
        self.assertFalse(PendingSignup.objects.filter(email="new@example.com").exists())

    @override_settings(STRIPE_SECRET_KEY="sk_test_x")
    @patch("accounts.views.retrieve_checkout_session")
    def test_success_creates_account_and_logs_in(self, mock_retrieve):
        pending = PendingSignup.create_for_credentials("paid@example.com", "password12")
        mock_retrieve.return_value = {
            "id": "cs_test_paid",
            "status": "complete",
            "payment_status": "paid",
            "customer": "cus_123",
            "subscription": "sub_123",
            "metadata": {"pending_signup_id": str(pending.pk)},
            "client_reference_id": str(pending.pk),
        }
        response = self.client.get(reverse("signup_success"), {"session_id": "cs_test_paid"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You’re in")
        self.assertContains(
            response,
            "Get the iPhone app and say it the moment it arrives",
        )
        self.assertContains(response, "Get Ramble on the App Store")
        self.assertContains(response, "Sign in on the app with paid@example.com")
        self.assertContains(
            response,
            "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
        )
        self.assertContains(response, "data:image/svg+xml")
        self.assertContains(response, "Claude, Grok, and GrokBot")
        self.assertContains(response, reverse("settings"))
        self.assertContains(response, "tom@yourramble.com")
        self.assertContains(response, reverse("notes:list"))
        user = User.objects.get(email="paid@example.com")
        self.assertTrue(user.check_password("password12"))
        self.assertEqual(user.stripe_customer_id, "cus_123")
        self.assertEqual(user.stripe_subscription_id, "sub_123")
        self.assertEqual(user.subscription_status, "active")
        self.assertTrue(user.account_active)
        self.assertTrue(PendingSignup.objects.get(pk=pending.pk).completed_at)
        self.assertTrue(response.wsgi_request.user.is_authenticated)


class FulfillmentTests(TestCase):
    def test_fulfill_is_idempotent(self):
        pending = PendingSignup.create_for_credentials("once@example.com", "password12")
        session = {
            "id": "cs_test_once",
            "status": "complete",
            "payment_status": "paid",
            "customer": "cus_1",
            "subscription": "sub_1",
            "metadata": {"pending_signup_id": str(pending.pk)},
        }
        first = fulfill_checkout_session(session)
        second = fulfill_checkout_session(session)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(User.objects.filter(email="once@example.com").count(), 1)

    def test_incomplete_session_does_not_create_user(self):
        pending = PendingSignup.create_for_credentials("wait@example.com", "password12")
        session = {
            "id": "cs_test_wait",
            "status": "open",
            "payment_status": "unpaid",
            "metadata": {"pending_signup_id": str(pending.pk)},
        }
        self.assertIsNone(fulfill_checkout_session(session))
        self.assertFalse(User.objects.filter(email="wait@example.com").exists())

    def test_fulfill_trial_checkout_marks_trialing(self):
        pending = PendingSignup.create_for_credentials("trial@example.com", "password12")
        session = {
            "id": "cs_test_trial",
            "status": "complete",
            "payment_status": "no_payment_required",
            "customer": "cus_trial",
            "subscription": "sub_trial",
            "metadata": {"pending_signup_id": str(pending.pk)},
        }
        user = fulfill_checkout_session(session)
        self.assertIsNotNone(user)
        self.assertEqual(user.subscription_status, "trialing")

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_x",
        STRIPE_PRICE_ID="price_test_x",
    )
    @patch("accounts.stripe_billing.stripe.checkout.Session.create")
    def test_create_checkout_session_includes_seven_day_trial(self, mock_create):
        pending = PendingSignup.create_for_credentials("trial-create@example.com", "password12")
        mock_create.return_value = MagicMock(id="cs_trial")
        create_checkout_session(
            pending=pending,
            return_url="https://example.com/signup/success/?session_id={CHECKOUT_SESSION_ID}",
        )
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["subscription_data"]["trial_period_days"], TRIAL_PERIOD_DAYS)
        self.assertEqual(TRIAL_PERIOD_DAYS, 7)
        self.assertEqual(kwargs["payment_method_collection"], "always")

    @patch("accounts.stripe_billing.schedule_check_in_email_for_user")
    @patch("accounts.stripe_billing.send_welcome_email")
    def test_fulfill_sends_welcome_email_once(self, mock_welcome, mock_check_in):
        pending = PendingSignup.create_for_credentials("welcome@example.com", "password12")
        session = {
            "id": "cs_test_welcome",
            "status": "complete",
            "payment_status": "paid",
            "customer": "cus_welcome",
            "subscription": "sub_welcome",
            "metadata": {"pending_signup_id": str(pending.pk)},
        }
        with self.captureOnCommitCallbacks(execute=True):
            fulfill_checkout_session(session)
        mock_welcome.assert_called_once_with(email="welcome@example.com")
        mock_check_in.assert_called_once()
        self.assertEqual(mock_check_in.call_args.args[0].email, "welcome@example.com")

        with self.captureOnCommitCallbacks(execute=True):
            fulfill_checkout_session(session)
        mock_welcome.assert_called_once_with(email="welcome@example.com")
        mock_check_in.assert_called_once()


class WelcomeEmailTests(TestCase):
    def test_greeting_name_from_email(self):
        self.assertEqual(greeting_name("jane.doe+promo@example.com"), "Jane Doe")
        self.assertEqual(greeting_name("123@example.com"), "there")

    @override_settings(
        RESEND_API_KEY="re_test",
        DEFAULT_FROM_EMAIL="Tom <hello@mail.yourramble.com>",
        EMAIL_REPLY_TO="tom@yourramble.com",
        PUBLIC_BASE_URL="https://yourramble.com",
        APP_STORE_URL="https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
    )
    @patch("accounts.emails.resend.Emails.send")
    def test_send_welcome_email_payload(self, mock_send):
        mock_send.return_value = {"id": "email_test"}
        self.assertTrue(send_welcome_email(email="jane.doe@example.com"))
        mock_send.assert_called_once()
        payload = mock_send.call_args.args[0]
        self.assertEqual(payload["from"], "Tom <hello@mail.yourramble.com>")
        self.assertEqual(payload["to"], ["jane.doe@example.com"])
        self.assertEqual(payload["reply_to"], "tom@yourramble.com")
        self.assertEqual(payload["subject"], "You're in. Here's how to start")
        self.assertIn("Hi Jane Doe,", payload["html"])
        self.assertIn("<strong>jane.doe@example.com</strong>", payload["html"])
        self.assertIn("https://yourramble.com/settings/", payload["html"])
        self.assertIn("https://yourramble.com/privacy/", payload["html"])
        self.assertIn("Hi Jane Doe,", payload["text"])

    @override_settings(RESEND_API_KEY="")
    @patch("accounts.emails.resend.Emails.send")
    def test_send_welcome_email_skipped_without_key(self, mock_send):
        self.assertFalse(send_welcome_email(email="skip@example.com"))
        mock_send.assert_not_called()

    @override_settings(
        RESEND_API_KEY="re_test",
        DEFAULT_FROM_EMAIL="Tom <hello@mail.yourramble.com>",
        EMAIL_REPLY_TO="tom@yourramble.com",
        PUBLIC_BASE_URL="https://yourramble.com",
        APP_STORE_URL="https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
    )
    @patch("accounts.emails.resend.Emails.send")
    def test_send_check_in_email_scheduled(self, mock_send):
        mock_send.return_value = {"id": "email_check_in"}
        self.assertTrue(
            send_check_in_email(
                email="jane.doe@example.com",
                scheduled_at="2026-11-20T20:00:00Z",
            )
        )
        payload = mock_send.call_args.args[0]
        self.assertEqual(payload["subject"], "Quick check-in")
        self.assertEqual(payload["scheduled_at"], "2026-11-20T20:00:00Z")
        self.assertIn("Hello,", payload["html"])
        self.assertIn("How have you found Ramble so far?", payload["text"])
        self.assertIn("next time a thought pops up", payload["text"])

    @override_settings(
        RESEND_API_KEY="re_test",
        DEFAULT_FROM_EMAIL="Tom <hello@mail.yourramble.com>",
        EMAIL_REPLY_TO="tom@yourramble.com",
        PUBLIC_BASE_URL="https://yourramble.com",
    )
    @patch("accounts.emails.resend.Emails.send")
    def test_schedule_check_in_email_for_new_user(self, mock_send):
        mock_send.return_value = {"id": "email_check_in"}
        user = User.objects.create_user("checkin@example.com", "password12")
        self.assertTrue(schedule_check_in_email_for_user(user))
        user.refresh_from_db()
        self.assertIsNotNone(user.check_in_email_scheduled_at)
        payload = mock_send.call_args.args[0]
        self.assertEqual(payload["subject"], "Quick check-in")
        self.assertIn("scheduled_at", payload)
        self.assertFalse(schedule_check_in_email_for_user(user))
        self.assertEqual(mock_send.call_count, 1)

    @override_settings(RESEND_API_KEY="re_test")
    @patch("accounts.emails.resend.Emails.send")
    def test_schedule_check_in_email_sends_immediately_when_due(self, mock_send):
        mock_send.return_value = {"id": "email_check_in"}
        user = User.objects.create_user("due@example.com", "password12")
        User.objects.filter(pk=user.pk).update(
            date_joined=timezone.now() - timedelta(days=4)
        )
        user.refresh_from_db()
        self.assertTrue(schedule_check_in_email_for_user(user))
        payload = mock_send.call_args.args[0]
        self.assertNotIn("scheduled_at", payload)


class BillingPortalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "portal@example.com",
            "password12",
            stripe_customer_id="cus_portal",
            subscription_status="active",
        )

    @patch("accounts.views.refresh_user_subscription", return_value=False)
    def test_settings_shows_manage_subscription(self, _refresh):
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Active subscription")
        self.assertContains(response, "Manage subscription")
        self.assertContains(response, reverse("billing_portal"))
        self.assertContains(
            response,
            "If you cancel, recording pauses immediately",
        )
        self.assertNotContains(response, "free trial")

    @patch("accounts.views.refresh_user_subscription", return_value=False)
    def test_settings_shows_upgrade_when_inactive(self, _refresh):
        self.user.account_active = False
        self.user.subscription_status = "canceled"
        self.user.save(update_fields=["account_active", "subscription_status"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Inactive subscription")
        self.assertContains(response, "Upgrade account")
        self.assertContains(response, 'class="nav-inactive')
        self.assertContains(response, ">Inactive</a>")
        self.assertNotContains(response, "Manage subscription")
        self.assertNotContains(response, "free trial")

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_x",
        STRIPE_PORTAL_CONFIGURATION_ID="bpc_test_x",
    )
    @patch("accounts.views.create_billing_portal_session")
    def test_billing_portal_redirects(self, mock_portal):
        mock_portal.return_value = MagicMock(url="https://billing.stripe.com/session/test")
        self.client.force_login(self.user)
        response = self.client.post(reverse("billing_portal"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://billing.stripe.com/session/test")
        _, kwargs = mock_portal.call_args
        self.assertEqual(kwargs["customer_id"], "cus_portal")
        self.assertTrue(kwargs["return_url"].endswith("/settings/"))


class StripeWebhookHandlerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "bill@example.com",
            "password12",
            stripe_customer_id="cus_bill",
            stripe_subscription_id="sub_bill",
            subscription_status="active",
        )

    def test_checkout_completed_creates_account_once(self):
        pending = PendingSignup.create_for_credentials("hook@example.com", "password12")
        event = {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_hook",
                    "status": "complete",
                    "payment_status": "paid",
                    "customer": "cus_hook",
                    "subscription": "sub_hook",
                    "metadata": {"pending_signup_id": str(pending.pk)},
                }
            },
        }
        self.assertTrue(handle_webhook_event(event))
        self.assertFalse(handle_webhook_event(event))
        self.assertEqual(User.objects.filter(email="hook@example.com").count(), 1)
        self.assertEqual(ProcessedStripeEvent.objects.filter(event_id="evt_checkout_1").count(), 1)

    def test_invoice_paid_marks_active(self):
        self.user.subscription_status = "past_due"
        self.user.save(update_fields=["subscription_status"])
        handle_webhook_event(
            {
                "id": "evt_invoice_paid",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_1",
                        "customer": "cus_bill",
                        "subscription": "sub_bill",
                    }
                },
            }
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription_status, "active")

    def test_invoice_payment_failed_marks_past_due(self):
        handle_webhook_event(
            {
                "id": "evt_invoice_fail",
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "id": "in_2",
                        "customer": "cus_bill",
                        "subscription": "sub_bill",
                    }
                },
            }
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription_status, "past_due")

    def test_subscription_deleted_marks_account_inactive(self):
        from notes.models import Note

        Note.objects.create(user=self.user, tidied_text="keep me after cancel")
        handle_webhook_event(
            {
                "id": "evt_sub_deleted",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_bill",
                        "customer": "cus_bill",
                        "status": "canceled",
                    }
                },
            }
        )
        self.user.refresh_from_db()
        self.assertTrue(User.objects.filter(email="bill@example.com").exists())
        self.assertFalse(self.user.account_active)
        self.assertEqual(self.user.subscription_status, "canceled")
        self.assertEqual(self.user.stripe_subscription_id, "")
        self.assertEqual(self.user.stripe_customer_id, "cus_bill")
        self.assertEqual(Note.objects.count(), 1)

    def test_invoice_paid_reactivates_inactive_account(self):
        self.user.account_active = False
        self.user.subscription_status = "canceled"
        self.user.save(update_fields=["account_active", "subscription_status"])
        handle_webhook_event(
            {
                "id": "evt_invoice_reactivate",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_reactivate",
                        "customer": "cus_bill",
                        "subscription": "sub_bill",
                    }
                },
            }
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.account_active)
        self.assertEqual(self.user.subscription_status, "active")

    def test_subscription_updated_cancel_at_period_end_marks_inactive(self):
        handle_webhook_event(
            {
                "id": "evt_sub_cancelling",
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_bill",
                        "customer": "cus_bill",
                        "status": "active",
                        "cancel_at_period_end": True,
                    }
                },
            }
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription_status, "cancelling")
        self.assertFalse(self.user.account_active)
        self.assertTrue(User.objects.filter(email="bill@example.com").exists())

    def test_subscription_updated_trial_cancel_at_marks_inactive(self):
        """Trial cancels set cancel_at/canceled_at, not cancel_at_period_end."""
        handle_webhook_event(
            {
                "id": "evt_sub_trial_cancel",
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_bill",
                        "customer": "cus_bill",
                        "status": "trialing",
                        "cancel_at_period_end": False,
                        "canceled_at": 1794339849,
                        "cancel_at": 1794858884,
                        "cancellation_details": {"reason": "cancellation_requested"},
                    }
                },
            }
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription_status, "cancelling")
        self.assertFalse(self.user.account_active)


class AuthAPIAccountActiveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("status@example.com", "password12")

    def test_me_includes_account_active(self):
        login = self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": "password12"},
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["account_active"])
        token = login.json()["token"]
        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=f"Token {token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["account_active"])

        self.user.account_active = False
        self.user.save(update_fields=["account_active"])
        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=f"Token {token}",
        )
        self.assertFalse(response.json()["account_active"])


class LoginRateLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rate@example.com", "password12")

    @override_settings(AXES_FAILURE_LIMIT=3, AXES_COOLOFF_TIME=None)
    def test_login_locks_after_repeated_failures(self):
        login_url = reverse("login")
        for _ in range(2):
            response = self.client.post(
                login_url,
                {"username": self.user.email, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)

        locked = self.client.post(
            login_url,
            {"username": self.user.email, "password": "wrong-password"},
        )
        self.assertEqual(locked.status_code, 429)
        self.assertContains(locked, "Too many failed sign-in attempts", status_code=429)

    @override_settings(AXES_FAILURE_LIMIT=3, AXES_COOLOFF_TIME=None)
    def test_api_login_locks_after_repeated_failures(self):
        for _ in range(2):
            response = self.client.post(
                "/api/auth/login/",
                {"email": self.user.email, "password": "wrong-password"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

        locked = self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": "wrong-password"},
            content_type="application/json",
        )
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Too many failed sign-in attempts", locked.json()["detail"])

    @override_settings(AXES_FAILURE_LIMIT=3, AXES_COOLOFF_TIME=None)
    def test_admin_login_locks_after_repeated_failures(self):
        login_url = f"/{settings.ADMIN_URL}/login/"
        for _ in range(2):
            response = self.client.post(
                login_url,
                {
                    "username": "rate@example.com",
                    "password": "wrong-password",
                    "next": f"/{settings.ADMIN_URL}/",
                },
            )
            self.assertEqual(response.status_code, 200)

        locked = self.client.post(
            login_url,
            {
                "username": "rate@example.com",
                "password": "wrong-password",
                "next": f"/{settings.ADMIN_URL}/",
            },
        )
        self.assertEqual(locked.status_code, 429)


class AdminLoginTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin@example.com", "password12")

    def test_admin_login_is_password_only(self):
        login_url = f"/{settings.ADMIN_URL}/login/"
        response = self.client.get(login_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "otp_token")

        allowed = self.client.post(
            login_url,
            {
                "username": self.admin.email,
                "password": "password12",
                "next": f"/{settings.ADMIN_URL}/",
            },
        )
        self.assertEqual(allowed.status_code, 302)


class KpiDashboardTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser("boss@example.com", "password12")
        self.user = User.objects.create_user("member@example.com", "password12")
        joined = timezone.now() - timedelta(days=10)
        User.objects.filter(pk=self.user.pk).update(date_joined=joined)
        self.user.refresh_from_db()
        first = timezone.now() - timedelta(days=8)
        second = timezone.now() - timedelta(days=7)
        Note.objects.create(user=self.user, created_at=first, tidied_text="one")
        Note.objects.create(user=self.user, created_at=second, tidied_text="two")

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("kpi"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_regular_user_forbidden(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("kpi"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_sees_table_and_nav(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("kpi"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "member@example.com")
        self.assertContains(response, "Signup → 1st")
        self.assertContains(response, reverse("kpi"))
        # Nav link only for superuser
        roll = self.client.get(reverse("notes:list"))
        self.assertContains(roll, reverse("kpi"))

    def test_regular_user_nav_hides_kpi(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notes:list"))
        self.assertNotContains(response, reverse("kpi"))

    def test_user_kpis_compute_gaps(self):
        rows = {row.email: row for row in user_kpis()}
        member = rows["member@example.com"]
        self.assertEqual(member.take_count, 2)
        self.assertIsNotNone(member.signup_to_first)
        self.assertIsNotNone(member.first_to_second)
        self.assertAlmostEqual(
            member.signup_to_first.total_seconds(),
            timedelta(days=2).total_seconds(),
            delta=60,
        )
        self.assertAlmostEqual(
            member.first_to_second.total_seconds(),
            timedelta(days=1).total_seconds(),
            delta=60,
        )
        self.assertEqual(format_duration(timedelta(days=2, hours=3)), "2d 3h")
        self.assertEqual(format_duration(None), "-")


class CrmDashboardTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser("boss@example.com", "password12")
        self.user = User.objects.create_user("member@example.com", "password12")
        self.contact = CrmContact.objects.create(
            first_name="Ada",
            business_name="Analytical Engines",
            contact_type="celebrant",
            region="London",
            country="UK",
            website="https://example.com",
            email="ada@example.com",
            email_source="LinkedIn",
            personalisation_detail="Loves notebooks",
            tracking_slug="analytical-engines",
        )

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("crm"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_regular_user_forbidden(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("crm"))
        self.assertEqual(response.status_code, 403)

    @override_settings(
        PUBLIC_BASE_URL="https://yourramble.com",
        TRACKING_BASE_URL="https://yourramble.com",
    )
    def test_superuser_sees_table_and_nav(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("crm"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytical Engines")
        self.assertContains(response, "ada@example.com")
        self.assertContains(response, "analytical-engines")
        self.assertContains(response, "https://yourramble.com/signup/?ref=analytical-engines")
        self.assertContains(response, reverse("crm"))
        self.assertContains(response, "crm-contact-modal")
        self.assertContains(response, 'data-crm-modal-open')
        edit_page = self.client.get(reverse("crm_edit", args=[self.contact.pk]))
        self.assertContains(edit_page, 'data-crm-open="1"')
        roll = self.client.get(reverse("notes:list"))
        self.assertContains(roll, reverse("crm"))

    def test_regular_user_nav_hides_crm(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notes:list"))
        self.assertNotContains(response, reverse("crm"))

    @override_settings(
        PUBLIC_BASE_URL="https://yourramble.com",
        TRACKING_BASE_URL="https://yourramble.com",
    )
    def test_superuser_can_add_contact(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("crm"),
            {
                "first_name": "Grace",
                "business_name": "Navy Code",
                "contact_type": "celebrant",
                "region": "NY",
                "country": "US",
                "website": "navycode.example.com",
                "email": "grace@example.com",
                "phone": "+1 212 555 0100",
                "email_source": "Conference",
                "source": "UKSOC",
                "personalisation_detail": "Built compilers",
                "notes": "Left voicemail",
                "stage": "emailed",
                "last_contacted_on": "2026-11-10",
                "last_contacted_channel": "email",
                "next_follow_up_on": "2026-11-18",
                "response": "revisit",
                "response_reason": "Ask again next quarter",
                "tracking_slug": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        contact = CrmContact.objects.get(email="grace@example.com")
        self.assertEqual(contact.tracking_slug, "navy-code")
        self.assertEqual(contact.website, "https://navycode.example.com")
        self.assertEqual(contact.tracking_url, "https://yourramble.com/signup/?ref=navy-code")
        self.assertEqual(contact.phone, "+1 212 555 0100")
        self.assertEqual(contact.contact_type, "celebrant")
        self.assertEqual(contact.source, "UKSOC")
        self.assertEqual(contact.notes, "Left voicemail")
        self.assertEqual(contact.stage, "emailed")
        self.assertEqual(str(contact.last_contacted_on), "2026-11-10")
        self.assertEqual(contact.last_contacted_channel, "email")
        self.assertEqual(str(contact.next_follow_up_on), "2026-11-18")
        self.assertFalse(contact.do_not_contact)
        self.assertEqual(contact.response, "revisit")
        self.assertEqual(contact.response_reason, "Ask again next quarter")

    def test_superuser_can_edit_and_delete_contact(self):
        self.client.force_login(self.superuser)
        edit = self.client.post(
            reverse("crm_edit", args=[self.contact.pk]),
            {
                "first_name": "Ada",
                "business_name": "Analytical Engines Ltd",
                "contact_type": "celebrant",
                "region": "London",
                "country": "UK",
                "website": "https://example.com",
                "email": "ada@example.com",
                "phone": "020 7946 0958",
                "email_source": "LinkedIn",
                "source": "The Celebrant Directory",
                "personalisation_detail": "Loves notebooks",
                "notes": "Asked for a callback",
                "stage": "called",
                "last_contacted_on": "2026-11-16",
                "last_contacted_channel": "call",
                "next_follow_up_on": "2026-11-20",
                "do_not_contact": "on",
                "response": "signed_up",
                "response_reason": "Started trial",
                "tracking_slug": "analytical-engines",
            },
        )
        self.assertEqual(edit.status_code, 302)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.business_name, "Analytical Engines Ltd")
        self.assertEqual(self.contact.phone, "020 7946 0958")
        self.assertEqual(self.contact.source, "The Celebrant Directory")
        self.assertEqual(self.contact.notes, "Asked for a callback")
        self.assertEqual(self.contact.stage, "called")
        self.assertEqual(str(self.contact.last_contacted_on), "2026-11-16")
        self.assertEqual(self.contact.last_contacted_channel, "call")
        self.assertEqual(str(self.contact.next_follow_up_on), "2026-11-20")
        self.assertTrue(self.contact.do_not_contact)
        self.assertEqual(self.contact.response, "signed_up")
        self.assertEqual(self.contact.response_reason, "Started trial")
        listed = self.client.get(reverse("crm"))
        self.assertContains(listed, "Signed up")
        self.assertContains(listed, "Started trial")
        self.assertContains(listed, "Asked for a callback")
        self.assertContains(listed, "The Celebrant Directory")

        delete = self.client.post(reverse("crm_delete", args=[self.contact.pk]))
        self.assertEqual(delete.status_code, 302)
        self.assertFalse(CrmContact.objects.filter(pk=self.contact.pk).exists())

    def test_crm_paginates_contacts(self):
        from accounts.views import CRM_PAGE_SIZE

        self.client.force_login(self.superuser)
        for index in range(CRM_PAGE_SIZE):
            CrmContact.objects.create(
                first_name=f"Lead {index}",
                business_name=f"Biz {index:03d}",
                contact_type="celebrant",
                tracking_slug=f"biz-{index:03d}",
            )
        page_one = self.client.get(reverse("crm"))
        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(len(page_one.context["contacts"]), CRM_PAGE_SIZE)
        self.assertContains(page_one, "1 of 2")
        self.assertContains(page_one, "?page=2")
        self.assertContains(page_one, f"{CRM_PAGE_SIZE + 1} contacts")
        self.assertNotContains(page_one, ">Contacts</h2>")

        page_two = self.client.get(reverse("crm"), {"page": 2})
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual(len(page_two.context["contacts"]), 1)
        self.assertContains(page_two, "Biz 049")
        self.assertContains(page_two, "2 of 2")
        self.assertContains(page_one, "Analytical Engines")

    def test_crm_filters_by_type(self):
        self.client.force_login(self.superuser)
        CrmContact.objects.create(
            first_name="Sam",
            business_name="No Type Co",
            tracking_slug="no-type-co",
        )
        filtered = self.client.get(reverse("crm"), {"type": "celebrant"})
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, "Analytical Engines")
        self.assertNotContains(filtered, "No Type Co")
        self.assertEqual(filtered.context["crm_type_filter"], "celebrant")
        self.assertContains(filtered, 'name="type"')
        self.assertContains(filtered, "crm-filter-select")
        self.assertContains(filtered, "crm-heading-actions")

    @override_settings(
        PUBLIC_BASE_URL="https://yourramble.com",
        TRACKING_BASE_URL="https://yourramble.com",
    )
    def test_crm_outreach_email_draft_and_approve(self):
        self.client.force_login(self.superuser)
        listed = self.client.get(reverse("crm"))
        self.assertContains(listed, "Outreach email")
        self.assertContains(listed, "Add")
        self.assertContains(listed, reverse("crm_email_save", args=[self.contact.pk]))
        self.assertContains(listed, reverse("crm_email_approve", args=[self.contact.pk]))

        save = self.client.post(
            reverse("crm_email_save", args=[self.contact.pk]),
            {
                "outreach_email_subject": "Quick note",
                "outreach_email_body": "Hi Ada,\n\nThought of you.",
                "page": "1",
            },
        )
        self.assertEqual(save.status_code, 302)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.outreach_email_status, "draft")
        self.assertEqual(self.contact.outreach_email_subject, "Quick note")
        self.assertIn("Thought of you", self.contact.outreach_email_body)
        self.assertIn(
            "https://yourramble.com/signup/?ref=analytical-engines",
            self.contact.outreach_email_body,
        )

        drafted = self.client.get(reverse("crm"))
        self.assertContains(drafted, "Draft")
        self.assertContains(drafted, "Thought of you")
        self.assertContains(drafted, ">Opened</th>")
        self.assertContains(drafted, "crm-open-badge")
        self.assertContains(drafted, ">No</span>")

        approve = self.client.post(
            reverse("crm_email_approve", args=[self.contact.pk]),
            {
                "outreach_email_subject": "Quick note",
                "outreach_email_body": self.contact.outreach_email_body,
                "page": "1",
            },
        )
        self.assertEqual(approve.status_code, 302)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.outreach_email_status, "approved")
        approved = self.client.get(reverse("crm"))
        self.assertContains(approved, "Approved")

    def test_crm_tracking_open_requires_three_seconds(self):
        from django.utils import timezone
        from datetime import timedelta

        # Confirm before start should begin the timer, not mark opened.
        too_soon = self.client.post(
            reverse("crm_tracking_open_confirm", args=[self.contact.tracking_slug])
        )
        self.assertEqual(too_soon.status_code, 409)
        self.assertEqual(too_soon.json()["status"], "too_soon")
        self.contact.refresh_from_db()
        self.assertIsNotNone(self.contact.outreach_email_open_started_at)
        self.assertIsNone(self.contact.outreach_email_opened_at)

        start = self.client.post(
            reverse("crm_tracking_open_start", args=[self.contact.tracking_slug])
        )
        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.json()["status"], "started")

        early = self.client.post(
            reverse("crm_tracking_open_confirm", args=[self.contact.tracking_slug])
        )
        self.assertEqual(early.status_code, 409)
        self.assertIn("retry_after_ms", early.json())
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.outreach_email_opened_at)

        self.contact.outreach_email_open_started_at = timezone.now() - timedelta(seconds=3)
        self.contact.save(update_fields=["outreach_email_open_started_at"])
        confirm = self.client.post(
            reverse("crm_tracking_open_confirm", args=[self.contact.tracking_slug])
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["status"], "opened")
        self.contact.refresh_from_db()
        self.assertIsNotNone(self.contact.outreach_email_opened_at)

        self.client.force_login(self.superuser)
        self.contact.outreach_email_status = "draft"
        self.contact.outreach_email_body = "Hello"
        self.contact.save(
            update_fields=["outreach_email_status", "outreach_email_body", "updated_at"]
        )
        listed = self.client.get(reverse("crm"))
        self.assertContains(listed, 'crm-open-badge is-opened')
        self.assertContains(listed, ">Yes</span>")

    def test_crm_tracking_open_ignores_prefetch(self):
        ignored = self.client.post(
            reverse("crm_tracking_open_start", args=[self.contact.tracking_slug]),
            HTTP_SEC_PURPOSE="prefetch",
        )
        self.assertEqual(ignored.status_code, 204)
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.outreach_email_open_started_at)

    def test_signed_in_home_keeps_ref_for_open_tracking(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/?ref=analytical-engines")
        self.assertEqual(response.status_code, 302)
        self.assertIn("ref=analytical-engines", response["Location"])
        landed = self.client.get(response["Location"])
        self.assertEqual(landed.status_code, 200)
        self.assertContains(landed, "crm-open-track.js")

    def test_signed_in_signup_keeps_ref_for_open_tracking(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/signup/?ref=analytical-engines")
        self.assertEqual(response.status_code, 302)
        self.assertIn("ref=analytical-engines", response["Location"])
        landed = self.client.get(response["Location"])
        self.assertEqual(landed.status_code, 200)
        self.assertContains(landed, "crm-open-track.js")
