import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

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

    def rpc(self, method, params=None, token=None, msg_id=1):
        body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            body["params"] = params
        return self.client.post(
            "/mcp",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token if token is not None else self.token}",
        )

    def call(self, name, arguments=None, token=None):
        response = self.rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            token=token,
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

    def test_settings_shows_mcp_and_issues_token(self):
        self.client.force_login(self.user)
        page = self.client.get("/settings/")
        self.assertContains(page, "Ramble MCP")
        self.assertContains(page, "/mcp")
        created = self.client.post("/settings/", {"intent": "mcp_token"})
        self.assertContains(created, "Copy this token now")
        self.assertContains(created, "rmbl_")
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_mcp_token)
