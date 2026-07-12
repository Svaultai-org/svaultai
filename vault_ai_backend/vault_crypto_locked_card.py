

from __future__ import annotations

import json
import logging
from typing import Optional


logger = logging.getLogger(__name__)


TYPE_CRYPTO_VAULT_LOCKED: str = "crypto_vault_locked"


SCHEMA_VERSION: str = "crypto_vault_locked.v1"
COPY_VERSION:   str = "crypto_vault_locked_2026_07_12"


CARD_TITLE:  str = "Crypto Vault"
CARD_STATUS: str = "Upgrade required"
CARD_STATUS_ACTIVE: str = "Active"
CARD_BODY:   str = (
    "Crypto Vault is a real, non-custodial wallet — receive, "
    "send, and view balance on supported networks, with keys "
    "that stay on your device. It's not available on your "
    "current plan. Upgrade your account to unlock it."
)
CARD_BODY_ACTIVE: str = (
    "Crypto Vault is active on your account. Open it to pick "
    "a supported asset, use Receive for the wallet address "
    "and QR code, use Send to enter a recipient and amount, "
    "and view balance and transaction history where "
    "supported. The wallet is non-custodial — you control "
    "the funds."
)


ACTION_LEARN_MORE:           str = "crypto_vault_learn_more"
ACTION_UPGRADE_REQUIRED:     str = "crypto_vault_upgrade_required"
ACTION_OPEN_CRYPTO_VAULT:    str = "crypto_vault_open"

BUTTON_LABEL_LEARN_MORE:        str = "Learn more"
BUTTON_LABEL_UPGRADE_REQUIRED:  str = "Upgrade required"
BUTTON_LABEL_OPEN_CRYPTO_VAULT: str = "Open Crypto Vault"


TIER_FREE:     str = "free"
TIER_BASIC:    str = "basic"
TIER_UPGRADED: str = "upgraded"

ALL_TIERS: frozenset[str] = frozenset({
    TIER_FREE, TIER_BASIC, TIER_UPGRADED,
})


def _safe_tier(tier: Optional[str]) -> str:

    if not isinstance(tier, str):
        return TIER_FREE
    cleaned = tier.strip().lower()
    if cleaned in ALL_TIERS:
        return cleaned
    return TIER_FREE


def build_crypto_locked_envelope(
    *,
    user_tier: Optional[str] = None,
) -> str:


    tier = _safe_tier(user_tier)
    upgraded = (tier == TIER_UPGRADED)

    status = CARD_STATUS_ACTIVE if upgraded else CARD_STATUS
    body = CARD_BODY_ACTIVE if upgraded else CARD_BODY
    if upgraded:
        secondary_button = {
            "id":    ACTION_OPEN_CRYPTO_VAULT,
            "label": BUTTON_LABEL_OPEN_CRYPTO_VAULT,
            "kind":  "open",
        }
    else:
        secondary_button = {
            "id":    ACTION_UPGRADE_REQUIRED,
            "label": BUTTON_LABEL_UPGRADE_REQUIRED,
            "kind":  "upgrade",
        }
    payload = {
        "type":            TYPE_CRYPTO_VAULT_LOCKED,
        "schema_version":  SCHEMA_VERSION,
        "copy_version":    COPY_VERSION,
        "tier":            tier,
        "title":           CARD_TITLE,
        "status":          status,
        "body":            body,
        "buttons": [
            {
                "id":      ACTION_LEARN_MORE,
                "label":   BUTTON_LABEL_LEARN_MORE,

                "kind":    "info",
            },
            secondary_button,
        ],

        # Entitlement gates: on the non-upgraded card, send/receive/open
        # are disabled — the frontend must not render an enabled Open
        # Crypto Vault action. On the upgraded card, send + receive +
        # open are all live because the real wallet routes are gated by
        # require_crypto_entitlement on the backend anyway.
        "locked":         (not upgraded),
        "send_enabled":   upgraded,
        "receive_enabled": upgraded,
        "wallet_generation_enabled": upgraded,
        "trading_enabled":          False,
    }
    logger.info(
        "[CRYPTO-LOCKED-ENV] card tier=%s status=%s schema=%s",
        tier, status, SCHEMA_VERSION,
    )
    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "TYPE_CRYPTO_VAULT_LOCKED",
    "SCHEMA_VERSION",
    "COPY_VERSION",
    "CARD_TITLE",
    "CARD_STATUS",
    "CARD_STATUS_ACTIVE",
    "CARD_BODY",
    "CARD_BODY_ACTIVE",
    "ACTION_LEARN_MORE",
    "ACTION_UPGRADE_REQUIRED",
    "ACTION_OPEN_CRYPTO_VAULT",
    "BUTTON_LABEL_LEARN_MORE",
    "BUTTON_LABEL_UPGRADE_REQUIRED",
    "BUTTON_LABEL_OPEN_CRYPTO_VAULT",
    "TIER_FREE",
    "TIER_BASIC",
    "TIER_UPGRADED",
    "ALL_TIERS",
    "build_crypto_locked_envelope",
]
