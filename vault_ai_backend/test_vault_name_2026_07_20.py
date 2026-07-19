"""Regression tests for the 2026-07-20 vault_name repurpose.

Product model (confirmed 2026-07-20):

  vault_name    User-chosen identity used to access the vault AND
                as the vault AI's name. ONE string, ONE meaning.
                Server-visible product metadata (not a private
                credential). Length 1..60 chars. Nullable after
                migration 0031 for accounts that haven't been
                backfilled yet — UI + prompt fall back to the
                neutral "VaultAI" literal.

  display_name  Human owner's visible name (optional).

  vault_id      Internal opaque identifier, never surfaced.

This suite verifies:

  * ``normalize_vault_name`` shape rules
  * ``build_vault_runtime_context`` injects the normalized name
    into the ``Vault name`` slot, falls back to "VaultAI" when
    absent, and never leaks a placeholder token or an internal
    identifier
  * ``assert_no_unresolved_placeholders`` fails closed in dev/test
    and strips + logs in production
  * ``STATIC_VAULT_SYSTEM_PROMPT`` uses "vault name" language (not
    the interim "vault AI name" language from edf366b), does not
    contain the canned "I'm your vault. I keep track of what you
    store" filler, and uses "trusted AI keeper" / "AI custodian"
    role framing (not "second owner")
  * Request models: ZkRegisterFinalizeRequest accepts a
    ``vault_name`` string, ZkLoginFinalizeRequest accepts a
    ``vault_name`` for the opportunistic backfill path
  * MeResponse carries ``vault_name`` as ``Optional[str]``
  * The retired ``vault_ai_name`` symbol is not reachable anywhere
    in the auth surface
"""

from __future__ import annotations

import pytest


class TestNormalizeVaultName:
    def test_none_returns_none(self):
        from tools import normalize_vault_name
        assert normalize_vault_name(None) is None

    def test_empty_returns_none(self):
        from tools import normalize_vault_name
        assert normalize_vault_name("") is None
        assert normalize_vault_name("   ") is None
        assert normalize_vault_name("\t\n") is None

    def test_trim_and_collapse(self):
        from tools import normalize_vault_name
        assert normalize_vault_name("  Nova  ") == "Nova"
        assert normalize_vault_name("Nova  Star") == "Nova Star"
        assert normalize_vault_name("\tAtlas\n") == "Atlas"

    def test_length_cap_60_pass(self):
        from tools import normalize_vault_name
        name = "N" * 60
        assert normalize_vault_name(name) == name

    def test_length_cap_61_rejects(self):
        from tools import normalize_vault_name
        assert normalize_vault_name("N" * 61) is None

    def test_control_chars_reject(self):
        from tools import normalize_vault_name
        assert normalize_vault_name("Nova\x00") is None
        assert normalize_vault_name("N\x1bova") is None

    def test_bomb_input_rejects_fast(self):
        from tools import normalize_vault_name
        assert normalize_vault_name("N" * 100_000) is None


class TestBuildVaultRuntimeContext:
    def test_injects_user_chosen_name(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_name="Nova")
        assert "Vault name           : Nova" in ctx

    def test_falls_back_to_vaultai_literal_on_none(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_name=None)
        assert "Vault name           : VaultAI" in ctx

    def test_falls_back_when_input_normalizes_to_none(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_name="   \t   ")
        assert "Vault name           : VaultAI" in ctx

    def test_never_leaks_placeholder_token(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import build_vault_runtime_context
        ctx = build_vault_runtime_context(vault_name="Nova")
        # ALL-CAPS template tokens are the leak surface — none may
        # appear in the composed prompt.
        assert "{VAULT_NAME}" not in ctx
        assert "{VAULT_AI_NAME}" not in ctx
        assert "{VAULT_STATE}" not in ctx


class TestAssertNoUnresolvedPlaceholders:
    def test_clean_prompt_passes(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "test")
        from tools import assert_no_unresolved_placeholders
        assert assert_no_unresolved_placeholders("hello") == "hello"

    def test_dev_env_fails_closed(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "dev")
        from tools import assert_no_unresolved_placeholders
        with pytest.raises(AssertionError):
            assert_no_unresolved_placeholders(
                "Your name is {VAULT_NAME}",
            )

    def test_production_strips_and_returns(self, monkeypatch):
        monkeypatch.setenv("VAULTAI_ENV", "production")
        from tools import assert_no_unresolved_placeholders
        result = assert_no_unresolved_placeholders(
            "Your name is {VAULT_NAME}.",
        )
        assert "{" not in result
        assert "VAULT_NAME" not in result


class TestStaticSystemPromptShape:
    def test_static_prompt_no_generic_i_am_your_vault_line(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        assert (
            "I'm your vault. I keep track of what you store"
            not in STATIC_VAULT_SYSTEM_PROMPT
        )

    def test_static_prompt_uses_ai_keeper_language_not_second_owner(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        assert "second owner" not in STATIC_VAULT_SYSTEM_PROMPT
        assert "AI keeper" in STATIC_VAULT_SYSTEM_PROMPT
        assert "AI custodian" in STATIC_VAULT_SYSTEM_PROMPT
        # The block must explicitly state the human is the primary
        # authority so the model does not claim co-ownership.
        assert (
            "primary owner and final authority"
            in STATIC_VAULT_SYSTEM_PROMPT
        )

    def test_static_prompt_references_runtime_vault_name_slot(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        # The identity block instructs the model to read its name
        # from the RUNTIME CONTEXT "Vault name" slot.
        assert '"Vault name"' in STATIC_VAULT_SYSTEM_PROMPT

    def test_static_prompt_avoids_retired_vault_ai_name_language(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT
        # edf366b briefly used "vault AI name" phrasing; the 2026-07-20
        # correction unified back to a single "vault name" concept.
        assert '"Vault AI name"' not in STATIC_VAULT_SYSTEM_PROMPT


class TestRequestModels:
    def test_zk_register_finalize_accepts_vault_name(self):
        from routes.auth_zk_routes import ZkRegisterFinalizeRequest
        assert "vault_name" in ZkRegisterFinalizeRequest.model_fields

    def test_zk_login_finalize_accepts_vault_name(self):
        from routes.auth_zk_routes import ZkLoginFinalizeRequest
        assert "vault_name" in ZkLoginFinalizeRequest.model_fields

    def test_me_response_carries_optional_vault_name(self):
        from routes.auth_routes import MeResponse
        # The 2026-07-20 correction made vault_name Optional
        # (nullable) after migration 0031 dropped NOT NULL.
        fields = MeResponse.model_fields
        assert "vault_name" in fields
        # Retired symbols must not resurface.
        assert "vault_ai_name" not in fields

    def test_patch_vault_name_endpoint_models(self):
        from routes.auth_routes import (
            VaultNameUpdateRequest,
            VaultNameResponse,
        )
        # Positive shape checks.
        req = VaultNameUpdateRequest(vault_name="Nova")
        assert req.vault_name == "Nova"
        req2 = VaultNameUpdateRequest(vault_name=None)
        assert req2.vault_name is None


class TestNoRetiredVaultAiNameSymbols:
    """The interim ``vault_ai_name`` concept from edf366b was folded
    back into ``vault_name``. Locks the surface so no future patch
    silently reintroduces two competing sources of truth.
    """

    def test_no_vault_ai_name_field_on_any_route_model(self):
        from routes import auth_routes, auth_zk_routes
        for module in (auth_routes, auth_zk_routes):
            src = open(module.__file__, "r", encoding="utf-8").read()
            assert "vault_ai_name" not in src, module.__file__

    def test_tools_module_has_no_vault_ai_name_symbol(self):
        import tools
        assert not hasattr(tools, "normalize_vault_ai_name")
        assert not hasattr(tools, "VAULT_AI_NAME_FALLBACK")
        assert not hasattr(tools, "VAULT_AI_NAME_MAX_CHARS")

    def test_prompt_context_key_is_vault_name(self):
        import inspect
        from main import _build_chat_prompt_context
        src = inspect.getsource(_build_chat_prompt_context)
        assert '"VAULT_NAME"' in src
        assert '"VAULT_AI_NAME"' not in src

    def test_helper_is_vault_name_not_ai_name(self):
        from main import _fetch_vault_name_for_prompt
        assert _fetch_vault_name_for_prompt is not None
        # Retired helper must be gone.
        import main
        assert not hasattr(main, "_fetch_vault_ai_name_for_prompt")
