"""Regression tests for the crypto-wallet-record leak fix.

Bug: internal Crypto Vault wallet records (item_type =
'crypto_wallet_account', service = 'ETH:ethereum_mainnet' etc.)
were appearing in the user-facing Logins & Secure Items page and
falling through to file-search in chat.

This suite verifies:

  Part A + E  — user-facing list / search / count endpoints exclude
                internal wallet records
  Part D      — chat classifier routes internal service keys and
                "show my <asset> wallet" to Crypto Vault instead of
                file search
  Part G item 11 — the visibility layer never lets encrypted wallet
                secret material into secure-item payloads
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).parent


def _read(rel: str) -> str:
    return (_BACKEND_ROOT / rel).read_text(encoding="utf-8")


def _slice_route(src: str, path: str) -> str:
    anchor = f'@router.post("{path}")'
    start = src.index(anchor)
    tail = src[start + 1:]
    if "@router." in tail:
        end = start + 1 + tail.index("@router.")
    else:
        end = len(src)
    return src[start:end]


class TestVisibilityModuleContract(unittest.TestCase):
    """The central classification module has the shape every other
    call-site depends on."""

    def test_system_item_types_includes_crypto_wallet_account(self):
        from vault_item_visibility import SYSTEM_ITEM_TYPES
        self.assertIn("crypto_wallet_account", SYSTEM_ITEM_TYPES)

    def test_is_system_item_type_true_for_crypto_wallet_account(self):
        from vault_item_visibility import is_system_item_type
        self.assertTrue(is_system_item_type("crypto_wallet_account"))

    def test_is_system_item_type_false_for_user_types(self):
        from vault_item_visibility import is_system_item_type
        for t in ("login", "card", "id", "credential",
                  "crypto_wallet_address", "crypto_note"):
            with self.subTest(item_type=t):
                self.assertFalse(is_system_item_type(t))

    def test_is_system_item_type_false_for_non_string(self):
        from vault_item_visibility import is_system_item_type
        for v in (None, 42, [], {}):
            with self.subTest(v=v):
                self.assertFalse(is_system_item_type(v))

    def test_sql_tuple_matches_system_item_types(self):
        from vault_item_visibility import (
            SYSTEM_ITEM_TYPE_SQL_TUPLE, SYSTEM_ITEM_TYPES,
        )
        self.assertEqual(
            set(SYSTEM_ITEM_TYPE_SQL_TUPLE),
            set(SYSTEM_ITEM_TYPES),
        )

    def test_filter_out_system_rows_drops_wallet_rows(self):
        from vault_item_visibility import filter_out_system_rows
        rows = [
            {"item_type": "login", "service": "Gmail"},
            {"item_type": "crypto_wallet_account",
             "service": "ETH:ethereum_mainnet"},
            {"item_type": "card", "service": "MyBank"},
            {"item_type": "crypto_wallet_account",
             "service": "XMR:monero_mainnet"},
        ]
        result = filter_out_system_rows(rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["service"], "Gmail")
        self.assertEqual(result[1]["service"], "MyBank")


class TestListSecureItemsRouteFilters(unittest.TestCase):
    """Both /list-secure-items handlers must exclude system item
    types via SQL. There are two handlers because the historic
    codebase mounted the same path from two routers; both must be
    tightened to close every mount point."""

    def test_login_routes_list_secure_items_excludes_system(self):
        src = _read("routes/login_routes.py")
        body = _slice_route(src, "/list-secure-items")
        self.assertIn("SYSTEM_ITEM_TYPE_SQL_TUPLE", body)
        self.assertRegex(body, r"item_type\s+NOT\s+IN")

    def test_vault_manage_routes_list_secure_items_excludes_system(self):
        src = _read("routes/vault_manage_routes.py")
        body = _slice_route(src, "/list-secure-items")
        self.assertIn("SYSTEM_ITEM_TYPE_SQL_TUPLE", body)
        self.assertRegex(body, r"item_type\s+NOT\s+IN")

    def test_no_new_route_leaks_all_item_types(self):
        for rel in (
            "routes/login_routes.py",
            "routes/vault_manage_routes.py",
        ):
            src = _read(rel)
            body = _slice_route(src, "/list-secure-items")
            self.assertNotIn(
                "encrypted_data", body,
                msg=(
                    f"{rel} /list-secure-items handler must never "
                    "return encrypted_data"
                ),
            )


class TestLegacyToolsFilterSystemRecords(unittest.TestCase):
    """list_secrets_tool and retrieve_secret_tool are legacy Ask-VaultAI
    endpoints — they must never enumerate or return the crypto
    wallet system record even if the LLM asks for it by its exact
    service name."""

    def _read_main(self) -> str:
        return _read("main.py")

    def test_list_secrets_tool_excludes_system(self):
        src = self._read_main()
        anchor = "def list_secrets_tool("
        start = src.index(anchor)

        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        self.assertIn("SYSTEM_ITEM_TYPE_SQL_TUPLE", body)
        self.assertRegex(body, r"item_type\s+NOT\s+IN")

    def test_retrieve_secret_tool_excludes_system(self):
        src = self._read_main()
        anchor = "def retrieve_secret_tool("
        start = src.index(anchor)
        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        self.assertIn("SYSTEM_ITEM_TYPE_SQL_TUPLE", body)
        self.assertRegex(body, r"item_type\s+NOT\s+IN")


class TestActivityAndCountsExcludeSystem(unittest.TestCase):
    """Vault overview counts and the recent-activity feed must not
    include internal crypto wallet system rows."""

    def test_build_activity_data_filters_system(self):
        src = _read("vault_chat_card_data.py")
        anchor = "def build_activity_data("
        start = src.index(anchor)
        end = src.index("\n\ndef ", start + 1)
        body = src[start:end]
        self.assertIn("SYSTEM_ITEM_TYPE_SQL_TUPLE", body)

    def test_count_vault_items_filters_system(self):
        src = _read("vault_chat_card_data.py")
        anchor = "def _count_vault_items("
        start = src.index(anchor)
        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        self.assertIn("SYSTEM_ITEM_TYPE_SQL_TUPLE", body)
        self.assertRegex(body, r"item_type\s+NOT\s+IN")


class TestCryptoClassifierInternalServiceKeys(unittest.TestCase):
    """`<ASSET>:<network>` internal patterns route to Crypto Vault."""

    def test_eth_ethereum_mainnet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_BALANCE, ASSET_ETH,
        )
        r = classify_crypto_vault_intent("ETH:ethereum_mainnet")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_ETH)

    def test_xmr_monero_mainnet_scanner_status(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent,
            INTENT_SCANNER_STATUS, ASSET_XMR,
        )
        r = classify_crypto_vault_intent("XMR:monero_mainnet")
        self.assertEqual(r.intent, INTENT_SCANNER_STATUS)
        self.assertEqual(r.params["asset"], ASSET_XMR)

    def test_usdt_trc20_tron_mainnet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent,
            INTENT_BALANCE, ASSET_USDT_TRC20,
        )
        r = classify_crypto_vault_intent("USDT_TRC20:tron_mainnet")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_USDT_TRC20)

    def test_sol_solana_mainnet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_BALANCE, ASSET_SOL,
        )
        r = classify_crypto_vault_intent("SOL:solana_mainnet")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_SOL)

    def test_usdt_erc20_ethereum_mainnet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent,
            INTENT_BALANCE, ASSET_USDT_ERC20,
        )
        r = classify_crypto_vault_intent(
            "USDT_ERC20:ethereum_mainnet",
        )
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_USDT_ERC20)

    def test_natural_language_wrapper_still_routes(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_BALANCE, ASSET_ETH,
        )
        r = classify_crypto_vault_intent(
            "show me ETH:ethereum_mainnet",
        )
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_ETH)


class TestCryptoClassifierShowAssetWallet(unittest.TestCase):
    """'show my ETH wallet' patterns route to Crypto Vault."""

    def test_show_my_eth_wallet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_BALANCE, ASSET_ETH,
        )
        r = classify_crypto_vault_intent("show my ETH wallet")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_ETH)

    def test_show_my_ethereum_wallet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_BALANCE, ASSET_ETH,
        )
        r = classify_crypto_vault_intent("show my Ethereum wallet")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_ETH)

    def test_show_my_monero_wallet_scanner_status(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent,
            INTENT_SCANNER_STATUS, ASSET_XMR,
        )
        r = classify_crypto_vault_intent("show my Monero wallet")
        self.assertEqual(r.intent, INTENT_SCANNER_STATUS)
        self.assertEqual(r.params["asset"], ASSET_XMR)

    def test_show_usdt_trc20(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent,
            INTENT_BALANCE, ASSET_USDT_TRC20,
        )
        r = classify_crypto_vault_intent("show USDT TRC20")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_USDT_TRC20)

    def test_show_sol_wallet(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_BALANCE, ASSET_SOL,
        )
        r = classify_crypto_vault_intent("show SOL wallet")
        self.assertEqual(r.intent, INTENT_BALANCE)
        self.assertEqual(r.params["asset"], ASSET_SOL)

    def test_bare_show_usdt_wallet_is_ambiguous(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent,
            INTENT_CLARIFY_USDT_NETWORK,
        )
        r = classify_crypto_vault_intent("show my USDT wallet")
        self.assertEqual(r.intent, INTENT_CLARIFY_USDT_NETWORK)


class TestUmbrellaRouterDelegatesInternalKeys(unittest.TestCase):
    """The full-vault umbrella router must recognise
    <ASSET>:<network> as crypto so it hands off instead of falling
    through to file search."""

    def test_looks_like_crypto_message_catches_usdt_trc20(self):
        from vault_chat_router import _looks_like_crypto_message
        self.assertTrue(
            _looks_like_crypto_message("USDT_TRC20:tron_mainnet"),
        )

    def test_looks_like_crypto_message_catches_eth_mainnet(self):
        from vault_chat_router import _looks_like_crypto_message
        self.assertTrue(
            _looks_like_crypto_message("ETH:ethereum_mainnet"),
        )

    def test_looks_like_crypto_message_catches_sol_mainnet(self):
        from vault_chat_router import _looks_like_crypto_message
        self.assertTrue(
            _looks_like_crypto_message("SOL:solana_mainnet"),
        )

    def test_looks_like_crypto_message_catches_xmr_mainnet(self):
        from vault_chat_router import _looks_like_crypto_message
        self.assertTrue(
            _looks_like_crypto_message("XMR:monero_mainnet"),
        )

    def test_router_delegates_for_eth_service_key(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_CRYPTO_DELEGATED,
        )
        result = classify_and_build_vault_intent(
            "show me ETH:ethereum_mainnet",
        )
        self.assertEqual(
            result["intent"], INTENT_CRYPTO_DELEGATED,
            msg=(
                "The umbrella router MUST delegate an internal "
                "wallet service key to Crypto Vault, not fall "
                "through to file search"
            ),
        )

    def test_router_delegates_for_usdt_trc20_service_key(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_CRYPTO_DELEGATED,
        )
        result = classify_and_build_vault_intent(
            "USDT_TRC20:tron_mainnet",
        )
        self.assertEqual(
            result["intent"], INTENT_CRYPTO_DELEGATED,
        )

    def test_router_delegates_for_show_my_eth_wallet(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_CRYPTO_DELEGATED,
        )
        result = classify_and_build_vault_intent("show my ETH wallet")
        self.assertEqual(
            result["intent"], INTENT_CRYPTO_DELEGATED,
        )

    def test_router_delegates_for_show_monero_wallet(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_CRYPTO_DELEGATED,
        )
        result = classify_and_build_vault_intent(
            "show my Monero wallet",
        )
        self.assertEqual(
            result["intent"], INTENT_CRYPTO_DELEGATED,
        )

    def test_router_does_not_leak_service_key_to_file_search(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_FILE_SEARCH,
        )
        for msg in (
            "show me ETH:ethereum_mainnet",
            "ETH:ethereum_mainnet",
            "XMR:monero_mainnet",
            "USDT_TRC20:tron_mainnet",
            "SOL:solana_mainnet",
            "show my ETH wallet",
            "show my Monero wallet",
        ):
            with self.subTest(msg=msg):
                result = classify_and_build_vault_intent(msg)
                self.assertNotEqual(
                    result["intent"], INTENT_FILE_SEARCH,
                    msg=(
                        f"{msg!r} must NEVER route to file search "
                        "— that would produce the "
                        "'I couldn't find any files matching...' bug"
                    ),
                )


class TestNoSecretMaterialInPayloads(unittest.TestCase):
    """Neither the source of the secure-items handlers nor the
    activity feed reads or forwards the encrypted wallet secret,
    even if a crypto_wallet_account row survives filtering by
    mistake."""

    def test_list_secure_items_never_selects_encrypted_data(self):
        for rel in (
            "routes/login_routes.py",
            "routes/vault_manage_routes.py",
        ):
            src = _read(rel)
            body = _slice_route(src, "/list-secure-items")
            self.assertNotRegex(
                body,
                r"SELECT[\s\S]*?encrypted_data[\s\S]*?FROM\s+vault_items",
                msg=(
                    f"{rel} /list-secure-items must not SELECT "
                    "encrypted_data — otherwise a leaked wallet "
                    "row would expose the encrypted secret"
                ),
            )

    def test_activity_feed_does_not_forward_encrypted_data(self):
        src = _read("vault_chat_card_data.py")
        anchor = "def build_activity_data("
        start = src.index(anchor)
        end = src.index("\n\ndef ", start + 1)
        body = src[start:end]
        self.assertNotRegex(
            body,
            r"SELECT[\s\S]*?encrypted_data[\s\S]*?FROM\s+vault_items",
        )


class TestPreserveUserCryptoNotes(unittest.TestCase):
    """User-created crypto secure notes use item_types like
    'crypto_wallet_address' / 'crypto_note' — NOT
    'crypto_wallet_account' — and must remain user-visible."""

    def test_crypto_wallet_address_is_not_system(self):
        from vault_item_visibility import is_system_item_type
        self.assertFalse(is_system_item_type("crypto_wallet_address"))

    def test_crypto_note_is_not_system(self):
        from vault_item_visibility import is_system_item_type
        self.assertFalse(is_system_item_type("crypto_note"))

    def test_crypto_seed_phrase_is_not_system(self):
        from vault_item_visibility import is_system_item_type
        self.assertFalse(is_system_item_type("crypto_seed_phrase"))


if __name__ == "__main__":
    unittest.main()
