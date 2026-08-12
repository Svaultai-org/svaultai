"""Authoritative billing-state gates for vault content access.

The checks in this module operate only on subscription metadata.  They never
load ciphertext (and therefore cannot decrypt or inspect vault content).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException


DELINQUENT_STATUSES = frozenset({
    "delinquent", "past_due", "unpaid", "payment_failed", "incomplete_expired",
})
DELINQUENT_QUOTA_BYTES = 1_073_741_824
LARGE_FILE_THRESHOLD_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class VaultEntitlementState:
    status: str
    delinquent: bool
    effective_quota_bytes: int
    plan_quota_bytes: int


def resolve_vault_entitlement(vault_id: Optional[str]) -> VaultEntitlementState:
    if not vault_id:
        raise HTTPException(status_code=401, detail="vault_session_required")
    try:
        from billing import get_account_id_for_vault, get_entitlement
        account_id = get_account_id_for_vault(str(vault_id))
        if not account_id:
            return VaultEntitlementState("none", False, DELINQUENT_QUOTA_BYTES,
                                         DELINQUENT_QUOTA_BYTES)
        ent = get_entitlement(account_id)
        status = str(getattr(ent, "status", "none") or "none").lower()
        plan_quota = int(getattr(ent, "effective_limit_bytes", 0) or 0)
        delinquent = status in DELINQUENT_STATUSES
        return VaultEntitlementState(
            status=status,
            delinquent=delinquent,
            effective_quota_bytes=(DELINQUENT_QUOTA_BYTES if delinquent else plan_quota),
            plan_quota_bytes=plan_quota,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={
            "code": "entitlement_temporarily_unavailable",
            "message": "Subscription status could not be verified. Try again.",
        }) from exc


def require_content_write(principal):
    state = resolve_vault_entitlement(principal.get("vault_id"))
    if state.delinquent:
        raise HTTPException(status_code=402, detail={
            "code": "subscription_delinquent_write_blocked",
            "category": "billing_entitlement",
            "message": "Saving is paused until your plan is reactivated. Your existing data is preserved.",
        })
    return principal


def require_crypto_access(principal):
    state = resolve_vault_entitlement(principal.get("vault_id"))
    if state.delinquent:
        raise HTTPException(status_code=403, detail={
            "code": "subscription_delinquent_crypto_blocked",
            "category": "billing_entitlement",
            "message": "Reactivate your plan to open Crypto Vault. Wallet data remains preserved.",
        })
    return principal


def require_file_read(principal, total_bytes: int):
    state = resolve_vault_entitlement(principal.get("vault_id"))
    if state.delinquent and int(total_bytes) > LARGE_FILE_THRESHOLD_BYTES:
        raise HTTPException(status_code=403, detail={
            "code": "subscription_delinquent_large_file_blocked",
            "category": "billing_entitlement",
            "large_file_threshold_bytes": LARGE_FILE_THRESHOLD_BYTES,
            "message": "Reactivate your plan to open or download this large file. The file is preserved.",
        })
    return principal
