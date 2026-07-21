"""KDF-generation version check for encrypted-request endpoints.

The 2026-07-21 production incident: users entered their PIN correctly
but the first /chat message returned 400 "Invalid PIN or corrupted
data" and forced a second PIN entry. Root causes were a TOCTOU race
between the client's PBKDF2 derive and the server's decrypt derive
whenever ANYTHING mutated the vault row's (pin_salt, kdf_iterations)
in between — a concurrent second-tab /rotate-vault-kdf, an aborted-
but-committed rotate, a browser cache serving a stale /vault-meta
response after a rotation had moved the DB salt, etc. The client
would encrypt with K_v (derived from the salt it observed at unlock)
while the server derived K_w (from the current DB salt); AES-GCM
decrypt of ciphertext-K_v with key-K_w fails at
vault_core.decrypt_message and surfaces the generic 400.

This module provides the authoritative compare-and-swap gate:

  * `check_kdf_generation_fresh(vault_id, client_salt, client_iter)`
    reads the current DB row and returns None if the client's
    declared (salt, iter) matches, or an `HTTPException(409,
    {"code": "kdf_generation_stale", ...})` with the current salt +
    iter so the client can re-derive and the user can send again.

  * The comparison is exact — a base64 string comparison for the
    salt and an int comparison for the iterations. Any rotation
    generates a fresh 16-byte salt (`generate_pin_salt` in
    vault_core.py), so the salt IS the version identifier and no
    new column is needed on `vaults`.

  * Backwards-compatible: if the client omits `kdf_salt_used`
    (older builds), this helper returns None and the /chat handler
    falls through to the legacy behavior of deriving with the
    current DB state. Missing-field ≠ mismatch; only PRESENCE +
    MISMATCH triggers the 409.

The response body shape on 409 is documented in this module's
constant so the client and the tests both reference the same source
of truth. Deliberately does NOT include the PIN in the response.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor


logger = logging.getLogger(__name__)


# Response body keys returned inside the 409 detail. Kept as
# constants so the client, the tests, and this handler cannot drift.
KDF_STALE_CODE = "kdf_generation_stale"
KDF_STALE_MESSAGE = (
    "The vault's key generation changed since you last unlocked. "
    "Please re-send your message."
)

# 2026-07-22 modern-client enforcement — CORRECTED 2026-07-22 (2)
# to use an in-body protocol-version field instead of the
# X-App-Release header. A client-controlled header MUST NOT decide
# whether the backend validates required crypto fields — the review
# gate rejected that boundary because a missing/spoofed header
# could re-enable the legacy pass-through that let the exact
# production failure through.
#
# The correct boundary is a request-body field the client declares
# EXPLICITLY:
#
#   crypto_protocol_version >= 2  =>  kdf_salt_used AND
#                                     kdf_iterations_used are
#                                     mandatory. Missing = typed
#                                     400 missing_kdf_generation_fields.
#
#   crypto_protocol_version absent OR 1 => legacy compatibility.
#
# X-App-Release stays as a diagnostic log field but is NEVER used
# to decide enforcement.
MISSING_KDF_FIELDS_CODE = "missing_kdf_generation_fields"
MISSING_KDF_FIELDS_MESSAGE = (
    "This client protocol version requires kdf_salt_used and "
    "kdf_iterations_used with encrypted requests. Reload the app "
    "to pick up the latest frontend."
)

# Minimum protocol version that MUST declare its KDF fields.
CRYPTO_PROTOCOL_VERSION_REQUIRES_KDF = 2


def client_requires_kdf_fields(
    crypto_protocol_version: Optional[int],
) -> bool:
    """Return True iff the client's declared crypto_protocol_version
    is high enough to make the KDF fields mandatory. Missing/None
    or 1 stays on the legacy pass-through so an older client build
    is not broken by a partial rollout; 2 and above triggers the
    typed missing_kdf_generation_fields rejection.

    The version is declared in the REQUEST BODY (not a header) so
    it cannot be silently stripped by an intermediate cache /
    proxy / client-controlled header injection.
    """
    if crypto_protocol_version is None:
        return False
    try:
        v = int(crypto_protocol_version)
    except (TypeError, ValueError):
        return False
    return v >= CRYPTO_PROTOCOL_VERSION_REQUIRES_KDF


def salt_fingerprint(salt_base64: Optional[str]) -> str:
    """First 12 hex chars of SHA-256(decoded_salt). Non-secret —
    salts are already public metadata via /vault-meta. Used only
    for diagnostic log correlation."""
    if not salt_base64:
        return "-"
    try:
        raw = base64.b64decode(salt_base64)
    except Exception:
        return "invalid_b64"
    return hashlib.sha256(raw).hexdigest()[:12]


def key_fingerprint(key_bytes: bytes) -> str:
    """First 12 hex chars of SHA-256(key_bytes). Non-secret —
    a 12-hex prefix of SHA-256(K) is a random 48-bit value and
    reveals no key material. Used only for diagnostic log
    correlation across the client + server logs."""
    if not key_bytes:
        return "-"
    return hashlib.sha256(key_bytes).hexdigest()[:12]


def missing_kdf_fields_error() -> HTTPException:
    """Modern clients that forgot to include the KDF fields get
    a typed 400 (NOT the generic decrypt-failure 400 that the pre-
    2026-07-22 client mis-classified as session-expired)."""
    return HTTPException(
        status_code=400,
        detail={
            "code": MISSING_KDF_FIELDS_CODE,
            "message": MISSING_KDF_FIELDS_MESSAGE,
        },
    )


def check_kdf_generation_fresh(
    conn,
    vault_id: str,
    client_salt: Optional[str],
    client_iterations: Optional[int],
) -> None:
    """Raise HTTPException(409, kdf_generation_stale, current) when
    the client's declared (salt, iterations) do not match the vault
    row's current values.

    A ``None`` (missing) client-side field is treated as "legacy
    client, no version declared" and the check silently passes —
    the caller then derives with the current DB state as before.
    Only a PRESENT + DIFFERENT client value triggers the 409.

    The 409 body is:

        {
          "code": "kdf_generation_stale",
          "message": "<human-readable>",
          "current_pin_salt": "<base64>",
          "current_kdf_iterations": <int>
        }

    Never includes any secret material (PIN, verifier, MVK, wrapped
    key, encrypted item body). The salt is public metadata already
    returned by /vault-meta; the iterations count is likewise a
    plain int.

    Args:
        conn: an open DB connection. Caller owns lifecycle.
        vault_id: the caller's authenticated vault id (from
            principal["vault_id"]). Never trusted from the request
            body.
        client_salt: `req.kdf_salt_used`, may be None.
        client_iterations: `req.kdf_iterations_used`, may be None.

    Raises:
        HTTPException(409, {"code": "kdf_generation_stale", ...})
        when the declared salt or iter does not match current.
    """
    if not client_salt and client_iterations is None:
        return

    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        "SELECT pin_salt, kdf_iterations FROM vaults "
        "WHERE vault_id = %s LIMIT 1",
        (vault_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Vault not found")

    current_salt = row.get("pin_salt")
    current_iter = int(row.get("kdf_iterations") or 0)

    salt_mismatch = (
        client_salt is not None
        and current_salt is not None
        and client_salt != current_salt
    )
    iter_mismatch = (
        client_iterations is not None
        and current_iter > 0
        and client_iterations != current_iter
    )

    if not salt_mismatch and not iter_mismatch:
        return

    logger.warning(
        "[KDF-VERSION] mismatch for vault=%s salt_changed=%s iter_changed=%s",
        (vault_id or "")[:8], salt_mismatch, iter_mismatch,
    )
    raise HTTPException(
        status_code=409,
        detail={
            "code": KDF_STALE_CODE,
            "message": KDF_STALE_MESSAGE,
            "current_pin_salt": current_salt,
            "current_kdf_iterations": current_iter,
        },
    )


__all__ = [
    "KDF_STALE_CODE",
    "KDF_STALE_MESSAGE",
    "check_kdf_generation_fresh",
]
