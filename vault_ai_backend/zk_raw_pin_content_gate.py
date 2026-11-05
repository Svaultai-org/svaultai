"""Reject legacy raw-PIN operations for OPAQUE-registered vaults.

This is an explicit, default-off cutover switch. It does not inspect or log
the PIN or request body. Legacy-only vaults keep their existing PIN routes.
"""

from __future__ import annotations

import os

from fastapi import HTTPException


FLAG_NAME = "VAULTAI_ZK_RAW_PIN_CONTENT_DISABLED"


def raw_pin_content_disabled() -> bool:
    return os.getenv(FLAG_NAME, "false").strip().lower() == "true"


def reject_zk_raw_pin_content(
    vault_id: str, *, zk_registered: bool | None = None,
) -> None:
    if not raw_pin_content_disabled():
        return
    if zk_registered is None:
        # Fail closed on database errors: do not treat an unavailable lookup
        # as proof that an account is legacy-only.
        from vault_core import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT vault_handle IS NOT NULL FROM vaults "
                "WHERE vault_id=%s LIMIT 1",
                (vault_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail="vault_not_found")
        zk_registered = bool(row[0])
    if zk_registered:
        raise HTTPException(status_code=409, detail="zk_client_update_required")
