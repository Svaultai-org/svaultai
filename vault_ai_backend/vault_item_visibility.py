"""Central classification of internal vs. user-visible vault_items.

Some rows in the `vault_items` table are internal Crypto Vault
system records that the wallet engine writes to persist wallet
metadata. Those rows have `item_type = 'crypto_wallet_account'` and
must never surface in:

  * Logins & Secure Items list / search
  * Cross-vault search
  * Vault overview counts (as if they were user-saved items)
  * Ask-VaultAI buttons or chat card projections

They are kept in the same table for schema simplicity but are
filtered out at every read site through this module. User-created
crypto notes stored with normal item types (login, card,
crypto_wallet_address, crypto_note, …) are NOT system records and
stay visible.

The helpers here are used by:
  * routes/login_routes.py     — /list-secure-items
  * main.py                    — list_secrets_tool, retrieve_secret_tool
  * vault_chat_card_data.py    — build_activity_data
"""

from __future__ import annotations

from typing import Any, Iterable


SYSTEM_ITEM_TYPES: frozenset[str] = frozenset({
    "crypto_wallet_account",
})


def is_system_item_type(item_type: Any) -> bool:
    if not isinstance(item_type, str):
        return False
    return item_type in SYSTEM_ITEM_TYPES


def filter_out_system_rows(
    rows: Iterable[dict[str, Any]],
    *, item_type_key: str = "item_type",
) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if not is_system_item_type(r.get(item_type_key))
    ]


SYSTEM_ITEM_TYPE_SQL_EXCLUSION: str = (
    "AND item_type NOT IN ('crypto_wallet_account')"
)


SYSTEM_ITEM_TYPE_SQL_TUPLE: tuple[str, ...] = tuple(
    sorted(SYSTEM_ITEM_TYPES)
)
