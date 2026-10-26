from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from notes.models import Note

User = get_user_model()


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
