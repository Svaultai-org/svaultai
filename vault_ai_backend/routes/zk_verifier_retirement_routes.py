"""Default-off, owner-proof-gated retirement of an obsolete PIN verifier.

The live verifier is never cleared while a known PIN-derived legacy source is
still present. Existing item/file retire routes require owner exact readback;
this route only observes their completed database state. It cannot inspect
plaintext and does not claim that a client assertion proves it.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.errors import LockNotAvailable
from psycopg2.extras import RealDictCursor

from auth_local import (
    PIN_FREE_BENEFICIARY_OFFER,
    PIN_FREE_FILE_CREATE_OFFER,
    PIN_FREE_FILE_DOWNLOAD_OFFER,
    PIN_FREE_FILE_LIST_OFFER,
    PIN_FREE_FILE_MUTATION_OFFER,
    PIN_FREE_ITEM_READ_OFFER,
    PIN_FREE_PASSWORD_ANALYSIS_OFFER,
    PIN_FREE_PRIVATE_CHAT_OFFER,
    SessionPrincipal,
)
from device_gate import verify_trusted_device
from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from strict_raw_pin_ingress_gate import (
    require_strict_private_client, strict_raw_pin_ingress_enabled,
)
from vault_core import get_db


router = APIRouter()
_REQUIRED_OFFERS = (
    PIN_FREE_ITEM_READ_OFFER | PIN_FREE_FILE_LIST_OFFER |
    PIN_FREE_FILE_DOWNLOAD_OFFER | PIN_FREE_FILE_CREATE_OFFER |
    PIN_FREE_FILE_MUTATION_OFFER | PIN_FREE_PASSWORD_ANALYSIS_OFFER |
    PIN_FREE_BENEFICIARY_OFFER | PIN_FREE_PRIVATE_CHAT_OFFER
)
_SOURCE_TABLES = (
    "vault_items", "uploaded_files", "uploaded_file_chunks",
    "legacy_item_edit_candidates", "legacy_item_edit_history",
    "beneficiary_links", "vault_crypto_migration_journal",
)


class RetirePinVerifierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zk_proof_token: str = Field(min_length=1, max_length=128)
    client_verified_exact_readback: bool


def _require_retirement_rollout(
    request: Request, principal: SessionPrincipal,
) -> None:
    if os.getenv("VAULTAI_ZK_PIN_VERIFIER_RETIRE_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")
    if not strict_raw_pin_ingress_enabled():
        raise HTTPException(status_code=409, detail="strict_pin_free_cutover_required")
    require_strict_private_client(request)
    if (principal.get("auth_method") != "opaque" or
            (int(principal.get("pin_free_read_offers", 0)) & _REQUIRED_OFFERS)
            != _REQUIRED_OFFERS):
        raise HTTPException(status_code=409, detail="private_session_parity_required")


def _source_blockers(cur, vault_id: str) -> list[str]:
    """Read structural state only, never ciphertext or private content."""
    checks = (
        ("legacy_items", """
            SELECT EXISTS(SELECT 1 FROM vault_items
             WHERE vault_id=%s AND encrypted_data IS NOT NULL) AS blocked
        """, (vault_id,)),
        ("incomplete_items", """
            SELECT EXISTS(SELECT 1 FROM vault_items
             WHERE vault_id=%s AND encrypted_data IS NULL AND
               (item_type_ciphertext IS NULL OR service_ciphertext IS NULL
                OR payload_ciphertext IS NULL)) AS blocked
        """, (vault_id,)),
        ("legacy_item_edits", """
            SELECT EXISTS(SELECT 1 FROM legacy_item_edit_candidates
             WHERE vault_id=%s) AS blocked
        """, (vault_id,)),
        ("legacy_item_history", """
            SELECT EXISTS(SELECT 1 FROM legacy_item_edit_history
             WHERE vault_id=%s) AS blocked
        """, (vault_id,)),
        ("legacy_files", """
            SELECT EXISTS(SELECT 1 FROM uploaded_files
             WHERE vault_id=%s AND encrypted_file_data IS NOT NULL) AS blocked
        """, (vault_id,)),
        ("legacy_file_chunks", """
            SELECT EXISTS(SELECT 1 FROM uploaded_file_chunks c
              JOIN uploaded_files f ON f.id=c.file_id
             WHERE f.vault_id=%s) AS blocked
        """, (vault_id,)),
        ("incomplete_files", """
            SELECT EXISTS(SELECT 1 FROM uploaded_files f
             WHERE f.vault_id=%s AND
               (f.upload_status <> 'complete' OR NOT EXISTS(
                  SELECT 1 FROM file_v2_records r
                   WHERE r.file_id=f.id AND r.vault_id=f.vault_id::text
                     AND r.verification_state='client_verified'
                     AND r.lifecycle_state IN
                       ('legacy_migration_retired','client_v2_ready')
               ))) AS blocked
        """, (vault_id,)),
        ("pending_file_v2", """
            SELECT EXISTS(SELECT 1 FROM file_v2_records
             WHERE vault_id=%s AND verification_state <> 'client_verified') AS blocked
        """, (vault_id,)),
        ("pending_wallet_v2", """
            SELECT EXISTS(SELECT 1 FROM wallet_v2_records
             WHERE vault_id=%s AND migration_state <> 'v2_verified') AS blocked
        """, (vault_id,)),
        ("legacy_beneficiary_links", """
            SELECT EXISTS(SELECT 1 FROM beneficiary_links
             WHERE (passer_vault_id=%s OR beneficiary_vault_id=%s)
               AND wrapped_vault_key IS DISTINCT FROM %s) AS blocked
        """, (vault_id, vault_id, ZK_BENEFICIARY_V2_MARKER)),
        ("retained_migration_journal", """
            SELECT EXISTS(SELECT 1 FROM vault_crypto_migration_journal
             WHERE vault_id=%s AND legacy_retained) AS blocked
        """, (vault_id,)),
        ("active_legacy_session", """
            SELECT EXISTS(SELECT 1 FROM auth_sessions
             WHERE vault_id=%s AND auth_method='legacy_pin'
               AND revoked_at IS NULL AND expires_at>NOW()) AS blocked
        """, (vault_id,)),
    )
    blocked = []
    for code, sql, params in checks:
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None or row.get("blocked") is not False:
            blocked.append(code)
    return blocked


def _retire_pin_verifier(
    payload: RetirePinVerifierRequest, principal: SessionPrincipal,
) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Source triggers added in 0060 reject a post-retirement legacy write.
        # Lock these tables before checking so a concurrent old write either
        # commits first and is seen, or waits and sees the retired marker.
        cur.execute(
            "LOCK TABLE " + ", ".join(_SOURCE_TABLES) +
            " IN SHARE ROW EXCLUSIVE MODE NOWAIT"
        )
        cur.execute("""
            SELECT vault_handle, opaque_registration_record, wrapped_mvk,
                   wrapped_sk_vault, pk_vault_public,
                   display_name_ciphertext, pin_verifier,
                   pin_verifier_retired_at
              FROM vaults WHERE vault_id=%s FOR UPDATE
        """, (principal["vault_id"],))
        vault = cur.fetchone()
        if vault is None:
            raise HTTPException(status_code=404, detail="vault_not_found")
        if vault["pin_verifier_retired_at"] is not None:
            conn.commit()
            return {"retired": True, "already_retired": True}
        if any(vault.get(field) is None for field in (
            "vault_handle", "opaque_registration_record", "wrapped_mvk",
            "wrapped_sk_vault", "pk_vault_public", "display_name_ciphertext",
        )):
            raise HTTPException(status_code=409, detail="opaque_vault_not_ready")
        # Authenticate the owner before revealing even structural blocker
        # categories. A later 409 rolls back this one-use proof deletion.
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        blockers = _source_blockers(cur, principal["vault_id"])
        if blockers:
            raise HTTPException(status_code=409, detail={
                "code": "verifier_retirement_not_ready",
                "blockers": blockers,
            })
        cur.execute("""
            UPDATE vaults
               SET pin_verifier='', pin_verifier_retired_at=NOW()
             WHERE vault_id=%s AND pin_verifier_retired_at IS NULL
             RETURNING pin_verifier_retired_at
        """, (principal["vault_id"],))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="retirement_state_changed")
        conn.commit()
        return {"retired": True, "already_retired": False}
    except LockNotAvailable:
        conn.rollback()
        raise HTTPException(status_code=409, detail="verifier_retirement_busy") from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/auth/zk-pin-verifier-retire")
def retire_pin_verifier(
    payload: RetirePinVerifierRequest,
    request: Request,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_retirement_rollout(request, principal)
    if not payload.client_verified_exact_readback:
        raise HTTPException(status_code=400, detail="client_readback_required")
    return _retire_pin_verifier(payload, principal)
