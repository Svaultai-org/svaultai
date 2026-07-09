

from __future__ import annotations

import base64
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict

from fastapi import HTTPException, Request, status
from psycopg2.extras import RealDictCursor

from vault_core import get_db


logger = logging.getLogger(__name__)


SESSION_TTL_HOURS_DEFAULT = 24 * 7
SESSION_TTL_HOURS_MAX = 24 * 30
SESSION_TTL_HOURS_MIN = 1


def _read_ttl_hours() -> int:

    raw = os.getenv("VAULT_SESSION_TTL_HOURS", "").strip()
    if not raw:
        return SESSION_TTL_HOURS_DEFAULT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "[AUTH] VAULT_SESSION_TTL_HOURS=%r is not an integer; using default %d",
            raw, SESSION_TTL_HOURS_DEFAULT,
        )
        return SESSION_TTL_HOURS_DEFAULT
    if value < SESSION_TTL_HOURS_MIN:
        logger.warning(
            "[AUTH] VAULT_SESSION_TTL_HOURS=%d < %d; clamping",
            value, SESSION_TTL_HOURS_MIN,
        )
        return SESSION_TTL_HOURS_MIN
    if value > SESSION_TTL_HOURS_MAX:
        logger.warning(
            "[AUTH] VAULT_SESSION_TTL_HOURS=%d > %d; clamping",
            value, SESSION_TTL_HOURS_MAX,
        )
        return SESSION_TTL_HOURS_MAX
    return value


SESSION_TTL_HOURS = _read_ttl_hours()


def _is_production() -> bool:
    env_tokens = ("prod", "production", "live")
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        if os.getenv(var, "").strip().lower() in env_tokens:
            return True
    return False


_secret_cache: Optional[bytes] = None


def _get_secret() -> bytes:


    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    raw = os.getenv("VAULT_SESSION_SECRET", "").strip()
    if not raw:
        if _is_production():
            raise RuntimeError(
                "VAULT_SESSION_SECRET is required in production. "
                "Set it in the environment before starting the server. "
                "Generate one with: python -c "
                "\"import secrets;print(secrets.token_urlsafe(48))\"",
            )
        raise RuntimeError(
            "VAULT_SESSION_SECRET is required even in dev. "
            "There is no built-in fallback — the previous "
            "do-not-ship default was removed because it was a "
            "soft prod-bypass if the environment was ever "
            "misclassified. "
            "Add it to your .env (see dev-setup.md). Generate one "
            "with: python -c "
            "\"import secrets;print(secrets.token_urlsafe(48))\"",
        )
                                                                 
                                                                       
    if len(raw) < 32:
        raise RuntimeError(
            "VAULT_SESSION_SECRET must be at least 32 characters long. "
            "Generate one with: python -c "
            "\"import secrets;print(secrets.token_urlsafe(48))\"",
        )
    _secret_cache = raw.encode("utf-8")
    return _secret_cache


def reset_secret_for_tests() -> None:

    global _secret_cache
    _secret_cache = None


_TOKEN_ID_BYTES = 16
_HMAC_BYTES = 32                  


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _sign_token_id(token_id_bytes: bytes) -> bytes:
    return hmac.new(_get_secret(), token_id_bytes, "sha256").digest()


def _format_token(token_id_bytes: bytes) -> str:
    sig = _sign_token_id(token_id_bytes)
    return _b64url_encode(token_id_bytes + sig)


def _parse_token(token: str) -> Optional[bytes]:


    if not token or not isinstance(token, str):
        return None
    try:
        raw = _b64url_decode(token.strip())
    except Exception:
        return None
    if len(raw) != _TOKEN_ID_BYTES + _HMAC_BYTES:
        return None
    token_id_bytes = raw[:_TOKEN_ID_BYTES]
    provided_sig = raw[_TOKEN_ID_BYTES:]
    expected_sig = _sign_token_id(token_id_bytes)
    if not hmac.compare_digest(provided_sig, expected_sig):
        return None
    return token_id_bytes


class IssuedSession(TypedDict):
    token: str
    token_id: str
    expires_at: datetime
    vault_id: str
    vault_name: str


class SessionPrincipal(TypedDict):
    vault_id: str
    vault_name: str
    token_id: str
    device_id: Optional[str]


def issue_session_token(
    *,
    vault_id: str,
    vault_name: str,
    device_id: Optional[str] = None,
    ttl_hours: Optional[int] = None,
) -> IssuedSession:


    if not vault_id:
        raise ValueError("issue_session_token requires vault_id")
    if not vault_name:
        raise ValueError("issue_session_token requires vault_name")

    token_id_bytes = secrets.token_bytes(_TOKEN_ID_BYTES)
    token_id = str(uuid.UUID(bytes=token_id_bytes))

    hours = SESSION_TTL_HOURS if ttl_hours is None else int(ttl_hours)
    hours = max(SESSION_TTL_HOURS_MIN, min(SESSION_TTL_HOURS_MAX, hours))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO auth_sessions (token_id, vault_id, device_id, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (token_id, vault_id, device_id, expires_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "token":      _format_token(token_id_bytes),
        "token_id":   token_id,
        "expires_at": expires_at,
        "vault_id":   vault_id,
        "vault_name": vault_name,
    }


def revoke_session_token(token_id: str) -> bool:

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = NOW()
            WHERE token_id = %s AND revoked_at IS NULL
            """,
            (token_id,),
        )
        affected = cur.rowcount
        conn.commit()
        return bool(affected)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def revoke_all_sessions_for_vault(vault_id: str) -> int:

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = NOW()
            WHERE vault_id = %s AND revoked_at IS NULL
            """,
            (vault_id,),
        )
        affected = cur.rowcount
        conn.commit()
        return int(affected)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_principal(token_id: str) -> Optional[SessionPrincipal]:


    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT s.token_id, s.vault_id, s.device_id, s.expires_at, s.revoked_at,
                   v.vault_name
            FROM auth_sessions s
            JOIN vaults v ON v.vault_id = s.vault_id
            WHERE s.token_id = %s
            """,
            (token_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["revoked_at"] is not None:
            return None
        if row["expires_at"] <= datetime.now(timezone.utc):
            return None

                                                                    
        try:
            cur.execute(
                "UPDATE auth_sessions SET last_used_at = NOW() WHERE token_id = %s",
                (token_id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
                                                              
            logger.exception("[AUTH] failed to bump last_used_at for token_id=%s", token_id)

        return {
            "vault_id":   str(row["vault_id"]),
            "vault_name": row["vault_name"],
            "token_id":   str(row["token_id"]),
            "device_id":  row["device_id"],
        }
    finally:
        conn.close()


async def verify_session_token(request: Request) -> SessionPrincipal:


    auth_header = request.headers.get("authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )
    token = auth_header.split(" ", 1)[1].strip()
    token_id_bytes = _parse_token(token)
    if token_id_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    token_id = str(uuid.UUID(bytes=token_id_bytes))
    principal = _load_principal(token_id)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

                                                                     
    try:
        from device_monitor import monitor_best_effort
        monitor_best_effort(request, principal["vault_id"])
    except Exception:
        logger.exception("[AUTH] device monitor swallowed exception")

    return principal


__all__ = [
    "IssuedSession",
    "SessionPrincipal",
    "SESSION_TTL_HOURS",
    "issue_session_token",
    "revoke_session_token",
    "revoke_all_sessions_for_vault",
    "verify_session_token",
    "reset_secret_for_tests",
]
