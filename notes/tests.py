import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token

from notes.models import Note

User = get_user_model()


class TranscriptionConfigApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("config@example.com", "password12")
        self.token = Token.objects.create(user=self.user)

    def test_requires_auth(self):
        response = self.client.get("/api/transcription/config/")
        self.assertEqual(response.status_code, 401)

    @override_settings(
        ASSEMBLYAI_API_KEY="assembly-test",
        OPENAI_API_KEY="openai-test",
        ASSEMBLYAI_BATCH_MODEL="universal-3-pro",
        ASSEMBLYAI_STREAMING_MODEL="universal-streaming-english",
        OPENAI_TIDY_MODEL="gpt-4o-mini",
    )
    def test_returns_models_without_keys(self):
        response = self.client.get(
            "/api/transcription/config/",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["assembly"]["configured"])
        self.assertEqual(body["assembly"]["batch_model"], "universal-3-pro")
        self.assertEqual(body["assembly"]["streaming_model"], "universal-streaming-english")
        self.assertIn("terminate_timeout_seconds", body["assembly"])
        self.assertEqual(
            body["assembly"]["prompt"],
            "Single speaker. First-person British English voice note, recorded while walking and thinking aloud.",
        )
        self.assertTrue(body["openai"]["configured"])
        self.assertEqual(body["openai"]["tidy_model"], "gpt-4o-mini")
        prompt = body["openai"]["system_prompt"]
        self.assertIn("Copy the speaker's words exactly.", prompt)
        self.assertIn("complete, legible sentences", prompt)
        self.assertIn("and yeah", prompt)
        dumped = json.dumps(body)
        self.assertNotIn("assembly-test", dumped)
        self.assertNotIn("openai-test", dumped)
        self.assertNotIn("ASSEMBLYAI_API_KEY", dumped)
        self.assertNotIn("OPENAI_API_KEY", dumped)


class TranscriptionStreamTokenApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("stream@example.com", "password12")
        self.token = Token.objects.create(user=self.user)

    def test_requires_auth(self):
        response = self.client.post("/api/transcription/stream-token/")
        self.assertEqual(response.status_code, 401)

    @override_settings(ASSEMBLYAI_API_KEY="")
    def test_missing_assembly_key(self):
        response = self.client.post(
            "/api/transcription/stream-token/",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)

    @override_settings(
        ASSEMBLYAI_API_KEY="assembly-test",
        ASSEMBLYAI_STREAMING_MODEL="universal-streaming-english",
        ASSEMBLYAI_STREAM_TOKEN_TTL_SECONDS=60,
        ASSEMBLYAI_STREAM_MAX_SESSION_SECONDS=360,
        ASSEMBLYAI_STREAMING_SAMPLE_RATE=16000,
        ASSEMBLYAI_STREAM_TERMINATE_TIMEOUT_SECONDS=2,
    )
    @patch("notes.ai_providers.urllib.request.urlopen")
    def test_mints_streaming_token(self, urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"token":"temp-token","expires_in_seconds":60}'
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = False
        urlopen.return_value = mock_response

        response = self.client.post(
            "/api/transcription/stream-token/",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token"], "temp-token")
        self.assertEqual(body["speech_model"], "universal-streaming-english")
        self.assertEqual(body["sample_rate"], 16000)
        self.assertEqual(body["websocket_url"], "wss://streaming.assemblyai.com/v3/ws")
        self.assertEqual(body["terminate_timeout_seconds"], 2.0)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "assembly-test")
        self.assertIn(b'"product": "streaming"', request.data)


class HomePageTests(SimpleTestCase):
    def test_landing_offers_signup_and_app_store(self):
        response = self.client.get(reverse("notes:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Start your 7 day free trial today")
        self.assertNotContains(response, "Download the app")
        self.assertContains(response, "download-on-the-app-store.svg")
        self.assertContains(response, settings.APP_STORE_URL)
        self.assertContains(response, reverse("signup"))


class DevelopApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tom@example.com", "password12")
        self.token = Token.objects.create(user=self.user)

    def post_audio(self, **extra):
        audio = BytesIO(b"fake-audio")
        audio.name = "take.webm"
        data = {"audio": audio, "duration": "12"}
        data.update(extra)
        return self.client.post(
            "/api/notes/develop/",
            data=data,
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

    def test_requires_audio(self):
        response = self.client.post(
            "/api/notes/develop/",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_auth(self):
        audio = BytesIO(b"fake-audio")
        audio.name = "take.webm"
        response = self.client.post("/api/notes/develop/", {"audio": audio, "duration": "3"})
        self.assertEqual(response.status_code, 401)

    @override_settings(ASSEMBLYAI_API_KEY="")
    def test_missing_assembly_key(self):
        response = self.post_audio()
        self.assertEqual(response.status_code, 503)

    @override_settings(ASSEMBLYAI_API_KEY="test-key", OPENAI_API_KEY="")
    @patch("notes.develop._assembly_poll", return_value="Hello from the walk.")
    @patch("notes.develop._assembly_submit", return_value="tr_1")
    @patch("notes.develop._assembly_upload", return_value="https://example.com/audio")
    def test_develops_take(self, _upload, _submit, _poll):
        response = self.post_audio(id="11111111-1111-1111-1111-111111111111")
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id="11111111-1111-1111-1111-111111111111")
        self.assertEqual(note.user, self.user)
        self.assertEqual(note.gpt_tidied_text, "Hello from the walk.")
        self.assertFalse(note.is_processing)
        self.assertFalse(note.processing_failed)
        self.assertEqual(note.chosen_transcription_model, "universal-3-pro")

    @override_settings(ASSEMBLYAI_API_KEY="test-key", OPENAI_API_KEY="")
    @patch("notes.develop._assembly_poll", return_value="")
    @patch("notes.develop._assembly_submit", return_value="tr_1")
    @patch("notes.develop._assembly_upload", return_value="https://example.com/audio")
    def test_empty_transcript_saves_take(self, _upload, _submit, _poll):
        response = self.post_audio(id="22222222-2222-2222-2222-222222222222")
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id="22222222-2222-2222-2222-222222222222")
        self.assertFalse(note.is_processing)
        self.assertFalse(note.processing_failed)
        self.assertEqual(note.preview_line, "Transcription failed")

    @override_settings(ASSEMBLYAI_API_KEY="test-key", OPENAI_API_KEY="openai-test")
    @patch("notes.develop._tidy_transcript")
    @patch(
        "notes.develop._assembly_poll",
        return_value="Just a short take.",
    )
    @patch("notes.develop._assembly_submit", return_value="tr_short")
    @patch("notes.develop._assembly_upload", return_value="https://example.com/audio")
    def test_skips_tidy_for_short_takes(self, _upload, _submit, _poll, tidy):
        response = self.post_audio(
            id="33333333-3333-3333-3333-333333333333",
            duration="4",
        )
        self.assertEqual(response.status_code, 200)
        tidy.assert_not_called()
        note = Note.objects.get(id="33333333-3333-3333-3333-333333333333")
        self.assertEqual(note.gpt_tidied_text, "Just a short take.")

    @override_settings(ASSEMBLYAI_API_KEY="test-key", OPENAI_API_KEY="")
    @patch(
        "notes.develop._assembly_poll",
        return_value=" ".join(["word"] * 40),
    )
    @patch("notes.develop._assembly_submit", return_value="tr_hallucination")
    @patch("notes.develop._assembly_upload", return_value="https://example.com/audio")
    def test_rejects_implausible_transcript(self, _upload, _submit, _poll):
        response = self.post_audio(
            id="44444444-4444-4444-4444-444444444444",
            duration="5",
        )
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id="44444444-4444-4444-4444-444444444444")
        self.assertEqual(note.gpt_tidied_text, "")
        self.assertEqual(note.preview_line, "Transcription failed")

    @override_settings(
        ASSEMBLYAI_API_KEY="test-key",
        OPENAI_API_KEY="",
        TAKE_READY_WEBHOOK_INLINE=True,
    )
    @patch("notes.webhooks.urllib.request.urlopen")
    @patch("notes.develop._assembly_poll", return_value="Hello from the walk.")
    @patch("notes.develop._assembly_submit", return_value="tr_1")
    @patch("notes.develop._assembly_upload", return_value="https://example.com/audio")
    def test_develop_pings_take_ready_webhook(self, _upload, _submit, _poll, urlopen):
        self.user.issue_mcp_token()
        self.user.save_take_ready_webhook(
            "https://api2.cursor.sh/automations/webhook/example",
            "whsec_test_key",
        )
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = False
        urlopen.return_value = mock_response

        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_audio(id="33333333-3333-3333-3333-333333333333")
        self.assertEqual(response.status_code, 200)
        urlopen.assert_called_once()
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "https://api2.cursor.sh/automations/webhook/example")
        self.assertEqual(request.get_header("Authorization"), "Bearer whsec_test_key")
        self.assertIn(b'"event": "take.ready"', request.data)
        self.assertIn(b"33333333-3333-3333-3333-333333333333", request.data)
