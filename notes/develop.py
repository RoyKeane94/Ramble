import json
import logging
import time
import urllib.error
import urllib.request
from uuid import UUID, uuid4

from django.conf import settings

from core.logging import log_model_usage
from notes.models import Note
from notes.usage import usage_for_user

log = logging.getLogger("ramble.develop")

ASSEMBLY_MODEL = "universal-3-pro"
ASSEMBLY_BASE = "https://api.assemblyai.com"
ASSEMBLY_PROMPT = (
    "Single speaker. First-person British English voice note, recorded while walking and thinking aloud."
)
GPT_MODEL = "gpt-4o-mini"
GPT_SYSTEM_PROMPT = """
Produce a clean British English transcript of this first-person voice note recorded while walking or thinking aloud. Never include filler words such as um, uh, er, ahh, you know, I mean, kind of, or sort of. Never keep throwaway openers that add nothing, including so, well, right, yeah, and okay. Never include false starts; keep only the finished attempt. Always punctuate naturally. Always start a new paragraph when the topic clearly shifts. Do not reword, summarise, or add titles.
""".strip()

MAX_AUDIO_BYTES = 40 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/mp3",
    "audio/aac",
    "audio/x-m4a",
    "video/webm",
    "application/octet-stream",
}


class DevelopError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def develop_note(*, request, audio_bytes, content_type, duration, note_id=None, created_at=None):
    if not settings.ASSEMBLYAI_API_KEY:
        raise DevelopError("Transcription is not configured.", status=503)

    if not audio_bytes:
        raise DevelopError("Audio is required.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise DevelopError("That recording is too large to upload.")

    usage = usage_for_user(request.user)
    if usage["is_exhausted"]:
        raise DevelopError(usage["remaining_copy"], status=402)

    remaining_seconds = max(0.0, usage["remaining_minutes"] * 60)
    duration = max(0.0, float(duration or 0))
    if remaining_seconds < 1:
        raise DevelopError(usage["remaining_copy"], status=402)
    if duration > remaining_seconds + 1:
        duration = remaining_seconds

    note = _prepare_note(
        user=request.user,
        note_id=note_id,
        duration=duration,
        created_at=created_at,
    )

    started = time.monotonic()
    transcript_id = ""
    success = False
    try:
        _mark_stage(note, "transcribing", 0.16)
        remote_url = _assembly_upload(audio_bytes, content_type)
        _mark_stage(note, "transcribing", 0.22)
        transcript_id = _assembly_submit(remote_url)
        raw = _assembly_poll(transcript_id)
        _mark_stage(note, "tidying", 0.86)
        tidied = _tidy_transcript(raw) or raw
        success = True
        _complete_note(note, raw=raw, tidied=tidied)
        return note
    except DevelopError as exc:
        _fail_note(note, str(exc))
        raise
    except Exception as exc:
        message = str(exc) or "Transcription failed."
        _fail_note(note, message)
        raise DevelopError(message, status=502) from exc
    finally:
        log_model_usage(
            request=request,
            operation="assembly_cloud",
            model=ASSEMBLY_MODEL,
            success=success,
            frame_id=note.id,
            audio_seconds=duration,
            latency_ms=int((time.monotonic() - started) * 1000),
            app_version="web",
            metadata={"transcript_id": transcript_id, "source": "web"},
        )


def _prepare_note(user, note_id, duration, created_at):
    pk = _parse_uuid(note_id) or uuid4()
    note = Note.objects.filter(user=user, id=pk).first()
    if note is None:
        note = Note(id=pk, user=user)
        if created_at is not None:
            note.created_at = created_at
    note.duration = duration
    note.is_processing = True
    note.processing_failed = False
    note.processing_error = ""
    note.processing_stage = "preparing"
    note.save()
    return note


def _parse_uuid(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _mark_stage(note, stage, _progress=None):
    note.processing_stage = stage
    note.is_processing = True
    note.save(update_fields=["processing_stage", "is_processing", "updated_at"])


def _complete_note(note, raw, tidied):
    raw = _normalize_transcript(raw)
    tidied = _normalize_transcript(tidied) or raw
    note.raw_transcript = raw
    note.original_transcript = raw
    note.gpt_transcript = raw
    note.gpt_transcribe_transcript = raw
    note.tidied_text = tidied
    note.gpt_tidied_text = tidied
    note.gpt_transcribe_tidied_text = tidied
    note.did_gpt_tidy = True
    note.did_gpt_transcribe_tidy = True
    note.chosen_transcription_model = ASSEMBLY_MODEL
    note.is_processing = False
    note.processing_failed = False
    note.processing_error = ""
    note.processing_stage = "finishing"
    note.save()


def _fail_note(note, message):
    note.is_processing = False
    note.processing_failed = True
    note.processing_error = (message or "Transcription failed.")[:500]
    note.processing_stage = ""
    note.save(
        update_fields=[
            "is_processing",
            "processing_failed",
            "processing_error",
            "processing_stage",
            "updated_at",
        ]
    )


def _normalize_transcript(text):
    collapsed = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [line.strip() for line in collapsed.split("\n") if line.strip()]
    return "\n\n".join(paragraphs)


def _assembly_headers():
    return {"authorization": settings.ASSEMBLYAI_API_KEY}


def _http_json(method, url, *, headers=None, data=None, timeout=60):
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            if not body:
                return {}
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        log.error("HTTP %s %s failed: %s", method, url, detail[:400])
        raise DevelopError(f"Transcription request failed ({exc.code}).", status=502) from exc
    except urllib.error.URLError as exc:
        raise DevelopError("Could not reach the transcription service.", status=503) from exc


def _assembly_upload(audio_bytes, content_type):
    mime = (content_type or "application/octet-stream").split(";")[0].strip()
    if mime not in ALLOWED_AUDIO_TYPES:
        mime = "application/octet-stream"
    payload = _http_json(
        "POST",
        f"{ASSEMBLY_BASE}/v2/upload",
        headers={**_assembly_headers(), "Content-Type": mime},
        data=audio_bytes,
        timeout=120,
    )
    url = str(payload.get("upload_url") or "").strip()
    if not url:
        raise DevelopError("Invalid transcription response.", status=502)
    return url


def _assembly_submit(audio_url):
    body = json.dumps(
        {
            "audio_url": audio_url,
            "speech_models": [ASSEMBLY_MODEL],
            "language_code": "en_uk",
            "prompt": ASSEMBLY_PROMPT,
        }
    ).encode("utf-8")
    payload = _http_json(
        "POST",
        f"{ASSEMBLY_BASE}/v2/transcript",
        headers={**_assembly_headers(), "Content-Type": "application/json"},
        data=body,
        timeout=60,
    )
    transcript_id = str(payload.get("id") or "").strip()
    if not transcript_id:
        raise DevelopError("Invalid transcription response.", status=502)
    return transcript_id


def _assembly_poll(transcript_id):
    url = f"{ASSEMBLY_BASE}/v2/transcript/{transcript_id}"
    for _ in range(90):
        payload = _http_json("GET", url, headers=_assembly_headers(), timeout=30)
        status = str(payload.get("status") or "")
        if status == "completed":
            text = _normalize_transcript(payload.get("text") or "")
            if not text:
                log.info(
                    "AssemblyAI completed with no speech transcript_id=%s duration=%s confidence=%s",
                    transcript_id,
                    payload.get("audio_duration"),
                    payload.get("confidence"),
                )
            return text
        if status == "error":
            message = str(payload.get("error") or "Transcription failed.").strip()
            raise DevelopError(message, status=502)
        time.sleep(2)
    raise DevelopError("Transcription timed out.", status=504)


def _tidy_transcript(raw):
    key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not key:
        return raw
    trimmed = (raw or "").strip()
    if not trimmed:
        return raw
    body = json.dumps(
        {
            "model": GPT_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": GPT_SYSTEM_PROMPT},
                {"role": "user", "content": trimmed},
            ],
        }
    ).encode("utf-8")
    try:
        payload = _http_json(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            data=body,
            timeout=120,
        )
    except DevelopError:
        log.exception("GPT tidy failed; using AssemblyAI transcript")
        return raw
    choices = payload.get("choices") or []
    if not choices:
        return raw
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    return content or raw
