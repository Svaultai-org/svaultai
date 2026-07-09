

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple


logger = logging.getLogger(__name__)


_VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    "mp4", "mov", "m4v", "mkv", "avi",
})


_VIDEO_MIME_PREFIX = "video/"


try:
    from vault_config import media as _media_cfg
    _m = _media_cfg()
    MAX_VIDEO_BYTES = _m.max_video_bytes
    _MAX_EXTRACTED_AUDIO_BYTES = _m.max_audio_bytes
    MAX_TRANSCRIPT_CHARS = _m.max_transcript_chars
except Exception:
    MAX_VIDEO_BYTES = 200 * 1024 * 1024
                                                                  
                                                              
    _MAX_EXTRACTED_AUDIO_BYTES = 25 * 1024 * 1024
                                          
    MAX_TRANSCRIPT_CHARS = 500_000


_EXTRACT_TIMEOUT_SECONDS = 600


def _detect_video_backend() -> Tuple[bool, str]:


    if shutil.which("ffmpeg") is None:
        return (False, "ffmpeg-missing")
    try:
        import openai              
    except Exception:
        return (False, "openai-missing")
    return (True, "ffmpeg-openai")


VIDEO_AVAILABLE, VIDEO_BACKEND = _detect_video_backend()


_EXTRACTION_ENGINE = None                            


def set_video_audio_extraction_engine(fn) -> None:


    global _EXTRACTION_ENGINE
    _EXTRACTION_ENGINE = fn


def reset_video_audio_extraction_engine() -> None:


    global _EXTRACTION_ENGINE
    _EXTRACTION_ENGINE = (
        _default_ffmpeg_engine
        if shutil.which("ffmpeg") is not None
        else None
    )


def _default_ffmpeg_engine(video_bytes: bytes) -> bytes:


    if not video_bytes:
        raise VideoTranscriptionError("no video bytes to extract")

    video_fd, video_path = tempfile.mkstemp(suffix=".bin")
    audio_fd, audio_path = tempfile.mkstemp(suffix=".m4a")
    try:
        try:
            with os.fdopen(video_fd, "wb") as vf:
                vf.write(video_bytes)
        finally:
            video_fd = -1
        os.close(audio_fd)
        audio_fd = -1

        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",                                    
                    "-nostdin",                               
                    "-i", video_path,             
                    "-vn",                                      
                    "-ac", "1",                  
                    "-ar", "16000",                          
                    "-c:a", "aac",
                    "-b:a", "64k",
                    audio_path,
                ],
                capture_output=True,
                timeout=_EXTRACT_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VideoTranscriptionError(
                "ffmpeg timed out during audio extraction"
            ) from exc
        except FileNotFoundError as exc:
            raise VideoTranscriptionError(
                "ffmpeg binary not found"
            ) from exc

                                                             
        rc = proc.returncode
        proc = None              

        if rc != 0:
            raise VideoTranscriptionError(
                f"ffmpeg failed to extract audio (rc={rc})"
            )

        with open(audio_path, "rb") as af:
            audio_bytes = af.read()
        if not audio_bytes:
            raise VideoTranscriptionError(
                "ffmpeg produced no audio output"
            )
        if len(audio_bytes) > _MAX_EXTRACTED_AUDIO_BYTES:
            raise VideoTranscriptionError(
                f"extracted audio exceeds {_MAX_EXTRACTED_AUDIO_BYTES} "
                f"byte cap (got {len(audio_bytes)})"
            )
        return audio_bytes
    finally:
        for fd in (video_fd, audio_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except Exception:
                    pass
        for p in (video_path, audio_path):
            try:
                os.unlink(p)
            except Exception:
                pass


if shutil.which("ffmpeg") is not None:
    _EXTRACTION_ENGINE = _default_ffmpeg_engine


class VideoTranscriptionError(Exception):
    pass


def _file_extension(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return None
    return name[dot + 1:]


def supports_video_transcription(
    *, file_name: Optional[str], content_type: Optional[str] = None,
) -> bool:


    mime = (content_type or "").strip().lower()
    if mime.startswith(_VIDEO_MIME_PREFIX):
        return True
    ext = _file_extension(file_name)
    if ext and ext in _VIDEO_EXTENSIONS:
        return True
    return False


def extract_audio_from_video(video_bytes: bytes) -> bytes:


    if not video_bytes:
        raise VideoTranscriptionError("no video bytes to extract")
    engine = _EXTRACTION_ENGINE
    if engine is None:
        raise VideoTranscriptionError(
            "video extraction engine unavailable: install ffmpeg "
            "or inject a test engine via "
            "set_video_audio_extraction_engine"
        )
    try:
        audio = engine(video_bytes)
    except VideoTranscriptionError:
        raise
    except Exception as exc:
        raise VideoTranscriptionError(
            f"video extraction engine error: {exc}"
        ) from exc
    if not audio:
        raise VideoTranscriptionError(
            "extraction engine returned no audio"
        )
    if not isinstance(audio, (bytes, bytearray)):
        raise VideoTranscriptionError(
            "extraction engine returned non-bytes audio"
        )
    return bytes(audio)


def transcribe_video(
    *,
    file_name: str,
    file_bytes: bytes,
    content_type: Optional[str] = None,
    max_chars: int = MAX_TRANSCRIPT_CHARS,
) -> Tuple[str, bool]:


    if not supports_video_transcription(
        file_name=file_name, content_type=content_type,
    ):
        raise VideoTranscriptionError(
            f"video transcription not supported for {file_name!r}"
        )
    if not file_bytes:
        raise VideoTranscriptionError("no video bytes to transcribe")
    if len(file_bytes) > MAX_VIDEO_BYTES:
        raise VideoTranscriptionError(
            f"video file exceeds {MAX_VIDEO_BYTES} byte cap "
            f"(got {len(file_bytes)})"
        )

    audio_bytes = extract_audio_from_video(file_bytes)
    try:
                                                               
                                                               
        import vault_audio_transcription as at
        try:
            text, truncated = at.transcribe_audio(
                file_name="extracted_audio.m4a",
                file_bytes=audio_bytes,
                content_type="audio/mp4",
                max_chars=max_chars,
            )
        except at.AudioTranscriptionError as exc:
            raise VideoTranscriptionError(
                f"audio transcription failed: {exc}"
            ) from exc
    finally:
                                                            
                                                               
        audio_bytes = b""              

    return text, truncated
