

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


# Domain-separated HMAC used to derive ``auth_sessions.token_id_hash``.
# A hash leaked from the DB cannot be reused as a valid wire signature
# because the two HMAC inputs cover different byte strings.
_TOKEN_ID_HASH_DOMAIN = b"session-id/v1"


def _hash_token_id(token_id_bytes: bytes) -> bytes:
    """Return a 32-byte HMAC-SHA256 of ``token_id_bytes`` domain-separated
    from the wire signature. Stored as ``auth_sessions.token_id_hash``.
    """
    return hmac.new(
        _get_secret(),
        token_id_bytes + _TOKEN_ID_HASH_DOMAIN,
        "sha256",
    ).digest()


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


# ============================================================
# Client-label normalizer (Step B.1)
#
# Coarse, server-side derivation of a session-audit label from the
# HTTP User-Agent header. Chosen from a fixed allow-list; never
# trusts arbitrary client-supplied text; length-capped at 64 chars.
#
# Order matters in the probe tuples:
#   * iOS/Android must precede macOS/Linux — iPhone UAs contain
#     "like Mac OS X", Android UAs contain "Linux".
#   * Edge must precede Chrome — Edge UAs contain "Chrome/".
#   * Chrome must precede Safari — Chrome UAs contain "Safari/".
# ============================================================

_CLIENT_LABEL_MAX_LEN = 64
_UA_INSPECTION_LIMIT = 512
_UNKNOWN_CLIENT_LABEL = "Unknown device"

_OS_PROBES = (
    ("iOS",     ("iPhone", "iPad", "iPod")),
    ("Android", ("Android",)),
    ("Windows", ("Windows",)),
    ("macOS",   ("Mac OS X", "Macintosh")),
    ("Linux",   ("Linux",)),
)

_BROWSER_PROBES = (
    ("Edge",    ("Edg/", "Edge/")),
    ("Firefox", ("Firefox/",)),
    ("Chrome",  ("Chrome/", "CriOS/")),
    ("Safari",  ("Safari/",)),
)


def normalize_client_label(user_agent: Optional[str]) -> str:
    """Return a coarse, non-PII device/browser label for auditing.

    Never returns the User-Agent verbatim. Never longer than 64 chars.
    Returns ``"Unknown device"`` for None, non-str, empty, whitespace-only,
    or unrecognized inputs. Callers MUST derive this from
    ``request.headers.get("user-agent")`` at the route boundary; no
    downstream code should invent labels from other sources.
    """
    if not isinstance(user_agent, str) or not user_agent:
        return _UNKNOWN_CLIENT_LABEL
    ua = user_agent[:_UA_INSPECTION_LIMIT].strip()
    if not ua:
        return _UNKNOWN_CLIENT_LABEL

    os_name: Optional[str] = None
    for name, probes in _OS_PROBES:
        if any(p in ua for p in probes):
            os_name = name
            break

    browser: Optional[str] = None
    for name, probes in _BROWSER_PROBES:
        if any(p in ua for p in probes):
            browser = name
            break

    if browser and os_name:
        label = f"{browser} on {os_name}"
    elif browser:
        label = browser
    elif os_name:
        label = os_name
    else:
        return _UNKNOWN_CLIENT_LABEL

    return label[:_CLIENT_LABEL_MAX_LEN]


class IssuedSession(TypedDict):
    token: str
    token_id: str
    expires_at: datetime
    vault_id: str
    vault_name: str
    client_label: str


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
    client_label: str,
    ttl_hours: Optional[int] = None,
) -> IssuedSession:
    """Mint a session token atomically under the single-session policy.

    Contract (Step B.3):
      A Vault may have at most one unrevoked ``auth_sessions`` row.
      Every successful login enforces this by revoking every existing
      unrevoked session for the vault in the SAME transaction that
      inserts the new session. The token is returned to the caller
      ONLY AFTER a successful commit.

    Transaction (single Postgres transaction):
      1. ``SELECT vault_id FROM vaults WHERE vault_id = %s FOR UPDATE``
         — serializes concurrent logins for the same vault.
      2. ``UPDATE auth_sessions SET revoked_at = NOW(),
         revoked_reason='superseded-by-new-login' WHERE vault_id = %s
         AND revoked_at IS NULL RETURNING client_label, issued_at``
         — captures the previous session's coarse label for the
         audit event without ever surfacing token_id / token_id_hash.
      3. ``INSERT INTO auth_sessions (...)`` with the new token_id and
         its 32-byte token_id_hash (see :func:`_hash_token_id`).
      4. ``INSERT INTO vault_security_events`` (type
         ``'new_session_created'``).
      5. If step 2 revoked any prior row, ``INSERT INTO
         vault_security_events`` (type ``'previous_session_revoked'``)
         with the OLD row's client_label (or NULL for pre-migration
         legacy rows without a label).
      6. ``COMMIT``.

    Race semantics: two concurrent logins for the same vault queue on
    the FOR UPDATE lock. The second to commit revokes the first's
    freshly-inserted row and inserts its own. Result: last commit
    wins — matches "phone→laptop displaces phone" scenario.

    Callers MUST supply ``client_label`` via
    :func:`normalize_client_label` applied to
    ``request.headers.get("user-agent")`` at the route boundary. This
    function never trusts client-supplied labels.
    """
    if not vault_id:
        raise ValueError("issue_session_token requires vault_id")
    if not vault_name:
        raise ValueError("issue_session_token requires vault_name")
    if not isinstance(client_label, str) or not client_label:
        raise ValueError("issue_session_token requires client_label")

    token_id_bytes = secrets.token_bytes(_TOKEN_ID_BYTES)
    token_id = str(uuid.UUID(bytes=token_id_bytes))
    token_id_hash = _hash_token_id(token_id_bytes)

    hours = SESSION_TTL_HOURS if ttl_hours is None else int(ttl_hours)
    hours = max(SESSION_TTL_HOURS_MIN, min(SESSION_TTL_HOURS_MAX, hours))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    conn = get_db()
    try:
        # _PooledConnection wraps a psycopg2 connection whose default
        # autocommit is False; the pool's close() rollback keeps that
        # invariant across borrows. No autocommit toggle needed here.
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Serialize per-vault. Blocks any concurrent login for this vault.
        cur.execute(
            "SELECT vault_id FROM vaults WHERE vault_id = %s FOR UPDATE",
            (vault_id,),
        )
        if cur.fetchone() is None:
            raise ValueError("issue_session_token: vault_id not found")

        # 2. Revoke every existing unrevoked session for this vault.
        #    Return the OLD client_label / issued_at so we can name the
        #    displaced session in the audit event (never token_id / hash).
        cur.execute(
            """
            UPDATE auth_sessions
               SET revoked_at     = NOW(),
                   revoked_reason = 'superseded-by-new-login'
             WHERE vault_id       = %s
               AND revoked_at IS NULL
            RETURNING client_label, issued_at
            """,
            (vault_id,),
        )
        revoked_rows = cur.fetchall()
        previous_client_label: Optional[str] = None
        if revoked_rows:
            # Newest revoked first — used for the audit event's label.
            _epoch = datetime.min.replace(tzinfo=timezone.utc)
            newest = max(
                revoked_rows,
                key=lambda r: (r.get("issued_at") or _epoch),
            )
            previous_client_label = newest.get("client_label")

        # 3. Insert the new, single unrevoked session.
        #    client_label_source = 1 encodes "derived from HTTP User-Agent
        #    at issue time" (see :func:`normalize_client_label`).
        cur.execute(
            """
            INSERT INTO auth_sessions (
                token_id, token_id_hash, vault_id, device_id,
                client_label, client_label_source,
                expires_at
            ) VALUES (%s, %s, %s, %s, %s, 1, %s)
            """,
            (
                token_id, token_id_hash, vault_id, device_id,
                client_label, expires_at,
            ),
        )

        # 4. new_session_created event.
        cur.execute(
            """
            INSERT INTO vault_security_events
                (vault_id, event_type, client_label)
            VALUES (%s, 'new_session_created', %s)
            """,
            (vault_id, client_label),
        )

        # 5. previous_session_revoked event (only when step 2 revoked something).
        if revoked_rows:
            cur.execute(
                """
                INSERT INTO vault_security_events
                    (vault_id, event_type, client_label)
                VALUES (%s, 'previous_session_revoked', %s)
                """,
                (vault_id, previous_client_label),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        # Never surface the token — the wire value is not even built yet.
        raise
    finally:
        conn.close()

    # Only after successful commit do we compute & return the wire token.
    return {
        "token":        _format_token(token_id_bytes),
        "token_id":     token_id,
        "expires_at":   expires_at,
        "vault_id":     vault_id,
        "vault_name":   vault_name,
        "client_label": client_label,
    }


def revoke_session_token(token_id: str, *, reason: str = "logout") -> bool:
    """Revoke a single session by ``token_id`` and stamp ``revoked_reason``.

    Default reason is ``'logout'`` because that's the only current
    non-issuance caller. Vault-delete and other bulk paths use
    :func:`revoke_all_sessions_for_vault`.
    """
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE auth_sessions
               SET revoked_at     = NOW(),
                   revoked_reason = %s
             WHERE token_id       = %s
               AND revoked_at IS NULL
            """,
            (reason, token_id),
        )
        affected = cur.rowcount
        conn.commit()
        return bool(affected)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def revoke_all_sessions_for_vault(
    vault_id: str, *, reason: str = "vault-delete",
) -> int:
    """Bulk-revoke every unrevoked session for a vault (vault delete path).

    Since Step B.3 the single-session invariant guarantees at most one
    unrevoked row per vault, so callers normally see ``rowcount <= 1``.
    Retained as a defensive bulk operation for the vault-delete cascade.
    """
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE auth_sessions
               SET revoked_at     = NOW(),
                   revoked_reason = %s
             WHERE vault_id       = %s
               AND revoked_at IS NULL
            """,
            (reason, vault_id),
        )
        affected = cur.rowcount
        conn.commit()

        try:
            from vault_chat_active_entity import clear_active_entity
            clear_active_entity(vault_id)
        except Exception:
            pass
        try:
            from vault_active_context import clear_active_context
            clear_active_context(vault_id)
        except Exception:
            pass

        return int(affected)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# Session-error codes (Step B.3)
# ============================================================
#
# Every 401 produced by verify_session_token carries a
# machine-readable ``code`` in the response body's ``detail`` object.
# Client-side code (frontend Step B.4) will branch on the code to
# render the correct user message and — for ``session_superseded`` —
# wipe local ZK state before routing back to the auth screen.
#
# Wire shape:
#   { "detail": { "code": "<one-of-below>", "message": "<human text>" } }
#
_SESSION_ERROR_MESSAGES = {
    "invalid_session":
        "Session is invalid or missing. Please sign in again.",
    "session_expired":
        "Your session has expired. Please sign in again.",
    "session_revoked":
        "Your session has been revoked. Please sign in again.",
    "session_superseded":
        "Your Vault was signed in on another device. This session has been closed.",
}


def _auth_401(code: str) -> HTTPException:
    """Build an HTTPException with a machine-readable code + human message."""
    message = _SESSION_ERROR_MESSAGES.get(code, _SESSION_ERROR_MESSAGES["invalid_session"])
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": message},
    )


# Bumping ``last_used_at`` on every request creates a hot-write path.
# We only bump if the current value is NULL or older than this many
# seconds. 60 s matches the design doc and gives the frontend enough
# resolution for the "last activity" display.
_LAST_USED_AT_THROTTLE_SECONDS = 60


def _load_principal(
    token_id: str,
    token_id_hash: bytes,
) -> tuple[Optional[SessionPrincipal], Optional[str]]:
    """Look up the session row and classify the outcome.

    Returns ``(principal, None)`` on success or ``(None, code)`` where
    ``code`` is one of the ``_SESSION_ERROR_MESSAGES`` keys.

    Pre-0025 compatibility: legacy rows have ``token_id_hash IS NULL``.
    We look up by ``token_id`` (the primary key, always present) so the
    lookup is O(1) with no scan. When the DB row has a non-NULL hash we
    additionally compare it constant-time against the caller-provided
    hash as belt-and-braces protection against a DB whose ``token_id``
    was leaked without the HMAC secret. The wire signature check in
    :func:`_parse_token` is the primary defense.

    Never logs raw ``token_id`` or ``token_id_hash``.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT s.token_id, s.vault_id, s.device_id, s.expires_at,
                   s.revoked_at, s.revoked_reason, s.token_id_hash,
                   s.last_used_at,
                   v.vault_name
              FROM auth_sessions s
              JOIN vaults v ON v.vault_id = s.vault_id
             WHERE s.token_id = %s
            """,
            (token_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None, "invalid_session"

        row_hash = row["token_id_hash"]
        if row_hash is not None:
            # Constant-time compare; row_hash comes back as memoryview
            # under psycopg2 — coerce to bytes for compare_digest.
            if not hmac.compare_digest(bytes(row_hash), token_id_hash):
                return None, "invalid_session"

        if row["revoked_at"] is not None:
            reason = (row["revoked_reason"] or "").strip()
            if reason == "superseded-by-new-login":
                return None, "session_superseded"
            return None, "session_revoked"

        if row["expires_at"] <= datetime.now(timezone.utc):
            return None, "session_expired"

        # Throttled last_used_at bump — only fires when the current
        # value is NULL or > 60 s stale. Failure is best-effort:
        # authentication has already succeeded.
        try:
            cur.execute(
                """
                UPDATE auth_sessions
                   SET last_used_at = NOW()
                 WHERE token_id = %s
                   AND (last_used_at IS NULL
                        OR last_used_at < NOW() - INTERVAL '%s seconds')
                """,
                (token_id, _LAST_USED_AT_THROTTLE_SECONDS),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            # No token_id or hash in the log message.
            logger.exception("[AUTH] last_used_at bump failed")

        principal: SessionPrincipal = {
            "vault_id":   str(row["vault_id"]),
            "vault_name": row["vault_name"],
            "token_id":   str(row["token_id"]),
            "device_id":  row["device_id"],
        }
        return principal, None
    finally:
        conn.close()


async def verify_session_token(request: Request) -> SessionPrincipal:
    """FastAPI dependency: authenticate a request or raise a coded 401.

    Never logs the raw token, token_id, or token_id_hash. All error
    paths raise a 401 with ``detail={"code": ..., "message": ...}``.
    """
    auth_header = request.headers.get("authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        raise _auth_401("invalid_session")

    token = auth_header.split(" ", 1)[1].strip()
    token_id_bytes = _parse_token(token)
    if token_id_bytes is None:
        raise _auth_401("invalid_session")

    token_id = str(uuid.UUID(bytes=token_id_bytes))
    token_id_hash = _hash_token_id(token_id_bytes)

    principal, error_code = _load_principal(token_id, token_id_hash)
    if principal is None:
        raise _auth_401(error_code or "invalid_session")

    # Best-effort device presence signal; never blocks or logs the token.
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
    "normalize_client_label",
    "revoke_session_token",
    "revoke_all_sessions_for_vault",
    "verify_session_token",
    "reset_secret_for_tests",
]
