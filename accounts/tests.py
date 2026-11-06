from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from notes.models import Note

from .emails import greeting_name, send_welcome_email
from .kpi import format_duration, user_kpis
from .models import PendingSignup, ProcessedStripeEvent
from .stripe_billing import fulfill_checkout_session, handle_webhook_event

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
        self.assertContains(response, "Continue to payment")
        self.assertContains(response, "By signing up, you are agreeing to our")
        self.assertContains(response, "Terms of Use")
        self.assertContains(response, reverse("notes:terms"))
        self.assertContains(response, "Secure payment with Stripe")
        self.assertContains(response, "Give your thoughts somewhere to go.")
        self.assertContains(response, "An iPhone app, plus the web.")
        self.assertContains(response, "Talk into your phone. Read it anywhere, same words.")
        self.assertContains(response, "£9.99 a month")
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
        self.assertContains(response, reverse("notes:list"))
        user = User.objects.get(email="paid@example.com")
        self.assertTrue(user.check_password("password12"))
        self.assertEqual(user.stripe_customer_id, "cus_123")
        self.assertEqual(user.stripe_subscription_id, "sub_123")
        self.assertEqual(user.subscription_status, "active")
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

    @patch("accounts.stripe_billing.send_welcome_email")
    def test_fulfill_sends_welcome_email_once(self, mock_welcome):
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

        with self.captureOnCommitCallbacks(execute=True):
            fulfill_checkout_session(session)
        mock_welcome.assert_called_once_with(email="welcome@example.com")


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


class BillingPortalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "portal@example.com",
            "password12",
            stripe_customer_id="cus_portal",
            subscription_status="active",
        )

    def test_settings_shows_manage_subscription(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Manage subscription")
        self.assertContains(response, reverse("billing_portal"))
        self.assertContains(
            response,
            "If you cancel, your account and all your rambles will be deleted",
        )

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

    def test_subscription_deleted_removes_account(self):
        from notes.models import Note

        Note.objects.create(user=self.user, tidied_text="keep me until cancel")
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
        self.assertFalse(User.objects.filter(email="bill@example.com").exists())
        self.assertEqual(Note.objects.count(), 0)

    def test_subscription_updated_cancel_at_period_end_marks_cancelling(self):
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
        self.assertTrue(User.objects.filter(email="bill@example.com").exists())


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
