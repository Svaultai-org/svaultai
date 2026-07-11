"""Shared Crypto Vault entitlement dependency.

Every user-facing endpoint under ``/crypto/wallet/*`` must gate on the
authoritative billing entitlement in addition to trusted-device
verification. Before this module existed those endpoints only checked
``verify_trusted_device`` + the global feature flag — leaving a bypass
where a non-upgraded but trusted-device caller could still hit the raw
crypto wallet API directly.

Authoritative rule (identical to every other in-app gate — see
``StorageEntitlement`` in ``billing.py``, the ``AppState.isCryptoEntitled``
getter, and the Crypto Vault page's own route guard in ``main.dart``):

    entitlement.block_count > 0
    AND entitlement.purchased_bytes > 0

Any other state — missing account, DB failure, expired, canceled beyond
grace, block_count == 0, purchased_bytes == 0 — results in a fail-closed
403. The response body carries only a stable machine code and a
user-facing message. It never reveals billing internals (period end
date, exact status, block price, purchased byte count).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Depends, HTTPException

from device_gate import verify_trusted_device


logger = logging.getLogger(__name__)


ENTITLEMENT_CODE_UPGRADE_REQUIRED: str = "crypto_vault_upgrade_required"
ENTITLEMENT_MESSAGE_UPGRADE_REQUIRED: str = (
    "Crypto Vault is not included in the current plan. Upgrade to "
    "unlock wallet operations."
)


def _resolve_upgraded_flag(vault_id: Optional[str]) -> bool:
    """Fail-closed: any error path returns False so the caller 403s.

    Uses ``billing.get_account_id_for_vault`` + ``billing.get_entitlement``
    — the same authoritative source of truth the rest of the app reads.
    """
    if not vault_id:
        return False
    try:
        from billing import (
            get_account_id_for_vault, get_entitlement,
        )
        account_id = get_account_id_for_vault(vault_id)
        if not account_id:
            return False
        ent = get_entitlement(account_id)
        return bool(
            getattr(ent, "block_count", 0) > 0
            and getattr(ent, "purchased_bytes", 0) > 0
        )
    except Exception:
        logger.warning(
            "crypto_entitlement resolve failed vault=%s",
            (vault_id or "")[:8] + "...",
            exc_info=True,
        )
        return False


def is_crypto_entitled_for_vault(vault_id: Optional[str]) -> bool:
    """Non-HTTP helper — safe to call from anywhere that already has a
    ``vault_id`` and wants to make a locality decision (e.g. chat card
    fallback deflectors). Returns True only when the authoritative
    billing rule is satisfied. Never raises.
    """
    return _resolve_upgraded_flag(vault_id)


def require_crypto_entitlement(
    principal: dict = Depends(verify_trusted_device),
) -> dict:
    """FastAPI dependency: gate the request on Crypto Vault entitlement.

    Composes with ``verify_trusted_device`` — trusted device is still
    required, entitlement is an ADDITIONAL requirement. Returns the
    same principal so callers can drop this in place of
    ``verify_trusted_device`` without changing the handler body.
    """
    vault_id = None
    try:
        vault_id = principal.get("vault_id") if isinstance(
            principal, dict,
        ) else getattr(principal, "vault_id", None)
    except Exception:
        vault_id = None

    if not _resolve_upgraded_flag(vault_id):
        # Deliberately opaque body: never leak entitlement internals.
        raise HTTPException(
            status_code=403,
            detail={
                "code":    ENTITLEMENT_CODE_UPGRADE_REQUIRED,
                "message": ENTITLEMENT_MESSAGE_UPGRADE_REQUIRED,
            },
        )
    return principal


__all__ = [
    "ENTITLEMENT_CODE_UPGRADE_REQUIRED",
    "ENTITLEMENT_MESSAGE_UPGRADE_REQUIRED",
    "is_crypto_entitled_for_vault",
    "require_crypto_entitlement",
]
