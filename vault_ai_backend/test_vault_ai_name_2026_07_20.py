"""Regression tests for the 2026-07-20 vault AI name introduction.

Adds four separate identity concepts to the codebase:

  canonical_username   client-only login identifier (98c5afd)
  display_name         human owner's visible name (already existed
                       as ``display_username`` for legacy reasons)
  vault_ai_name        NEW — user-chosen name of their vault's AI
                       keeper, injected into the LLM prompt server-
                       authoritatively so the assistant maintains a
                       persistent identity profile across turns
  vault_id             internal opaque identifier (never surfaced)

This suite covers:

  * ``normalize_vault_ai_name`` shape rules (trim, whitespace
    collapse, length cap, control-char reject, None-on-empty)
  * ``build_vault_runtime_context`` injects the normalized name
    and never leaks a placeholder token or an internal identifier
  * ``build_vault_runtime_context`` falls back to the neutral
    ``VaultAI`` literal when the name is missing/invalid — never
    a hash, never a handle, never a UUID
  * ``assert_no_unresolved_placeholders`` fails closed in dev/test
    envs and strips + logs in production
  * ``STATIC_VAULT_SYSTEM_PROMPT`` no longer instructs the model
    to say ``I'm your vault`` (the specific canned phrase from
    before this change)
  * ``STATIC_VAULT_SYSTEM_PROMPT`` no longer uses the
    ``second owner`` framing that implied legal co-ownership
  * ``VaultAiNameUpdateRequest`` / ``VaultAiNameResponse`` shapes
"""

from __future__ import annotations

import pytest


class TestNormalizeVaultAiName:
    def test_none_returns_none(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name(None) is None

    def test_empty_returns_none(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name("") is None
        assert normalize_vault_ai_name("   ") is None
        assert normalize_vault_ai_name("\t\n") is None

    def test_trim_and_collapse(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name("  Nova  ") == "Nova"
        assert normalize_vault_ai_name("Nova  Star") == "Nova Star"
        assert normalize_vault_ai_name("\tAtlas\n") == "Atlas"

    def test_length_cap_60_chars_pass(self):
        from tools import normalize_vault_ai_name
        name = "N" * 60
        assert normalize_vault_ai_name(name) == name

    def test_length_cap_61_rejects(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name("N" * 61) is None

    def test_control_chars_reject(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name("Nova\x00") is None
        assert normalize_vault_ai_name("N\x1bova") is None

    def test_non_string_returns_none(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name(42) is None  # type: ignore[arg-type]
        assert normalize_vault_ai_name({"a": 1}) is None  # type: ignore[arg-type]

    def test_bomb_input_rejected_fast(self):
        from tools import normalize_vault_ai_name
        assert normalize_vault_ai_name("N" * 100_000) is None


class TestBuildVaultRuntimeContext:
    def test_injects_user_chosen_name(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_ai_name="Nova")
        assert "Vault AI name        : Nova" in ctx

    def test_falls_back_to_neutral_literal_when_none(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_ai_name=None)
        assert "Vault AI name        : VaultAI" in ctx

    def test_falls_back_when_input_normalizes_to_none(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_ai_name="   \t   ")
        assert "Vault AI name        : VaultAI" in ctx

    def test_never_contains_vault_name_label(self, monkeypatch):
        """Regression: the prior template exposed a "Vault name" slot
        which received the VLT handle / random hex placeholder. That
        line has been removed entirely.
        """
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_ai_name="Nova")
        assert "Vault name           :" not in ctx
        assert "Vault name          :" not in ctx
        assert "Vault name        :" not in ctx

    def test_never_leaks_placeholder_token(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_ai_name="Nova")
        assert "{VAULT_AI_NAME}" not in ctx
        assert "{VAULT_NAME}" not in ctx
        assert "{" not in ctx or "{VAULT" not in ctx


class TestAssertNoUnresolvedPlaceholders:
    def test_clean_prompt_passes(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import assert_no_unresolved_placeholders
        assert assert_no_unresolved_placeholders("hello world") == "hello world"

    def test_dev_env_fails_closed(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "dev")
        from tools import assert_no_unresolved_placeholders
        with pytest.raises(AssertionError):
            assert_no_unresolved_placeholders("Your name is {VAULT_AI_NAME}")

    def test_test_env_fails_closed(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import assert_no_unresolved_placeholders
        with pytest.raises(AssertionError):
            assert_no_unresolved_placeholders("hi {VAULT_NAME}")

    def test_production_strips_and_returns(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "production")
        from tools import assert_no_unresolved_placeholders
        result = assert_no_unresolved_placeholders(
            "Your name is {VAULT_AI_NAME}."
        )
        assert "{" not in result
        assert "VAULT_AI_NAME" not in result


class TestStaticSystemPromptShape:
    def test_static_prompt_no_generic_i_am_your_vault_canned_line(self):
        """The pre-2026-07-20 identity block instructed the model to
        reply "I'm your vault. I keep track of what you store here..."
        as a canned self-identity answer. That instruction is now
        replaced by a named-keeper identity that responds specifically.
        The specific canned string must NOT reappear in the static
        prompt or the vault AI name feature silently regresses.
        """
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        assert "I'm your vault. I keep track of what you store" \
            not in STATIC_VAULT_SYSTEM_PROMPT

    def test_static_prompt_uses_ai_keeper_language_not_second_owner(self):
        """Per the 2026-07-20 review adjustment: use "trusted AI
        keeper" / "AI custodian" instead of "second owner" (which
        implied legal ownership).
        """
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        assert "second owner" not in STATIC_VAULT_SYSTEM_PROMPT
        assert "co-owner" not in STATIC_VAULT_SYSTEM_PROMPT.lower() or \
               "NOT a co-owner" in STATIC_VAULT_SYSTEM_PROMPT
        assert "AI keeper" in STATIC_VAULT_SYSTEM_PROMPT
        assert "AI custodian" in STATIC_VAULT_SYSTEM_PROMPT

    def test_static_prompt_references_runtime_ai_name_slot(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        assert "Vault AI name" in STATIC_VAULT_SYSTEM_PROMPT

    def test_static_prompt_forbids_identifier_conflation(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        # The identity block must specifically call out the four
        # concepts that must never be conflated. If any of these
        # anchors are missing, the LLM can be nudged into treating
        # the account username as its own name (or vice versa).
        assert "vault AI name" in STATIC_VAULT_SYSTEM_PROMPT
        assert "display name" in STATIC_VAULT_SYSTEM_PROMPT
        assert "account username" in STATIC_VAULT_SYSTEM_PROMPT
        assert "internal identifier" in STATIC_VAULT_SYSTEM_PROMPT


class TestRequestModels:
    def test_vault_ai_name_update_accepts_string(self):
        from routes.auth_routes import VaultAiNameUpdateRequest
        req = VaultAiNameUpdateRequest(vault_ai_name="Nova")
        assert req.vault_ai_name == "Nova"

    def test_vault_ai_name_update_accepts_null(self):
        from routes.auth_routes import VaultAiNameUpdateRequest
        req = VaultAiNameUpdateRequest(vault_ai_name=None)
        assert req.vault_ai_name is None

    def test_me_response_carries_vault_ai_name(self):
        from routes.auth_routes import MeResponse
        assert "vault_ai_name" in MeResponse.model_fields
