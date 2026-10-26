from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware import SecurityHeadersMiddleware


class SecurityHeaderTests(SimpleTestCase):
    def test_csp_and_permissions_policy(self):
        middleware = SecurityHeadersMiddleware(lambda _request: HttpResponse("ok"))
        response = middleware(RequestFactory().get("/"))
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertIn("https://fonts.googleapis.com", response["Content-Security-Policy"])
        self.assertIn("microphone=(self)", response["Permissions-Policy"])
        self.assertIn("camera=()", response["Permissions-Policy"])

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
        self.assertIn("Disallow: /admin/", response.content.decode())
        self.assertIn("Disallow: /mcp", response.content.decode())

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
