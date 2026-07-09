

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time

from fastapi import HTTPException


logger = logging.getLogger(__name__)


CHUNK_TOKEN_TTL_DEFAULT_SECONDS = 3600
CHUNK_TOKEN_TTL_MAX_SECONDS = 86400


def load_ttl_seconds(env_var_name: str) -> int:


    raw = os.getenv(env_var_name, "").strip()
    if not raw:
        return CHUNK_TOKEN_TTL_DEFAULT_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "[CHUNKED-TOKENS] %s=%r is not an integer; using default %d",
            env_var_name, raw, CHUNK_TOKEN_TTL_DEFAULT_SECONDS,
        )
        return CHUNK_TOKEN_TTL_DEFAULT_SECONDS
    if value <= 0:
        logger.warning(
            "[CHUNKED-TOKENS] %s=%d <= 0; using default %d",
            env_var_name, value, CHUNK_TOKEN_TTL_DEFAULT_SECONDS,
        )
        return CHUNK_TOKEN_TTL_DEFAULT_SECONDS
    if value > CHUNK_TOKEN_TTL_MAX_SECONDS:
        logger.warning(
            "[CHUNKED-TOKENS] %s=%d exceeds max %d; clamping",
            env_var_name, value, CHUNK_TOKEN_TTL_MAX_SECONDS,
        )
        return CHUNK_TOKEN_TTL_MAX_SECONDS
    return value


def _load_secret() -> bytes:


    raw = os.getenv("VAULTAI_UPLOAD_TOKEN_SECRET", "")
    if raw:
        return raw.encode("utf-8")

    chunked_on = os.getenv("VAULTAI_CHUNKED_UPLOADS", "false").lower() == "true"
    dev_override = os.getenv(
        "VAULTAI_ALLOW_EPHEMERAL_TOKEN_SECRET", "false"
    ).lower() == "true"

    if chunked_on and not dev_override:
        raise RuntimeError(
            "VAULTAI_UPLOAD_TOKEN_SECRET is required when "
            "VAULTAI_CHUNKED_UPLOADS=true. Set it to a stable random "
            "string in your environment, or set "
            "VAULTAI_ALLOW_EPHEMERAL_TOKEN_SECRET=true to permit an "
            "ephemeral per-process secret (dev only - restarts will "
            "invalidate any in-flight chunked upload/download tokens)."
        )

    logger.warning(
        "[CHUNKED-TOKENS] VAULTAI_UPLOAD_TOKEN_SECRET not set; using "
        "ephemeral per-process secret. Set this in production."
    )
    return os.urandom(32)


CHUNK_TOKEN_SECRET: bytes = _load_secret()


def issue_chunk_token(
    *, kind: str, vault_id: str, file_id: str, ttl_seconds: int
) -> tuple[str, int]:


    if kind not in ("upload", "download"):
        raise ValueError(f"unknown chunk-token kind: {kind!r}")
    if "|" in vault_id or "|" in file_id:
                                                                       
                                                                       
        raise ValueError("vault_id and file_id must not contain '|'")
    exp = int(time.time()) + ttl_seconds
    payload = f"{kind}|{vault_id}|{file_id}|{exp}"
    sig = hmac.new(CHUNK_TOKEN_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(
        f"{payload}|{sig}".encode()
    ).decode().rstrip("=")
    return token, exp


def verify_chunk_token(
    token: str, *, kind: str, vault_id: str, file_id: str
) -> None:


    try:
        pad = "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(token + pad).decode()
        k, v, f, exp_str, sig = decoded.split("|", 4)
        exp = int(exp_str)
    except Exception:
        raise HTTPException(status_code=401, detail=f"Invalid {kind} token")
    if k != kind or v != vault_id or f != file_id:
        raise HTTPException(
            status_code=401, detail=f"{kind.capitalize()} token mismatch"
        )
    if exp < int(time.time()):
        raise HTTPException(
            status_code=401, detail=f"{kind.capitalize()} token expired"
        )
    expected = hmac.new(
        CHUNK_TOKEN_SECRET,
        f"{kind}|{v}|{f}|{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(
            status_code=401,
            detail=f"{kind.capitalize()} token signature invalid",
        )
