import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import CrmContact
from ramble_mcp.views import mcp_endpoint

from notes.models import Album, Note

User = get_user_model()


class McpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tom@example.com", "password12")
        self.other = User.objects.create_user("other@example.com", "password12")
        self.token = self.user.issue_mcp_token()
        self.other_token = self.other.issue_mcp_token()
        self.now = timezone.now()
        self.pricing = Note.objects.create(
            user=self.user,
            created_at=self.now - timedelta(days=2),
            tidied_text="We should raise pricing next quarter.",
            gpt_tidied_text="We should raise pricing next quarter.",
            did_gpt_tidy=True,
            duration=42,
            is_starred=True,
        )
        self.lunch = Note.objects.create(
            user=self.user,
            created_at=self.now - timedelta(hours=3),
            tidied_text="Pick up lunch on the way home.",
            gpt_tidied_text="Pick up lunch on the way home.",
            did_gpt_tidy=True,
            duration=12,
        )
        self.album = Album.create_for_user(self.user, "Work")
        self.album.notes.add(self.pricing)
        Note.objects.create(
            user=self.other,
            tidied_text="Secret pricing for someone else.",
            gpt_tidied_text="Secret pricing for someone else.",
            did_gpt_tidy=True,
        )

    def rpc(self, method, params=None, token=None, msg_id=1, path="/mcp"):
        body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            body["params"] = params
        return self.client.post(
            path,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token if token is not None else self.token}",
        )

    def call(self, name, arguments=None, token=None, path="/mcp"):
        response = self.rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            token=token,
            path=path,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("result", payload)
        return payload["result"]

    def test_rejects_missing_token(self):
        response = self.client.post(
            "/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_wrong_token(self):
        response = self.rpc("initialize", {}, token="rmbl_not-a-real-token")
        self.assertEqual(response.status_code, 401)

    def test_initialize_and_list_tools(self):
        response = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["serverInfo"]["name"], "ramble")
        names = [tool["name"] for tool in self.rpc("tools/list").json()["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "search_takes",
                "list_recent_takes",
                "get_take",
                "list_albums",
                "update_take",
                "create_album",
            ],
        )

    def test_search_by_words_album_starred_and_date(self):
        result = self.call(
            "search_takes",
            {
                "query": "pricing",
                "album": "Work",
                "starred": True,
                "since": (self.now - timedelta(days=7)).date().isoformat(),
            },
        )
        ids = [take["id"] for take in result["structuredContent"]["takes"]]
        self.assertEqual(ids, [str(self.pricing.id)])
        self.assertIn("updated_at", result["structuredContent"]["takes"][0])

    def test_list_recent_newest_first(self):
        result = self.call("list_recent_takes", {"limit": 10})
        ids = [take["id"] for take in result["structuredContent"]["takes"]]
        self.assertEqual(ids[0], str(self.lunch.id))
        self.assertTrue(ids.index(str(self.lunch.id)) < ids.index(str(self.pricing.id)))

    def test_updated_since_picks_up_changes(self):
        older = timezone.now() - timedelta(days=1)
        Note.objects.filter(id=self.lunch.id).update(updated_at=older)
        result = self.call(
            "list_recent_takes",
            {"updated_since": (timezone.now() - timedelta(minutes=1)).isoformat()},
        )
        ids = [take["id"] for take in result["structuredContent"]["takes"]]
        self.assertIn(str(self.pricing.id), ids)
        self.assertNotIn(str(self.lunch.id), ids)

    def test_get_take_full_text(self):
        result = self.call("get_take", {"take_id": str(self.pricing.id)})
        take = result["structuredContent"]
        self.assertEqual(take["text"], "We should raise pricing next quarter.")
        self.assertEqual(take["starred"], True)
        self.assertEqual(take["albums"][0]["name"], "Work")
        self.assertIn("created_at", take)
        self.assertIn("updated_at", take)
        self.assertEqual(take["duration_seconds"], 42.0)

    def test_list_albums_with_counts(self):
        result = self.call("list_albums")
        data = result["structuredContent"]
        self.assertEqual(data["starred_count"], 1)
        self.assertEqual(data["albums"][0]["name"], "Work")
        self.assertEqual(data["albums"][0]["take_count"], 1)

    def test_move_and_star(self):
        ideas = self.call("create_album", {"name": "Ideas"})
        album_id = ideas["structuredContent"]["id"]
        moved = self.call(
            "update_take",
            {"take_id": str(self.lunch.id), "album": album_id, "starred": True},
        )
        take = moved["structuredContent"]
        self.assertTrue(take["starred"])
        self.assertEqual(take["albums"][0]["name"], "Ideas")
        self.lunch.refresh_from_db()
        self.assertTrue(self.lunch.is_starred)
        self.assertTrue(Album.objects.get(id=album_id).notes.filter(id=self.lunch.id).exists())

    def test_cannot_see_another_users_takes(self):
        result = self.call("search_takes", {"query": "pricing"}, token=self.other_token)
        ids = [take["id"] for take in result["structuredContent"]["takes"]]
        self.assertNotIn(str(self.pricing.id), ids)
        missing = self.call("get_take", {"take_id": str(self.pricing.id)}, token=self.other_token)
        self.assertTrue(missing["isError"])

    def test_session_cookie_is_not_enough(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_options_cors(self):
        request = RequestFactory().options("/mcp", HTTP_ORIGIN="https://claude.ai")
        response = mcp_endpoint(request)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://claude.ai")
        self.assertIn("Authorization", response["Access-Control-Allow-Headers"])

    @override_settings(CORS_ALLOW_ALL_ORIGINS=False, CORS_ALLOWED_ORIGINS=[])
    def test_options_preflight_returns_allow_headers(self):
        response = self.client.options(
            "/mcp",
            HTTP_ORIGIN="https://claude.ai",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type,mcp-protocol-version",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://claude.ai")
        self.assertIn("Authorization", response["Access-Control-Allow-Headers"])
        self.assertIn("POST", response["Access-Control-Allow-Methods"])
        self.assertIn("OPTIONS", response["Access-Control-Allow-Methods"])
        self.assertIn("MCP-Protocol-Version", response["Access-Control-Allow-Headers"])

    def test_settings_shows_mcp_and_issues_token(self):
        self.client.force_login(self.user)
        page = self.client.get("/settings/")
        self.assertContains(page, "Claude MCP")
        self.assertContains(page, "Grok Bot MCP")
        self.assertContains(page, "/mcp")
        self.assertContains(page, "/mcp/grok")
        self.assertContains(page, "custom connector")
        self.assertContains(page, "Replace token")
        self.assertContains(page, "New-take alerts")
        self.assertContains(page, "Save webhook")
        created = self.client.post("/settings/", {"intent": "mcp_token"})
        self.assertContains(created, "Copy this token now")
        self.assertContains(created, "rmbl_")
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_mcp_token)

        self.user.save_take_ready_webhook(
            "https://api2.cursor.sh/automations/webhook/example",
            "whsec_test_key",
        )
        connected = self.client.get("/settings/")
        self.assertContains(connected, "Webhook connected")
        self.assertContains(connected, "Replace webhook")
        self.assertNotContains(connected, "Save webhook")

    def test_settings_saves_replaces_and_clears_take_ready_webhook(self):
        self.client.force_login(self.user)
        saved = self.client.post(
            "/settings/",
            {
                "intent": "take_ready_webhook",
                "url": "https://api2.cursor.sh/automations/webhook/one",
                "key": "whsec_one",
            },
        )
        self.assertContains(saved, "Webhook saved")
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.take_ready_webhook_url,
            "https://api2.cursor.sh/automations/webhook/one",
        )
        self.assertEqual(self.user.take_ready_webhook_key, "whsec_one")

        edit = self.client.post("/settings/", {"intent": "edit_take_ready_webhook"})
        self.assertContains(edit, "Replace webhook")
        self.assertContains(edit, "Webhook URL")

        replaced = self.client.post(
            "/settings/",
            {
                "intent": "take_ready_webhook",
                "url": "https://api2.cursor.sh/automations/webhook/two",
                "key": "whsec_two",
            },
        )
        self.assertContains(replaced, "Webhook saved")
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.take_ready_webhook_url,
            "https://api2.cursor.sh/automations/webhook/two",
        )
        self.assertEqual(self.user.take_ready_webhook_key, "whsec_two")

        rejected = self.client.post(
            "/settings/",
            {
                "intent": "take_ready_webhook",
                "url": "http://insecure.example/hook",
                "key": "x",
            },
        )
        self.assertContains(rejected, "Use an https webhook URL.")
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.take_ready_webhook_url,
            "https://api2.cursor.sh/automations/webhook/two",
        )

        cleared = self.client.post(
            "/settings/",
            {"intent": "clear_take_ready_webhook"},
        )
        self.assertContains(cleared, "Webhook cleared")
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_take_ready_webhook)

    def test_webhook_tools_only_on_grok_surface(self):
        claude_names = [
            tool["name"] for tool in self.rpc("tools/list").json()["result"]["tools"]
        ]
        self.assertNotIn("save_take_ready_webhook", claude_names)
        self.assertNotIn("clear_take_ready_webhook", claude_names)
        self.assertNotIn("get_take_ready_webhook_status", claude_names)
        denied = self.call(
            "save_take_ready_webhook", {"url": "https://example.com/hook", "key": "x"}
        )
        self.assertTrue(denied.get("isError"))

        grok_names = [
            tool["name"]
            for tool in self.rpc("tools/list", path="/mcp/grok").json()["result"]["tools"]
        ]
        self.assertIn("save_take_ready_webhook", grok_names)
        self.assertIn("clear_take_ready_webhook", grok_names)
        self.assertIn("get_take_ready_webhook_status", grok_names)

        saved = self.call(
            "save_take_ready_webhook",
            {
                "url": "https://api2.cursor.sh/automations/webhook/example",
                "key": "whsec_test",
            },
            path="/mcp/grok",
        )["structuredContent"]
        self.assertTrue(saved["configured"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_take_ready_webhook)

        status = self.call("get_take_ready_webhook_status", path="/mcp/grok")[
            "structuredContent"
        ]
        self.assertTrue(status["configured"])
        self.assertEqual(status["url_host"], "api2.cursor.sh")
        self.assertNotIn("key", status)

        cleared = self.call("clear_take_ready_webhook", path="/mcp/grok")[
            "structuredContent"
        ]
        self.assertFalse(cleared["configured"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_take_ready_webhook)

    def test_get_kpis_not_exposed(self):
        denied = self.call("get_kpis")
        self.assertTrue(denied.get("isError"))
        names = [tool["name"] for tool in self.rpc("tools/list").json()["result"]["tools"]]
        self.assertNotIn("get_kpis", names)

        admin = User.objects.create_superuser("admin@example.com", "password12")
        token = admin.issue_mcp_token()
        names = [
            tool["name"]
            for tool in self.rpc("tools/list", token=token, path="/mcp/grok").json()[
                "result"
            ]["tools"]
        ]
        self.assertNotIn("get_kpis", names)

    def test_crm_tools_require_superuser_on_grok_mcp(self):
        names = [tool["name"] for tool in self.rpc("tools/list").json()["result"]["tools"]]
        self.assertNotIn("list_crm_contacts", names)
        denied = self.call("list_crm_contacts")
        self.assertTrue(denied.get("isError"))

        grok_regular = [
            tool["name"]
            for tool in self.rpc("tools/list", path="/mcp/grok").json()["result"]["tools"]
        ]
        self.assertNotIn("list_crm_contacts", grok_regular)
        denied_grok = self.call("list_crm_contacts", path="/mcp/grok")
        self.assertTrue(denied_grok.get("isError"))

        admin = User.objects.create_superuser("crm-admin@example.com", "password12")
        token = admin.issue_mcp_token()
        # Superuser token on Claude URL still must not expose CRM.
        claude_admin = [
            tool["name"]
            for tool in self.rpc("tools/list", token=token).json()["result"]["tools"]
        ]
        self.assertNotIn("list_crm_contacts", claude_admin)

        names = [
            tool["name"]
            for tool in self.rpc("tools/list", token=token, path="/mcp/grok").json()[
                "result"
            ]["tools"]
        ]
        self.assertIn("list_crm_contacts", names)
        self.assertIn("create_crm_contact", names)
        self.assertIn("update_crm_contact", names)
        self.assertIn("delete_crm_contact", names)

        created = self.call(
            "create_crm_contact",
            {
                "first_name": "Ada",
                "business_name": "Analytical Engines",
                "email": "ada@example.com",
                "website": "analytical.example.com",
            },
            token=token,
            path="/mcp/grok",
        )["structuredContent"]
        self.assertEqual(created["tracking_slug"], "analytical-engines")
        self.assertEqual(created["website"], "https://analytical.example.com")
        contact_id = created["id"]

        listed = self.call(
            "list_crm_contacts",
            {"query": "Ada"},
            token=token,
            path="/mcp/grok",
        )["structuredContent"]
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["contacts"][0]["id"], contact_id)

        updated = self.call(
            "update_crm_contact",
            {
                "contact_id": contact_id,
                "region": "London",
                "personalisation_detail": "Loves notebooks",
                "response": "declined",
                "response_reason": "Timing",
            },
            token=token,
            path="/mcp/grok",
        )["structuredContent"]
        self.assertEqual(updated["region"], "London")
        self.assertEqual(updated["personalisation_detail"], "Loves notebooks")
        self.assertEqual(updated["response"], "declined")
        self.assertEqual(updated["response_label"], "Declined")
        self.assertEqual(updated["response_reason"], "Timing")

        fetched = self.call(
            "get_crm_contact",
            {"tracking_slug": "analytical-engines"},
            token=token,
            path="/mcp/grok",
        )["structuredContent"]
        self.assertEqual(fetched["email"], "ada@example.com")

        deleted = self.call(
            "delete_crm_contact",
            {"contact_id": contact_id},
            token=token,
            path="/mcp/grok",
        )["structuredContent"]
        self.assertTrue(deleted["deleted"])
        self.assertFalse(CrmContact.objects.filter(pk=contact_id).exists())

    def test_grok_mcp_rejects_oauth_token(self):
        from ramble_mcp.models import OAuthAccessToken, OAuthClient, hash_secret

        client = OAuthClient.objects.create(
            client_id="claude-test",
            client_name="Claude",
            redirect_uris=["https://claude.ai/callback"],
        )
        plain = "rmoa_oauth_test_token_value"
        OAuthAccessToken.objects.create(
            token_hash=hash_secret(plain),
            token_prefix=plain[:12],
            client=client,
            user=self.user,
            scope="mcp",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        response = self.rpc("initialize", {}, token=plain, path="/mcp/grok")
        self.assertEqual(response.status_code, 401)
        # Same OAuth token still works on the Claude MCP URL.
        ok = self.rpc("initialize", {}, token=plain)
        self.assertEqual(ok.status_code, 200)

    def test_unauthorized_points_at_resource_metadata(self):
        response = self.client.post(
            "/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        www = response["WWW-Authenticate"]
        self.assertIn("resource_metadata=", www)
        self.assertIn("/.well-known/oauth-protected-resource", www)


@override_settings(PUBLIC_BASE_URL="https://yourramble.com")
class McpOAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("oauth@example.com", "password12")

    def _challenge(self, verifier: str) -> str:
        import base64
        import hashlib

        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def test_discovery_metadata(self):
        resource = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(resource.status_code, 200)
        body = resource.json()
        self.assertEqual(body["resource"], "https://yourramble.com/mcp")
        self.assertEqual(body["authorization_servers"], ["https://yourramble.com"])

        path_meta = self.client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(path_meta.status_code, 200)
        self.assertEqual(path_meta.json()["resource"], "https://yourramble.com/mcp")

        as_meta = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(as_meta.status_code, 200)
        data = as_meta.json()
        self.assertEqual(data["issuer"], "https://yourramble.com")
        self.assertEqual(data["authorization_endpoint"], "https://yourramble.com/oauth/authorize")
        self.assertEqual(data["token_endpoint"], "https://yourramble.com/oauth/token")
        self.assertEqual(data["registration_endpoint"], "https://yourramble.com/oauth/register")
        self.assertIn("S256", data["code_challenge_methods_supported"])

    def test_register_authorize_token_and_mcp_call(self):
        registered = self.client.post(
            "/oauth/register",
            data=json.dumps(
                {
                    "client_name": "Claude",
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(registered.status_code, 201)
        client_id = registered.json()["client_id"]

        verifier = "test-verifier-abcdefghijklmnopqrstuvwxyz0123456789"
        challenge = self._challenge(verifier)
        self.client.force_login(self.user)

        consent = self.client.get(
            "/oauth/authorize",
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "scope": "mcp offline_access",
                "state": "xyz",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "https://yourramble.com/mcp",
            },
        )
        self.assertEqual(consent.status_code, 200)
        self.assertContains(consent, "Connect to Ramble")
        self.assertContains(consent, "Claude")

        approved = self.client.post(
            "/oauth/authorize",
            {
                "decision": "approve",
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "scope": "mcp offline_access",
                "state": "xyz",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "https://yourramble.com/mcp",
            },
        )
        self.assertEqual(approved.status_code, 302)
        location = approved["Location"]
        self.assertIn("https://claude.ai/api/mcp/auth_callback?", location)
        self.assertIn("state=xyz", location)
        self.assertIn("code=", location)
        from urllib.parse import parse_qs, urlsplit

        code = parse_qs(urlsplit(location).query)["code"][0]

        token = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": "https://yourramble.com/mcp",
            },
        )
        self.assertEqual(token.status_code, 200)
        payload = token.json()
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertIn("access_token", payload)
        self.assertIn("refresh_token", payload)

        mcp = self.client.post(
            "/mcp",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "claude", "version": "1"},
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
        )
        self.assertEqual(mcp.status_code, 200)
        self.assertEqual(mcp.json()["result"]["serverInfo"]["name"], "ramble")

        refreshed = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": payload["refresh_token"],
                "client_id": client_id,
            },
        )
        self.assertEqual(refreshed.status_code, 200)
        new_access = refreshed.json()["access_token"]
        self.assertNotEqual(new_access, payload["access_token"])

        # Old refresh token is rotated away.
        stale = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": payload["refresh_token"],
                "client_id": client_id,
            },
        )
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(stale.json()["error"], "invalid_grant")

    def test_loopback_redirect_accepted(self):
        from ramble_mcp.oauth import redirect_uri_allowed

        self.assertTrue(
            redirect_uri_allowed(
                ["http://localhost/callback", "http://127.0.0.1/callback"],
                "http://localhost:3118/callback",
            )
        )
        self.assertTrue(
            redirect_uri_allowed(
                ["http://127.0.0.1/callback"],
                "http://127.0.0.1/callback",
            )
        )
        self.assertFalse(
            redirect_uri_allowed(
                ["https://claude.ai/api/mcp/auth_callback"],
                "https://evil.example/callback",
            )
        )
