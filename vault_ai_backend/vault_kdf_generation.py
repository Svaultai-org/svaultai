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
