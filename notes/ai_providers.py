"""Server-owned AssemblyAI / OpenAI configuration and token minting.

Permanent API keys never leave the server. Clients get model names and
short-lived AssemblyAI streaming tokens only.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger("ramble.ai_providers")

ASSEMBLY_API_BASE = "https://api.assemblyai.com"
ASSEMBLY_TOKEN_URL = "https://token.assemblyai.com/v1/token"
ASSEMBLY_STREAMING_WS = "wss://streaming.assemblyai.com/v3/ws"
ASSEMBLY_PROMPT = (
    "Single speaker. First-person British English voice note, recorded while walking and thinking aloud."
)
GPT_SYSTEM_PROMPT = """
Produce a clean British English transcript of this first-person voice note recorded while walking or thinking aloud. Never include filler words such as um, uh, er, ahh, you know, I mean, kind of, or sort of. Never keep throwaway openers that add nothing, including so, well, right, yeah, and okay. Never include false starts; keep only the finished attempt. Always punctuate naturally. Always start a new paragraph when the topic clearly shifts. Do not reword, summarise, or add titles.
""".strip()


class AIProviderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def assembly_configured() -> bool:
    return bool(getattr(settings, "ASSEMBLYAI_API_KEY", "").strip())


def openai_configured() -> bool:
    return bool(getattr(settings, "OPENAI_API_KEY", "").strip())


def batch_model() -> str:
    return getattr(settings, "ASSEMBLYAI_BATCH_MODEL", "universal-3-pro")


def streaming_model() -> str:
    return getattr(settings, "ASSEMBLYAI_STREAMING_MODEL", "universal-streaming-english")


def tidy_model() -> str:
    return getattr(settings, "OPENAI_TIDY_MODEL", "gpt-4o-mini")


def language_code() -> str:
    return getattr(settings, "ASSEMBLYAI_LANGUAGE_CODE", "en_uk")


def streaming_sample_rate() -> int:
    return int(getattr(settings, "ASSEMBLYAI_STREAMING_SAMPLE_RATE", 16000))


def stream_terminate_timeout_seconds() -> float:
    """Client-side max wait for AssemblyAI Termination after stop."""
    raw = getattr(settings, "ASSEMBLYAI_STREAM_TERMINATE_TIMEOUT_SECONDS", 5)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 5.0
    return max(0.5, min(30.0, value))


def public_ai_config() -> dict:
    """Safe payload for authenticated clients — no API keys."""
    return {
        "assembly": {
            "configured": assembly_configured(),
            "batch_model": batch_model(),
            "streaming_model": streaming_model(),
            "language_code": language_code(),
            "streaming_websocket_url": ASSEMBLY_STREAMING_WS,
            "sample_rate": streaming_sample_rate(),
            "terminate_timeout_seconds": stream_terminate_timeout_seconds(),
            "prompt": ASSEMBLY_PROMPT,
        },
        "openai": {
            "configured": openai_configured(),
            "tidy_model": tidy_model(),
            "system_prompt": GPT_SYSTEM_PROMPT,
        },
    }


def mint_streaming_token(
    *,
    expires_in_seconds: int | None = None,
    max_session_duration_seconds: int | None = None,
) -> dict:
    """Mint a short-lived AssemblyAI streaming token with the server API key."""
    api_key = getattr(settings, "ASSEMBLYAI_API_KEY", "").strip()
    if not api_key:
        raise AIProviderError("Transcription is not configured.", status=503)

    ttl = expires_in_seconds
    if ttl is None:
        ttl = int(getattr(settings, "ASSEMBLYAI_STREAM_TOKEN_TTL_SECONDS", 60))
    ttl = max(1, min(600, int(ttl)))

    max_session = max_session_duration_seconds
    if max_session is None:
        max_session = int(getattr(settings, "ASSEMBLYAI_STREAM_MAX_SESSION_SECONDS", 360))
    max_session = max(60, int(max_session))

    body = json.dumps(
        {
            "product": "streaming",
            "expires_in_seconds": ttl,
            "max_session_duration_seconds": max_session,
            "access": {
                "tts": {"enabled": False},
                "speech_to_speech": {"enabled": False},
                "llm_gateway": {"enabled": False},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ASSEMBLY_TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        log.error("AssemblyAI token mint failed: %s", detail[:400])
        raise AIProviderError(
            f"Could not mint a streaming token ({exc.code}).",
            status=502,
        ) from exc
    except urllib.error.URLError as exc:
        raise AIProviderError(
            "Could not reach the transcription service.",
            status=503,
        ) from exc

    token = str(payload.get("token") or "").strip()
    if not token:
        raise AIProviderError("Invalid streaming token response.", status=502)

    expires = int(payload.get("expires_in_seconds") or ttl)
    return {
        "token": token,
        "expires_in_seconds": expires,
        "max_session_duration_seconds": max_session,
        "speech_model": streaming_model(),
        "websocket_url": ASSEMBLY_STREAMING_WS,
        "sample_rate": streaming_sample_rate(),
        "language_code": language_code(),
        "terminate_timeout_seconds": stream_terminate_timeout_seconds(),
    }
