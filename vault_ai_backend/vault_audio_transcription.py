

from __future__ import annotations

import io
import logging
import os
from typing import Optional, Tuple


logger = logging.getLogger(__name__)


_AUDIO_EXTENSIONS: frozenset[str] = frozenset({
    "mp3", "m4a", "wav", "aac", "ogg", "flac", "webm",
})


_AUDIO_MIME_PREFIXES: tuple[str, ...] = (
    "audio/mpeg",            
    "audio/mp3",
    "audio/mp4",             
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/aac",
    "audio/x-aac",
    "audio/ogg",
    "application/ogg",
    "audio/flac",
    "audio/x-flac",
    "audio/webm",
)


try:
    from vault_config import media as _media_cfg
    _m = _media_cfg()
    MAX_TRANSCRIPT_CHARS = _m.max_transcript_chars
    MAX_AUDIO_BYTES = _m.max_audio_bytes
except Exception:
    MAX_TRANSCRIPT_CHARS = 500_000
                                                                   
                                                                 
    MAX_AUDIO_BYTES = 25 * 1024 * 1024


_TRANSCRIBE_TIMEOUT_SECONDS = 300


def _detect_transcription_backend() -> Tuple[bool, str]:


    try:
        import openai              
    except Exception:
        return (False, "openai-missing")
    return (True, "openai-whisper")


AUDIO_AVAILABLE, AUDIO_BACKEND = _detect_transcription_backend()


_TRANSCRIBE_ENGINE = None                            


def set_audio_transcription_engine(fn) -> None:


    global _TRANSCRIBE_ENGINE
    _TRANSCRIBE_ENGINE = fn


def reset_audio_transcription_engine() -> None:


    global _TRANSCRIBE_ENGINE
    _TRANSCRIBE_ENGINE = _default_engine if AUDIO_AVAILABLE else None


def _default_engine(
    audio_bytes: bytes,
    mime: Optional[str],
    file_name: Optional[str],
) -> str:


    try:
        from openai import OpenAI                
    except Exception as exc:
        raise AudioTranscriptionError(
            f"openai SDK unavailable: {exc}"
        ) from exc
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AudioTranscriptionError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key, timeout=_TRANSCRIBE_TIMEOUT_SECONDS)

                                                                
    safe_name = (file_name or "audio.wav").strip()
    buf = io.BytesIO(audio_bytes)
    buf.name = safe_name                              

    try:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            response_format="text",
        )
    except Exception as exc:
        raise AudioTranscriptionError(
            f"transcription engine error: {exc}"
        ) from exc
    if isinstance(resp, str):
        return resp
                                                             
    return str(getattr(resp, "text", "") or "")


if AUDIO_AVAILABLE:
    _TRANSCRIBE_ENGINE = _default_engine


class AudioTranscriptionError(Exception):
    pass


def _file_extension(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return None
    return name[dot + 1:]


def supports_audio_transcription(
    *, file_name: Optional[str], content_type: Optional[str] = None,
) -> bool:


    ext = _file_extension(file_name)
    if ext and ext in _AUDIO_EXTENSIONS:
        return True
    mime = (content_type or "").strip().lower()
    if any(mime == prefix for prefix in _AUDIO_MIME_PREFIXES):
        return True
    return False


def _truncate(
    text: str, *, cap: int = MAX_TRANSCRIPT_CHARS,
) -> Tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def transcribe_audio(
    *,
    file_name: str,
    file_bytes: bytes,
    content_type: Optional[str] = None,
    max_chars: int = MAX_TRANSCRIPT_CHARS,
) -> Tuple[str, bool]:


    if not supports_audio_transcription(
        file_name=file_name, content_type=content_type,
    ):
        raise AudioTranscriptionError(
            f"audio transcription not supported for {file_name!r}"
        )
    if not file_bytes:
        raise AudioTranscriptionError("no audio bytes to transcribe")
    if len(file_bytes) > MAX_AUDIO_BYTES:
        raise AudioTranscriptionError(
            f"audio file exceeds {MAX_AUDIO_BYTES} byte cap "
            f"(got {len(file_bytes)})"
        )
    engine = _TRANSCRIBE_ENGINE
    if engine is None:
        raise AudioTranscriptionError(
            "transcription engine unavailable: install openai SDK "
            "or inject a test engine via "
            "set_audio_transcription_engine"
        )
    mime = (content_type or "").strip().lower() or None
    try:
        text = engine(file_bytes, mime, file_name)
    except AudioTranscriptionError:
        raise
    except Exception as exc:
        raise AudioTranscriptionError(
            f"transcription engine error: {exc}"
        ) from exc
    if text is None:
        return "", False
    normalised = _normalise_transcript_text(str(text))
    truncated = False
    if max_chars and len(normalised) > max_chars:
        normalised = normalised[:max_chars]
        truncated = True
    return normalised, truncated


def _normalise_transcript_text(raw: str) -> str:


    out_lines: list[str] = []
    for line in raw.replace("\f", "\n").splitlines():
        clean = "".join(
            ch for ch in line
            if (ord(ch) >= 0x20 or ch in ("\t",))
        ).rstrip()
        out_lines.append(clean)
    collapsed: list[str] = []
    last_blank = False
    for line in out_lines:
        if not line.strip():
            if last_blank:
                continue
            collapsed.append("")
            last_blank = True
        else:
            collapsed.append(line)
            last_blank = False
    return "\n".join(collapsed).strip()
