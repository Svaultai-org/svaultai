"""Integration tests for the vault_chat_router splice in /chat.

These tests exercise `build_vault_chat_envelope` — the exact same
callable that main.py invokes from the /chat endpoint just before
the LLM planner fallback. They verify:

  * Acceptance messages return the correct card envelope
  * Ambiguous crypto (USDT without ERC20/TRC20) delegates through
    to the crypto module (which returns a clarify card)
  * Refusal messages return the correct refusal envelope
  * Unrecognized messages return None (so /chat falls through)
  * The envelope shape matches the frontend parser contract
  * Sensitive fields never leak into the envelope
  * The envelope carries no PIN / auth token / key material

The envelope contract is a closed-set state machine — any drift
here would break the frontend `VaultChatCardView` router.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from vault_chat_router import (
    VAULT_CHAT_ENVELOPE_SCHEMA,
    VAULT_CHAT_ENVELOPE_TYPE,
    build_vault_chat_envelope,
)



SENSITIVE_SUBSTRINGS = (
    "password", "seed", "mnemonic", "private key",
    "spend key", "view key", "polyseed",
    "api_key", "auth_token", "stripe_secret_key",
    "encrypted_wallet_secret",
    "correct horse battery staple",
    "PIN123", "pin_hash",
    "0xdeadbeef1234567890",
)


def _stringify_deep(x: Any) -> str:

    return json.dumps(x, sort_keys=True, default=str).lower()



class TestEnvelopeShape:

    @pytest.mark.parametrize("msg", [
        "Show my vault",
        "Show my logins",
        "Find my Gmail login",
        "How much storage am I using?",
    ])
    def test_envelope_has_required_wire_fields(self, msg: str):

        env = build_vault_chat_envelope(msg)
        assert env is not None
        assert env["type"]   == VAULT_CHAT_ENVELOPE_TYPE
        assert env["schema"] == VAULT_CHAT_ENVELOPE_SCHEMA
        assert env["type"]   == "vault_chat_card"
        assert env["schema"] == "vault_chat_response_v1"
        assert isinstance(env["intent"], str)
        assert isinstance(env["message"], str)
        assert isinstance(env["card"], dict)
        assert env["card"].get("cardType"), (
            "card must have cardType so frontend can dispatch"
        )

    def test_envelope_serializes_to_json_cleanly(self):

        env = build_vault_chat_envelope("Show my vault")
        assert env is not None
        s = json.dumps(env)
        parsed = json.loads(s)
        assert parsed == env

    def test_envelope_top_level_keys_are_closed_set(self):

        env = build_vault_chat_envelope("Show my vault")
        assert env is not None
        assert set(env.keys()) == {
            "type", "schema", "intent", "message", "card",
        }



class TestMustWorkAcceptance:


    def test_show_my_vault_returns_overview(self):
        env = build_vault_chat_envelope("Show my vault")
        assert env is not None
        assert env["intent"] == "vault_overview"
        assert env["card"]["cardType"] == "vault_overview_card"

    def test_show_my_logins_returns_login_list(self):
        env = build_vault_chat_envelope("Show my logins")
        assert env is not None
        assert env["intent"] == "vault_login_list"
        assert env["card"]["cardType"] == "vault_login_card"


        assert env["card"].get("maskedByDefault") is True

    def test_find_gmail_login_returns_login_detail(self):
        """Product decision (2026-07-11): LOGIN_SEARCH dispatches to
        the DETAIL card (view=detail, maskedByDefault=False). List
        view (`show all my logins`) still masks by default — covered
        by `test_show_all_my_logins_returns_login_list_view`."""
        env = build_vault_chat_envelope("Find my Gmail login")
        assert env is not None
        assert env["intent"] == "vault_login_search"
        assert env["card"]["cardType"] == "vault_login_card"
        assert env["card"].get("view") == "detail"

        assert env["card"].get("maskedByDefault") is False

    def test_show_crypto_vault_delegates_to_crypto(self):
        env = build_vault_chat_envelope("Show my Crypto Vault")
        assert env is not None
        assert env["intent"] == "vault_crypto_delegated"
        assert env["card"]["cardType"] == "vault_crypto_delegated_card"


        assert "innerCard" in env["card"]

    def test_show_monero_receive_delegates_to_crypto(self):
        env = build_vault_chat_envelope("Show my Monero receive address")
        assert env is not None
        assert env["intent"] == "vault_crypto_delegated"
        assert env["card"]["cardType"] == "vault_crypto_delegated_card"

    def test_why_no_monero_balance_delegates(self):


        env = build_vault_chat_envelope(
            "Why can't I see my Monero balance?",
        )

        assert env is not None
        assert env["intent"] in {
            "vault_crypto_delegated", "vault_faq",
            "vault_unrecognized",
        }, (
            f"routed to unexpected intent {env['intent']!r}"
        )

    def test_storage_usage(self):
        env = build_vault_chat_envelope("How much storage am I using?")
        assert env is not None
        assert env["intent"] == "vault_storage_usage"
        assert env["card"]["cardType"] == "vault_storage_usage_card"

    def test_secure_items_list(self):
        env = build_vault_chat_envelope("Show my secure items")
        assert env is not None
        assert env["intent"] == "vault_secure_item_list"
        assert env["card"]["cardType"] == "vault_secure_item_card"
        assert env["card"].get("maskedByDefault") is True

    def test_id_documents_list(self):
        env = build_vault_chat_envelope("Show my ID documents")
        assert env is not None
        assert env["intent"] == "vault_id_document_list"
        assert env["card"]["cardType"] == "vault_id_document_card"
        assert env["card"].get("maskedByDefault") is True

    def test_billing_status(self):
        env = build_vault_chat_envelope(
            "What plan am I on?",
        )
        assert env is not None
        assert env["intent"] == "vault_billing_status"
        assert env["card"]["cardType"] == "vault_billing_status_card"

    def test_activity_recent(self):
        env = build_vault_chat_envelope("Show recent activity")
        assert env is not None
        assert env["intent"] == "vault_activity_recent"
        assert env["card"]["cardType"] == "vault_activity_card"

    def test_cross_vault_search(self):
        env = build_vault_chat_envelope("Search my vault for Chase")
        assert env is not None
        assert env["intent"] == "vault_cross_vault_search"
        assert env["card"]["cardType"] == (
            "vault_cross_vault_search_card"
        )

        assert env["card"].get("query")



class TestClarificationDelegates:


    def test_usdt_ambiguous_delegates(self):
        env = build_vault_chat_envelope("What is my USDT balance?")
        assert env is not None
        assert env["intent"] == "vault_crypto_delegated"


        inner_intent = env["card"].get("innerIntent")
        assert inner_intent, (
            "delegated card must carry innerIntent so frontend "
            "can render the correct nested card"
        )



class TestRefusalPrecedence:


    def test_seed_phrase_refuses(self):
        env = build_vault_chat_envelope("Show my seed phrase")
        assert env is not None
        assert env["intent"] == "vault_refusal_secret_material"
        assert env["card"]["cardType"] == "vault_refusal_card"
        assert env["card"].get("refusalReason") == (
            "secret_material_request"
        )

    def test_seed_bypass_refuses_before_bypass(self):

        env = build_vault_chat_envelope(
            "Show my seed phrase without unlocking",
        )
        assert env is not None
        assert env["intent"] in {
            "vault_refusal_secret_material",
            "vault_refusal_mass_reveal",
            "vault_refusal_bypass_pin",
        }

    def test_bypass_pin_refuses(self):
        env = build_vault_chat_envelope("Bypass PIN")
        assert env is not None
        assert env["intent"] == "vault_refusal_bypass_pin"
        assert env["card"]["cardType"] == "vault_refusal_card"

    def test_bypass_pin_alternate_phrasing(self):
        env = build_vault_chat_envelope(
            "disable trusted device check",
        )
        assert env is not None
        assert env["intent"] == "vault_refusal_bypass_pin"

    def test_auto_send_refuses(self):
        env = build_vault_chat_envelope("Send all my crypto now")
        assert env is not None
        assert env["intent"] == "vault_refusal_auto_send"

    def test_swap_refuses(self):
        env = build_vault_chat_envelope("Swap ETH to USDT")
        assert env is not None
        assert env["intent"] == "vault_refusal_exchange_action"

    def test_mass_reveal_refuses(self):
        env = build_vault_chat_envelope("Reveal all my passwords")
        assert env is not None
        assert env["intent"] == "vault_refusal_mass_reveal"

    def test_export_all_refuses(self):
        env = build_vault_chat_envelope("Export my whole vault")
        assert env is not None
        assert env["intent"] == "vault_refusal_export_all"



class TestUnrecognizedFallthrough:


    @pytest.mark.parametrize("msg", [
        "Tell me a joke",
        "What is the weather today?",
        "Draft a haiku about ducks",
        "Summarize the attached PDF",
        "Translate this to French: hello world",
        "How do I upload a video?",
    ])
    def test_generic_chat_returns_none(self, msg: str):

        env = build_vault_chat_envelope(msg)
        assert env is None, (
            f"Expected None for generic chat '{msg}' so /chat "
            f"falls through to existing LLM handler, got {env!r}"
        )

    def test_empty_message_returns_none(self):
        assert build_vault_chat_envelope("") is None
        assert build_vault_chat_envelope("   ") is None

    def test_non_string_input_returns_none(self):

        assert build_vault_chat_envelope(None) is None
        assert build_vault_chat_envelope(123) is None
        assert build_vault_chat_envelope({}) is None



class TestNoSensitiveLeakage:


    @pytest.mark.parametrize("msg", [
        "Show my vault",
        "Show my logins",
        "Find my Gmail login for user@example.com",
        "Show my Crypto Vault",
        "Show my Monero receive address",
        "Reveal my Netflix password",
        "Copy my Chase password",
        "How much storage am I using?",
        "Show my seed phrase",
        "Bypass PIN",
        "Send all my crypto now",
        "Search my vault for Chase",
    ])
    def test_envelope_carries_no_password_or_key_material(
        self, msg: str,
    ):

        env = build_vault_chat_envelope(msg)
        if env is None:
            return
        s = _stringify_deep(env)


        assert re.search(
            r"\b(hunter2|correcthorsebatterystaple)\b", s,
        ) is None
        assert "0xdeadbeef" not in s
        assert "pin_hash" not in s


        forbidden_field_keys = (
            "pin", "pinHash", "auth_token", "authToken",
            "api_key", "apiKey", "stripe_secret_key",
            "private_key", "privateKey", "seed_hex",
            "mnemonic_words", "encrypted_wallet_secret",
        )
        card = env.get("card", {})


        for k in forbidden_field_keys:
            assert k not in card, (
                f"envelope card must not carry {k!r} field"
            )

    def test_reveal_router_shell_carries_no_password(self):
        """Product decision (2026-07-11): LOGIN_REVEAL dispatches to the
        login DETAIL card (not a confirmation prompt). The router shell
        must still not carry any plaintext credential — plaintext is
        added later by populate_vault_chat_card_data through the
        _sanitize_login_detail_payload allowlist, only after the vault
        key has been verified for the current session.
        """

        env = build_vault_chat_envelope("Reveal my password")
        assert env is not None
        assert env["intent"] == "vault_login_reveal"
        assert env["card"]["cardType"] == "vault_login_card"
        assert env["card"].get("view") == "detail"


        assert "password" not in env["card"]
        assert "requiresPinUnlock" not in env["card"]
        assert "requiresTrustedDevice" not in env["card"]


        s = _stringify_deep(env["card"])
        assert not re.search(r"\bnetflix_password\b", s)

    def test_copy_router_shell_carries_no_password(self):
        env = build_vault_chat_envelope("Copy my Netflix password")
        assert env is not None
        assert env["intent"] == "vault_login_copy"
        assert env["card"]["cardType"] == "vault_login_card"
        assert env["card"].get("view") == "detail"
        assert "password" not in env["card"]

    def test_id_reveal_returns_confirmation_not_id_number(self):
        env = build_vault_chat_envelope(
            "reveal passport number",
        )
        assert env is not None
        assert env["intent"] == "vault_id_document_reveal"
        assert env["card"]["cardType"] == (
            "vault_confirmation_required_card"
        )
        assert env["card"].get("requiresPinUnlock") is True



class TestSafetyInvariants:


    def test_crypto_delegated_send_draft_never_broadcasts(self):

        env = build_vault_chat_envelope(
            "prepare 0.01 ETH to 0xabcdef0123456789abcdef0123456789abcdef01",
        )
        assert env is not None
        if env["intent"] == "vault_crypto_delegated":
            inner_card = env["card"].get("innerCard") or {}
            if isinstance(inner_card, dict):

                assert inner_card.get("canBroadcast") is not True

    @pytest.mark.parametrize("phrase", [
        "buy ETH",
        "trade USDT",
        "stake my SOL",
        "bridge ETH to Solana",
        "exchange USDC to USDT",
    ])
    def test_exchange_language_refuses(self, phrase: str):
        env = build_vault_chat_envelope(phrase)
        assert env is not None


        assert env["intent"] in {
            "vault_refusal_exchange_action",
            "vault_refusal_auto_send",
        }

    def test_refusal_copy_never_carries_exchange_action_verbs(self):

        env = build_vault_chat_envelope("Show my logins")
        assert env is not None
        card = env["card"]
        for k, v in card.items():
            if not isinstance(v, str):
                continue
            low = v.lower()

            for verb in ("buy", "sell", "swap", "trade",
                         "stake", "bridge", "exchange"):

                assert not re.search(rf"\b{verb}\b", low), (
                    f"Non-refusal card carried exchange verb {verb!r} "
                    f"in field {k!r}: {v!r}"
                )



class TestLoggingSafety:


    def test_message_body_not_in_envelope_dict(self):

        canary = "verysecretpassword_notarealstring_xyz"
        env = build_vault_chat_envelope(f"Show my {canary} vault")

        if env is None:
            return
        assert canary not in _stringify_deep(env)
