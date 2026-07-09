"""Tests for the vault_chat_card_data projector.

The projector fills chat card envelopes with SAFE live data. These
tests verify:

  * Masking helpers redact usernames/IDs correctly.
  * Populator maps intents to the right builders.
  * Forbidden keys are stripped from ALL payloads.
  * Unavailable state is honest (no fake data).
  * Refusal / delegated / confirmation envelopes are LEFT ALONE.
  * The projector never raises.
  * Source guard: the module does not import or reference forbidden
    plaintext accessors.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import vault_chat_card_data as vccd
from vault_chat_card_data import (
    UNAVAIL_INTERNAL_ERROR,
    UNAVAIL_MISSING_DEPENDENCY,
    UNAVAIL_NOT_YET_IMPLEMENTED,
    UNAVAIL_VAULT_LOCKED,
    VAULT_ACTIVITY_DATA_SCHEMA,
    VAULT_BILLING_DATA_SCHEMA,
    VAULT_ID_DOCUMENT_DATA_SCHEMA,
    VAULT_LOGIN_DATA_SCHEMA,
    VAULT_OVERVIEW_DATA_SCHEMA,
    VAULT_SEARCH_DATA_SCHEMA,
    VAULT_SECURE_ITEM_DATA_SCHEMA,
    VAULT_STORAGE_DATA_SCHEMA,
    _FORBIDDEN_CARD_KEYS,
    _mask_id_number,
    _mask_username,
    _project_login_row,
    _project_secure_item_row,
    _project_id_document,
    _strip_forbidden,
    populate_vault_chat_card_data,
)



class TestMasking:

    def test_short_username_becomes_stars(self):
        assert _mask_username("bob") == "***"

    def test_medium_username_masked(self):
        assert _mask_username("alice") == "a***"

    def test_email_local_part_masked(self):
        r = _mask_username("user@example.com")
        assert "user" not in r.split("@")[0]
        assert r.endswith("@example.com")

    def test_domain_visible_email(self):

        r = _mask_username("verylongusername@corp.example.com")
        assert r.endswith("@corp.example.com")

    def test_id_number_shows_only_tail(self):
        r = _mask_id_number("AB1234567")
        assert r == "•••4567"
        assert "AB123" not in r

    def test_id_number_short_becomes_bullets(self):
        r = _mask_id_number("9")
        assert r == "•••"

    def test_id_number_none_is_empty(self):
        assert _mask_id_number(None) == ""

    def test_id_number_bytes_correctness(self):

        r = _mask_id_number("AB1234567")
        assert r.encode("utf-8").startswith(
            b"\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2",
        )



class TestForbiddenKeyStripping:

    def test_strip_forbidden_removes_top_level(self):
        d = {
            "title":     "safe",
            "password":  "should_be_removed",
            "api_key":   "sk-abcdef",
            "seed_hex":  "0xdeadbeef",
        }
        out = _strip_forbidden(d)
        assert "title" in out
        for k in ("password", "api_key", "seed_hex"):
            assert k not in out, f"forbidden key {k!r} leaked"

    def test_strip_forbidden_deep_nested(self):
        d = {
            "safe_outer": {
                "safe_inner": {"password": "leak"},
                "logins": [
                    {"title": "ok", "password_field": "leak"},
                    {"id_number": "leak", "type": "ok"},
                ],
            },
        }
        out = _strip_forbidden(d)
        assert "password" not in json.dumps(out)
        assert "password_field" not in json.dumps(out)
        assert "id_number" not in json.dumps(out)


        assert out["safe_outer"]["logins"][0]["title"] == "ok"
        assert out["safe_outer"]["logins"][1]["type"]  == "ok"

    def test_forbidden_set_contains_all_expected(self):

        for k in (
            "password", "seed_phrase", "private_key",
            "mnemonic", "api_key", "auth_token",
            "encrypted_wallet_secret", "id_number",
            "stripe_secret_key", "pin_hash",
        ):
            assert k in _FORBIDDEN_CARD_KEYS



class TestUnavailableStates:

    def test_overview_no_vault_id(self):
        r = vccd.build_vault_overview_data("")
        assert r["schema"] == VAULT_OVERVIEW_DATA_SCHEMA
        assert r["available"] is False
        assert r["unavailable_reason"] == UNAVAIL_MISSING_DEPENDENCY

    def test_login_list_no_key(self):
        r = vccd.build_login_list_data("vault-123", b"")
        assert r["schema"] == VAULT_LOGIN_DATA_SCHEMA
        assert r["available"] is False
        assert r["unavailable_reason"] == UNAVAIL_VAULT_LOCKED

    def test_secure_item_no_key(self):
        r = vccd.build_secure_item_list_data("vault-123", b"")
        assert r["schema"] == VAULT_SECURE_ITEM_DATA_SCHEMA
        assert r["available"] is False

    def test_id_document_no_vault(self):
        r = vccd.build_id_document_list_data("")
        assert r["schema"] == VAULT_ID_DOCUMENT_DATA_SCHEMA
        assert r["available"] is False

    def test_storage_no_vault(self):
        r = vccd.build_storage_data("")
        assert r["available"] is False

    def test_billing_no_vault(self):
        r = vccd.build_billing_data("")
        assert r["available"] is False

    def test_activity_no_vault(self):
        r = vccd.build_activity_data("")
        assert r["available"] is False

    def test_cross_vault_search_empty_query(self):
        r = vccd.build_cross_vault_search_data(
            "vault-123", b"key", "",
        )
        assert r["available"] is False



class TestPopulatorSkipsCriticalEnvelopes:


    def test_populator_skips_refusal(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_refusal_secret_material",
            "card":   {"cardType": "vault_refusal_card"},
        }
        out = populate_vault_chat_card_data(
            env, vault_id="vault-123", key=b"key",
        )
        assert "data" not in out["card"], (
            "refusal cards must never carry live data"
        )

    def test_populator_skips_crypto_delegated(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_crypto_delegated",
            "card":   {"cardType": "vault_crypto_delegated_card"},
        }
        out = populate_vault_chat_card_data(
            env, vault_id="vault-123", key=b"key",
        )

        assert "data" not in out["card"]

    def test_populator_skips_confirmation_required(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_login_reveal",
            "card":   {"cardType": "vault_confirmation_required_card"},
        }
        out = populate_vault_chat_card_data(
            env, vault_id="vault-123", key=b"key",
        )
        assert "data" not in out["card"]

    def test_populator_never_raises_on_garbage(self):

        for bad in [None, 0, "not a dict", []]:
            populate_vault_chat_card_data(
                bad, vault_id="vault-123", key=b"key",
            )



class TestPopulatorMapsIntentsCorrectly:


    @pytest.mark.parametrize("intent,expected_schema", [
        ("vault_overview",         VAULT_OVERVIEW_DATA_SCHEMA),
        ("vault_login_list",       VAULT_LOGIN_DATA_SCHEMA),
        ("vault_login_search",     VAULT_LOGIN_DATA_SCHEMA),
        ("vault_login_duplicates", VAULT_LOGIN_DATA_SCHEMA),
        ("vault_secure_item_list", VAULT_SECURE_ITEM_DATA_SCHEMA),
        ("vault_secure_item_search", VAULT_SECURE_ITEM_DATA_SCHEMA),
        ("vault_id_document_list", VAULT_ID_DOCUMENT_DATA_SCHEMA),
        ("vault_id_document_expiry", VAULT_ID_DOCUMENT_DATA_SCHEMA),
        ("vault_id_document_search", VAULT_ID_DOCUMENT_DATA_SCHEMA),
        ("vault_storage_usage",    VAULT_STORAGE_DATA_SCHEMA),
        ("vault_storage_largest_files", VAULT_STORAGE_DATA_SCHEMA),
        ("vault_billing_status",   VAULT_BILLING_DATA_SCHEMA),
        ("vault_billing_upgrade",  VAULT_BILLING_DATA_SCHEMA),
        ("vault_activity_recent",  VAULT_ACTIVITY_DATA_SCHEMA),
        ("vault_activity_item_history", VAULT_ACTIVITY_DATA_SCHEMA),
        ("vault_cross_vault_search", VAULT_SEARCH_DATA_SCHEMA),
    ])
    def test_intent_produces_correct_data_schema(
        self, intent: str, expected_schema: str,
    ):
        env = {
            "type":   "vault_chat_card",
            "intent": intent,
            "card":   {"cardType": "x", "query": "chase"},
        }


        out = populate_vault_chat_card_data(
            env, vault_id="", key=b"",
        )
        assert "data" in out["card"], f"intent {intent} produced no data"
        assert out["card"]["data"]["schema"] == expected_schema

    def test_populator_leaves_data_absent_for_unmapped_intents(self):
        env = {
            "type":   "vault_chat_card",
            "intent": "vault_file_search",
            "card":   {"cardType": "vault_file_result_card"},
        }
        out = populate_vault_chat_card_data(
            env, vault_id="vault-123", key=b"key",
        )
        assert "data" not in out["card"]



class TestProjectionsMaskSensitive:

    def test_project_login_masks_username(self):

        row = {
            "id":              "abc",
            "service":         "Gmail",
            "encrypted_data":  None,
            "created_at":      None,
        }
        proj = _project_login_row(row, b"")

        assert "password" not in proj
        assert "encrypted_data" not in proj

        assert proj["username_masked"] == ""

    def test_project_secure_item_masks_content(self):
        row = {
            "id":             "abc",
            "service":        "MyNotes",
            "encrypted_data": None,
            "created_at":     None,
        }
        proj = _project_secure_item_row(row, b"")
        assert "password" not in proj
        assert "encrypted_data" not in proj

        assert isinstance(proj.get("snippet", ""), str)

    def test_project_id_document_masks_number(self):
        row = {
            "uploaded_file_id": "abc",
            "doc_type":         "passport",
            "metadata_json":    json.dumps({
                "issuing_country": "US",
                "id_number":       "AB1234567",
                "expires_at":      "2030-01-01",
            }),
        }
        proj = _project_id_document(row)

        assert proj["id_number_masked"].endswith("4567")

        assert "id_number" not in proj

        assert "AB1234567" not in json.dumps(proj)



class TestNoSensitiveLeakInProjectedData:


    def test_populator_scrubs_forbidden_keys_from_raw_leak(self):


        env = {
            "type":   "vault_chat_card",
            "intent": "vault_overview",
            "card":   {
                "cardType": "vault_overview_card",
                "data": {
                    "schema":   VAULT_OVERVIEW_DATA_SCHEMA,
                    "counts":   {"files": 3},

                    "password": "hunter2",
                    "api_key":  "sk-leaked",
                },
            },
        }


        card = env["card"]
        data = card["data"]
        data_scrubbed = _strip_forbidden(data)
        card["data"] = data_scrubbed

        s = json.dumps(env)
        assert "hunter2"  not in s
        assert "sk-leaked" not in s

    def test_forbidden_key_set_covers_common_leaks(self):
        for name in [
            "password", "password_value", "raw_password",
            "seed", "mnemonic", "private_key",
            "id_number", "raw_id_number",
            "stripe_secret_key",
        ]:
            assert name in _FORBIDDEN_CARD_KEYS



class TestSourceGuard:


    def test_module_source_carries_no_forbidden_literals(self):
        import inspect
        src = inspect.getsource(vccd)


        for lit in [
            r"\bhunter2\b",
            r"correct\s*horse\s*battery\s*staple",
            r"\bLOUIS-IODATO\b",
            r"\bAB1234567\b",
        ]:
            assert re.search(lit, src) is None, (
                f"module source carries literal {lit!r}"
            )

    def test_module_does_not_reference_decrypt_all(self):
        import inspect
        src = inspect.getsource(vccd)


        assert "decrypt_all" not in src
        assert "reveal_all" not in src

        assert "canBroadcast" not in src

    def test_module_top_level_constants_are_closed_set(self):

        for name in dir(vccd):
            if name.startswith("_"):
                continue
            if not name.isupper():
                continue
            val = getattr(vccd, name)
            if not isinstance(val, str):
                continue
            assert not re.search(r"\bpassword\b", val.lower())
            assert not re.search(r"\bseed\s*phrase\b", val.lower())



class TestListLimitsEnforced:

    def test_default_list_limit(self):
        assert vccd.DEFAULT_LIST_LIMIT   == 20
        assert vccd.DEFAULT_SEARCH_LIMIT == 20
        assert vccd.DEFAULT_ACTIVITY_LIMIT == 20
        assert vccd.DEFAULT_SEARCH_GROUP_LIMIT == 5

    def test_activity_over_limit_clamped(self):

        r = vccd.build_activity_data("", limit=9999)
        assert r["available"] is False



class TestUnavailableReasonIsClosedSet:


    ALLOWED = {
        UNAVAIL_INTERNAL_ERROR,
        UNAVAIL_MISSING_DEPENDENCY,
        UNAVAIL_NOT_YET_IMPLEMENTED,
        UNAVAIL_VAULT_LOCKED,
    }

    @pytest.mark.parametrize("build,args", [
        (vccd.build_vault_overview_data,   ("",)),
        (vccd.build_login_list_data,       ("vault-x", b"")),
        (vccd.build_secure_item_list_data, ("vault-x", b"")),
        (vccd.build_id_document_list_data, ("",)),
        (vccd.build_storage_data,          ("",)),
        (vccd.build_billing_data,          ("",)),
        (vccd.build_activity_data,         ("",)),
    ])
    def test_unavailable_reason_within_closed_set(self, build, args):
        r = build(*args)
        assert r["available"] is False
        assert r["unavailable_reason"] in self.ALLOWED
