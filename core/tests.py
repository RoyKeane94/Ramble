import os
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from config.settings import _admin_url
from core.middleware import SecurityHeadersMiddleware
from core.models import TrafficHit
from core.traffic import prune_traffic, traffic_report, visitor_hash


class AdminUrlConfigTests(SimpleTestCase):
    def test_rejects_hostname_in_admin_url(self):
        with patch.dict(os.environ, {"ADMIN_URL": "yourramble.com/admin"}):
            with self.assertRaises(ImproperlyConfigured):
                _admin_url()

    def test_rejects_absolute_url(self):
        with patch.dict(os.environ, {"ADMIN_URL": "https://yourramble.com/admin"}):
            with self.assertRaises(ImproperlyConfigured):
                _admin_url()

    def test_accepts_path_segment(self):
        with patch.dict(os.environ, {"ADMIN_URL": "secret-panel"}):
            self.assertEqual(_admin_url(), "secret-panel")



class SecurityHeaderTests(SimpleTestCase):
    def test_csp_and_permissions_policy(self):
        middleware = SecurityHeadersMiddleware(lambda _request: HttpResponse("ok"))
        response = middleware(RequestFactory().get("/"))
        csp = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("https://fonts.googleapis.com", csp)
        self.assertIn("script-src 'self' https://js.stripe.com", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
        self.assertIn("microphone=(self)", response["Permissions-Policy"])
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertEqual(response["Cross-Origin-Resource-Policy"], "same-origin")

    @override_settings(
        SECURE_HSTS_SECONDS=31536000,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_HSTS_PRELOAD=True,
    )
    def test_hsts_on_https(self):
        middleware = SecurityMiddleware(lambda _request: HttpResponse("ok"))
        response = middleware(RequestFactory().get("/", secure=True))
        self.assertEqual(
            response["Strict-Transport-Security"],
            "max-age=31536000; includeSubDomains; preload",
        )


class WellKnownEndpointTests(SimpleTestCase):
    def test_robots_txt_disallows_admin_and_mcp(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Disallow: /mcp", body)
        self.assertIn("Disallow: /api/", body)
        self.assertIn("Disallow: /roll/", body)
        self.assertIn("Disallow: /notes/", body)
        self.assertIn("Allow: /llms.txt", body)
        self.assertIn("/llms.txt", body)
        self.assertNotIn("yourramble.com", body)

    @override_settings(ADMIN_URL="secret-panel")
    def test_robots_txt_does_not_advertise_custom_admin_url(self):
        response = self.client.get("/robots.txt")
        body = response.content.decode()
        self.assertIn("Disallow: /admin/", body)
        self.assertNotIn("secret-panel", body)

    def test_llms_txt(self):
        response = self.client.get("/llms.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        body = response.content.decode()
        self.assertTrue(body.startswith("# Ramble\n"))
        self.assertIn("> Talk your idea through before it disappears.", body)
        self.assertIn("[Home](", body)
        self.assertIn("/privacy/", body)
        self.assertIn("/terms/", body)
        self.assertIn("/support/", body)
        self.assertIn("## Optional", body)
        self.assertIn("apps.apple.com", body)

    def test_security_txt(self):
        response = self.client.get("/.well-known/security.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("Contact:", body)
        self.assertIn("/support/", body)
        self.assertIn("Expires:", body)
        self.assertIn("Canonical:", body)
        self.assertIn("/.well-known/security.txt", body)


class TrafficRecordingTests(TestCase):
    def test_homepage_counts_once_per_visitor_per_day(self):
        ua = "Mozilla/5.0 RambleTest"
        self.assertEqual(self.client.get("/", HTTP_USER_AGENT=ua).status_code, 200)
        self.client.get("/", HTTP_USER_AGENT=ua)
        hit = TrafficHit.objects.get()
        self.assertEqual(hit.path, "/")
        self.assertEqual(hit.views, 2)
        self.assertEqual(hit.referrer, "")
        self.assertNotIn("127.0.0.1", hit.visitor_hash)
        self.assertEqual(len(hit.visitor_hash), 32)

    def test_query_string_is_not_stored(self):
        self.client.get("/?utm_source=twitter", HTTP_USER_AGENT="Mozilla/5.0 RambleTest")
        self.assertEqual(TrafficHit.objects.get().path, "/")

    def test_external_referrer_is_hostname_only(self):
        self.client.get(
            "/",
            HTTP_USER_AGENT="Mozilla/5.0 RambleTest",
            HTTP_REFERER="https://www.google.com/search?q=ramble",
        )
        self.assertEqual(TrafficHit.objects.get().referrer, "google.com")

    def test_later_pages_keep_the_first_source(self):
        ua = "Mozilla/5.0 RambleTest"
        self.client.get(
            "/",
            HTTP_USER_AGENT=ua,
            HTTP_REFERER="https://news.ycombinator.com/item?id=1",
        )
        self.client.get("/signup/", HTTP_USER_AGENT=ua, HTTP_REFERER="http://testserver/")
        signup = TrafficHit.objects.get(path="/signup/")
        self.assertEqual(signup.referrer, "news.ycombinator.com")

    def test_canonical_host_referrer_counts_as_direct(self):
        self.client.get(
            "/signup/",
            HTTP_USER_AGENT="Mozilla/5.0 RambleTest",
            HTTP_REFERER="https://yourramble.com/",
        )
        self.assertEqual(TrafficHit.objects.get().referrer, "")

    def test_signed_in_visit_is_ignored(self):
        user = get_user_model().objects.create_user("member@example.com", "password12")
        self.client.force_login(user)
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TrafficHit.objects.count(), 0)

    def test_bots_and_non_pages_are_ignored(self):
        self.client.get("/", HTTP_USER_AGENT="Mozilla/5.0 (compatible; Googlebot/2.1)")
        self.client.get("/robots.txt")
        self.client.get("/", HTTP_SEC_PURPOSE="prefetch", HTTP_USER_AGENT="Mozilla/5.0 RambleTest")
        self.client.post("/login/", {"username": "a@example.com", "password": "nope"})
        self.assertEqual(TrafficHit.objects.count(), 0)

    def test_recording_failure_still_returns_the_page(self):
        with patch("core.middleware.record_page_view", side_effect=RuntimeError("db")):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_hash_changes_each_day_and_hides_the_ip(self):
        day = timezone.localdate()
        first = visitor_hash("203.0.113.8", "Mozilla/5.0", day)
        nxt = visitor_hash("203.0.113.8", "Mozilla/5.0", day + timedelta(days=1))
        other = visitor_hash("203.0.113.9", "Mozilla/5.0", day)
        self.assertNotEqual(first, nxt)
        self.assertNotEqual(first, other)
        self.assertNotIn("203.0.113.8", first)

    def test_forwarded_for_uses_the_first_address(self):
        ua = "Mozilla/5.0 RambleTest"
        self.client.get("/", HTTP_USER_AGENT=ua, HTTP_X_FORWARDED_FOR="203.0.113.8, 10.0.0.1")
        expected = visitor_hash("203.0.113.8", ua, timezone.localdate())
        self.assertEqual(TrafficHit.objects.get().visitor_hash, expected)


class TrafficReportTests(TestCase):
    def test_windows_and_dashboard(self):
        today = timezone.localdate()
        TrafficHit.objects.create(
            day=today, path="/", referrer="google.com", visitor_hash="a" * 32, views=3
        )
        TrafficHit.objects.create(
            day=today, path="/signup/", referrer="google.com", visitor_hash="a" * 32, views=1
        )
        TrafficHit.objects.create(
            day=today - timedelta(days=10),
            path="/",
            referrer="",
            visitor_hash="b" * 32,
            views=2,
        )

        report = traffic_report(today)
        week, month = report["windows"]
        self.assertEqual(week["visitors"], 1)
        self.assertEqual(week["pageviews_label"], "4 page views")
        self.assertEqual(month["visitors"], 2)
        self.assertEqual(month["pageviews_label"], "6 page views")
        self.assertEqual(report["pages"][0]["path"], "/")
        self.assertEqual(report["pages"][0]["views"], 5)
        self.assertEqual(report["pages"][0]["visitors"], 2)
        self.assertEqual(report["sources"][0], {"label": "google.com", "views": 4})
        self.assertEqual(report["sources"][1], {"label": "Direct", "views": 2})

        get_user_model().objects.create_superuser("boss@example.com", "password12")
        self.client.force_login(get_user_model().objects.get(email="boss@example.com"))
        response = self.client.get("/kpi/")
        self.assertContains(response, "Traffic")
        self.assertContains(response, "google.com")
        self.assertContains(response, "4 page views")
        self.assertContains(response, "6 page views")
        self.assertContains(response, "Direct")

    def test_prune_drops_rows_older_than_ninety_days(self):
        today = timezone.localdate()
        TrafficHit.objects.create(
            day=today - timedelta(days=91),
            path="/",
            visitor_hash="c" * 32,
            views=1,
        )
        TrafficHit.objects.create(
            day=today - timedelta(days=90),
            path="/",
            visitor_hash="d" * 32,
            views=1,
        )
        prune_traffic(today)
        self.assertEqual(list(TrafficHit.objects.values_list("visitor_hash", flat=True)), ["d" * 32])
