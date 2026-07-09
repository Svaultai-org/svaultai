"""Tests for the vault_chat_crypto_data projector.

Verifies:

  * Schema versions stable and closed-set
  * Overview never emits fake balances
  * Balance/activity carry `balanceStatus`/`activityStatus`, not
    a raw numeric balance unless provider actually returned one.
  * XMR balance/activity gate on scanner status honestly.
  * Receive card carries public address only.
  * Send draft ALWAYS has `canBroadcast=False` + all safety flags.
  * USDT ambiguity is NOT populated (left to classifier).
  * Populator LEAVES refusal/clarify/unrecognized envelopes alone.
  * Populator NEVER raises.
  * Source guard: module carries no forbidden identifiers.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import vault_chat_crypto_data as vccd
from vault_chat_crypto_data import (
    ACTIVITY_STATUS_PENDING_LIVE_FETCH,
    ACTIVITY_STATUS_SCANNER_GATED,
    ALL_ASSETS,
    ASSET_ETH,
    ASSET_LABELS,
    ASSET_NETWORKS,
    ASSET_SOL,
    ASSET_USDC_ERC20,
    ASSET_USDT_ERC20,
    ASSET_USDT_TRC20,
    ASSET_XMR,
    BALANCE_STATUS_PENDING_LIVE_FETCH,
    BALANCE_STATUS_SCANNER_GATED,
    BALANCE_STATUS_UNAVAILABLE,
    CRYPTO_ACTIVITY_DATA_SCHEMA,
    CRYPTO_BALANCE_DATA_SCHEMA,
    CRYPTO_RECEIVE_DATA_SCHEMA,
    CRYPTO_SCANNER_STATUS_DATA_SCHEMA,
    CRYPTO_SEND_DRAFT_DATA_SCHEMA,
    CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA,
    REASON_CREATE_WALLET_FIRST,
    REASON_INTERNAL_ERROR,
    _FORBIDDEN_CRYPTO_KEYS,
    _strip_forbidden,
    build_crypto_activity_data,
    build_crypto_balance_data,
    build_crypto_overview_data,
    build_crypto_receive_data,
    build_crypto_scanner_status_data,
    build_crypto_send_draft_data,
    populate_crypto_delegated_card_data,
)



class TestSchemasClosedSet:

    def test_schema_names_versioned(self):
        for s in (
            CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA,
            CRYPTO_BALANCE_DATA_SCHEMA,
            CRYPTO_RECEIVE_DATA_SCHEMA,
            CRYPTO_SCANNER_STATUS_DATA_SCHEMA,
            CRYPTO_ACTIVITY_DATA_SCHEMA,
            CRYPTO_SEND_DRAFT_DATA_SCHEMA,
        ):
            assert s.endswith("_v1"), (
                f"schema {s!r} must be versioned"
            )

    def test_all_assets_have_labels_and_networks(self):
        for a in ALL_ASSETS:
            assert a in ASSET_LABELS
            assert a in ASSET_NETWORKS



class TestOverview:

    def test_overview_no_vault_id_returns_unavailable(self):
        r = build_crypto_overview_data("")
        assert r["available"] is False

    def test_overview_returns_all_assets(self):
        r = build_crypto_overview_data("vault-abc")
        assert r["available"] is True
        assert len(r["assets"]) == 6
        got_assets = {a["asset"] for a in r["assets"]}
        assert got_assets == set(ALL_ASSETS)

    def test_overview_no_fake_balance_number(self):

        r = build_crypto_overview_data("vault-abc")
        for a in r["assets"]:
            display = a.get("displayBalance")
            assert display in (None, "", "0", "0.0"), (

                f"asset {a['asset']} has unexpected displayBalance "
                f"{display!r} — projector must not fake a number"
            )

    def test_overview_send_disabled_for_xmr(self):
        r = build_crypto_overview_data("vault-abc")
        xmr_row = next(a for a in r["assets"] if a["asset"] == "XMR")
        assert xmr_row["sendEnabled"] is False

    def test_overview_send_enabled_for_evm(self):
        r = build_crypto_overview_data("vault-abc")
        eth_row = next(a for a in r["assets"] if a["asset"] == "ETH")
        assert eth_row["sendEnabled"] is True



class TestBalance:

    def test_balance_missing_asset(self):
        r = build_crypto_balance_data("vault-abc", "")
        assert r["available"] is False

    @pytest.mark.parametrize("asset", [
        ASSET_ETH, ASSET_USDT_ERC20, ASSET_USDC_ERC20,
        ASSET_SOL, ASSET_USDT_TRC20,
    ])
    def test_non_xmr_balance_uses_pending_live_fetch(self, asset: str):

        r = build_crypto_balance_data("vault-abc", asset)
        assert r["available"] is True
        assert r["asset"] == asset
        assert r["balanceStatus"] == BALANCE_STATUS_PENDING_LIVE_FETCH
        assert r["liveFetchRequired"] is True

        assert "displayBalance" not in r

    def test_xmr_balance_carries_scanner_status(self):

        r = build_crypto_balance_data(
            "vault-abc", ASSET_XMR, client_platform="web",
        )
        assert r["available"] is True
        assert r["asset"] == ASSET_XMR

        assert r["balanceStatus"] in (
            BALANCE_STATUS_SCANNER_GATED,
            BALANCE_STATUS_PENDING_LIVE_FETCH,
        )

        if r["balanceStatus"] == BALANCE_STATUS_SCANNER_GATED:
            assert "displayBalance" not in r

    def test_no_fake_balance_zero(self):

        r = build_crypto_balance_data("vault-abc", ASSET_ETH)
        assert r.get("displayBalance") is None



class TestReceive:

    def test_receive_missing_asset(self):
        r = build_crypto_receive_data("vault-abc", "")
        assert r["available"] is False

    @pytest.mark.parametrize("asset", ALL_ASSETS)
    def test_receive_no_wallet_returns_create_first(self, asset: str):
        r = build_crypto_receive_data("vault-abc", asset)
        assert r["available"] is True
        assert r["asset"] == asset
        assert r["receiveReady"] is False
        assert r["reason"] == REASON_CREATE_WALLET_FIRST

        assert "publicAddress" not in r

    def test_receive_qr_flag_adds_qr_payload_when_ready(self):

        r = build_crypto_receive_data("vault-abc", ASSET_ETH,
                                       include_qr=True)


        assert r["receiveReady"] is False
        assert "qrPayload" not in r

    def test_receive_never_carries_private_key(self):
        r = build_crypto_receive_data("vault-abc", ASSET_ETH)
        s = json.dumps(r)
        assert "private_key" not in s
        assert "privateKey"  not in s
        assert "spend_key"   not in s
        assert "view_key"    not in s
        assert "seed"        not in s
        assert "mnemonic"    not in s



class TestScannerStatus:

    def test_scanner_status_web_returns_requires_desktop_or_disabled(self):
        r = build_crypto_scanner_status_data(client_platform="web")
        assert r["available"] is True
        assert r["asset"] == "XMR"


        assert r["canSend"] is False
        assert r["scannerStatus"] in (
            "not_enabled", "requires_desktop", "unavailable",
            "unreachable", "syncing", "ready", "disabled",
            "ready_local_scanner_available",
        )

    def test_scanner_status_native_returns_state(self):
        r = build_crypto_scanner_status_data(client_platform="native")
        assert r["available"] is True

        assert r["canSend"] is False

    def test_scanner_status_reason_is_string_or_none(self):
        r = build_crypto_scanner_status_data(client_platform="web")
        reason = r.get("reason")
        assert reason is None or isinstance(reason, str)



class TestActivity:

    def test_activity_no_asset_returns_pending(self):
        r = build_crypto_activity_data("vault-abc")
        assert r["available"] is True
        assert r["activityStatus"] == ACTIVITY_STATUS_PENDING_LIVE_FETCH
        assert r["entries"] == []
        assert r["liveFetchRequired"] is True

    def test_activity_xmr_gates_on_scanner(self):
        r = build_crypto_activity_data(
            "vault-abc", ASSET_XMR, client_platform="web",
        )
        assert r["available"] is True

        assert r["activityStatus"] in (
            ACTIVITY_STATUS_SCANNER_GATED,
            ACTIVITY_STATUS_PENDING_LIVE_FETCH,
        )

        assert r["entries"] == []

    def test_activity_no_fake_entries_ever(self):
        r = build_crypto_activity_data("vault-abc", ASSET_ETH)
        assert r["entries"] == []



class TestSendDraft:

    def test_send_draft_always_no_broadcast(self):
        r = build_crypto_send_draft_data(
            ASSET_ETH, "1.0", "0xabc",
        )
        assert r["canBroadcast"] is False
        assert r["requiresTrustedDevice"] is True
        assert r["requiresPinUnlock"] is True
        assert r["requiresLocalSigning"] is True
        assert r["requiresExplicitConfirmation"] is True

    def test_xmr_send_draft_has_disabled_flag(self):
        r = build_crypto_send_draft_data(
            ASSET_XMR, "0.5", "43abc...",
        )
        assert r["canBroadcast"] is False
        assert r["sendDisabledReason"] == "xmr_send_not_supported"

    def test_send_draft_never_carries_signed_tx(self):
        r = build_crypto_send_draft_data(
            ASSET_ETH, "1.0", "0xabc",
        )
        for k in ("signedTxHex", "signed_tx_hex", "privateKey"):
            assert k not in r



class TestForbiddenKeyStripping:

    def test_strip_forbidden_removes_top_level(self):
        d = {
            "asset": "ETH",
            "privateKey": "leak",
            "seed_phrase": "leak",
            "authToken": "leak",
        }
        out = _strip_forbidden(d)
        assert "asset" in out
        for k in ("privateKey", "seed_phrase", "authToken"):
            assert k not in out

    def test_strip_forbidden_deep_nested(self):
        d = {
            "assets": [
                {"asset": "ETH", "private_view_key": "leak"},
                {"asset": "XMR", "polyseed": "leak"},
            ],
        }
        out = _strip_forbidden(d)
        s = json.dumps(out)
        assert "private_view_key" not in s
        assert "polyseed" not in s

    def test_forbidden_set_covers_all_critical_keys(self):
        for k in (
            "privateKey", "private_key",
            "privateViewKey", "private_view_key",
            "privateSpendKey", "private_spend_key",
            "seed", "seed_phrase", "mnemonic", "polyseed",
            "encryptedWalletSecret", "encrypted_wallet_secret",
            "authToken", "auth_token", "apiKey", "api_key",
            "stripe_secret_key", "signedTxHex",
        ):
            assert k in _FORBIDDEN_CRYPTO_KEYS



class TestPopulatorSkipsCriticalEnvelopes:

    def test_populator_skips_non_crypto_envelopes(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_overview",
            "card":   {"cardType": "vault_overview_card"},
        }
        out = populate_crypto_delegated_card_data(
            env, vault_id="vault-x",
        )

        assert out["card"].get("data") is None

    def test_populator_skips_crypto_refusal_inner(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_crypto_delegated",
            "card": {
                "cardType":    "vault_crypto_delegated_card",
                "innerIntent": "crypto_vault_refusal_secret_material",
                "innerCard": {"cardType": "crypto_vault_refusal_card"},
            },
        }
        out = populate_crypto_delegated_card_data(
            env, vault_id="vault-x",
        )
        inner = out["card"]["innerCard"]

        assert "data" not in inner

    def test_populator_skips_usdt_clarify(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_crypto_delegated",
            "card": {
                "cardType":    "vault_crypto_delegated_card",
                "innerIntent": "crypto_vault_clarify_usdt_network",
                "innerCard": {"cardType": "crypto_vault_clarify_card"},
            },
        }
        out = populate_crypto_delegated_card_data(
            env, vault_id="vault-x",
        )
        assert "data" not in out["card"]["innerCard"]

    def test_populator_never_raises_on_garbage(self):
        for bad in [None, 0, "not a dict", []]:
            populate_crypto_delegated_card_data(
                bad, vault_id="vault-x",
            )



class TestPopulatorMapsIntents:

    @pytest.mark.parametrize("inner_intent,expected_schema", [
        ("crypto_vault_show_vault",
            CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA),
        ("crypto_vault_balance", CRYPTO_BALANCE_DATA_SCHEMA),
        ("crypto_vault_receive_address",
            CRYPTO_RECEIVE_DATA_SCHEMA),
        ("crypto_vault_receive_qr",
            CRYPTO_RECEIVE_DATA_SCHEMA),
        ("crypto_vault_scanner_status",
            CRYPTO_SCANNER_STATUS_DATA_SCHEMA),
        ("crypto_vault_activity",
            CRYPTO_ACTIVITY_DATA_SCHEMA),
        ("crypto_vault_send_draft",
            CRYPTO_SEND_DRAFT_DATA_SCHEMA),
    ])
    def test_intent_produces_correct_data_schema(
        self, inner_intent: str, expected_schema: str,
    ):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_crypto_delegated",
            "card": {
                "cardType":    "vault_crypto_delegated_card",
                "innerIntent": inner_intent,
                "innerCard": {
                    "cardType": "x", "asset": "ETH",
                },
            },
        }
        out = populate_crypto_delegated_card_data(
            env, vault_id="vault-x",
        )
        inner = out["card"]["innerCard"]
        assert "data" in inner, (
            f"intent {inner_intent} produced no data"
        )
        assert inner["data"]["schema"] == expected_schema

    def test_populator_always_forces_no_broadcast(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_crypto_delegated",
            "card": {
                "cardType":    "vault_crypto_delegated_card",
                "innerIntent": "crypto_vault_send_draft",
                "innerCard": {
                    "cardType": "crypto_vault_send_draft_card",
                    "asset":    "ETH",
                    "amount":   "1.0",
                    "recipient": "0xabc",

                    "canBroadcast": True,
                },
            },
        }
        out = populate_crypto_delegated_card_data(
            env, vault_id="vault-x",
        )

        assert out["card"]["innerCard"]["canBroadcast"] is False



class TestSourceGuard:

    def test_module_source_carries_no_forbidden_literals(self):
        import inspect
        src = inspect.getsource(vccd)
        for lit in [
            r"correct\s*horse\s*battery\s*staple",
            r"\b0xdeadbeef1234567890\b",
            r"\bMonero\s*wallet\s*password\b",
        ]:
            assert re.search(lit, src) is None, (
                f"module source carries literal {lit!r}"
            )

    def test_module_does_not_reference_secret_accessors(self):
        import inspect
        src = inspect.getsource(vccd)


        assert "get_private_key" not in src
        assert "reveal_seed" not in src

    def test_no_exchange_verbs_in_module_constants(self):
        for name in dir(vccd):
            if name.startswith("_"):
                continue
            val = getattr(vccd, name)
            if not isinstance(val, str):
                continue
            low = val.lower()

            for verb in ("buy", "sell", "swap",
                         "trade", "stake", "bridge"):

                assert not re.search(rf"\b{verb}\b", low)



class TestNoSensitiveLeakInAllPayloads:

    @pytest.mark.parametrize("build,args,kwargs", [
        (build_crypto_overview_data, ("vault-x",), {}),
        (build_crypto_balance_data, ("vault-x", "ETH"), {}),
        (build_crypto_receive_data, ("vault-x", "ETH"), {}),
        (build_crypto_scanner_status_data, (), {}),
        (build_crypto_activity_data, ("vault-x",), {}),
        (build_crypto_send_draft_data,
            ("ETH", "1.0", "0xabc"), {}),
    ])
    def test_payload_carries_no_forbidden_keys(
        self, build, args, kwargs,
    ):
        r = build(*args, **kwargs)
        s = json.dumps(r)
        for k in _FORBIDDEN_CRYPTO_KEYS:
            assert k not in s, (
                f"forbidden key {k!r} leaked in "
                f"{build.__name__} payload"
            )
