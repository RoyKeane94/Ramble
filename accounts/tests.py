from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


class AuthPageTests(TestCase):
    def test_login_autocomplete(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertNotContains(response, 'autocomplete="off"')

    def test_register_autocomplete_and_no_store(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertContains(response, 'autocomplete="email"')
        self.assertContains(response, 'autocomplete="new-password"')
        self.assertNotContains(response, 'autocomplete="off"')


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
