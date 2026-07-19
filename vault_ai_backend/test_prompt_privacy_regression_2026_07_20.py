"""Prompt-privacy regression tests (2026-07-20).

Asserts that the assembled LLM system-prompt payload — static prompt
+ runtime context — never contains any of:

  * a canary-flavored canonical username
  * the base64url or hex form of a canary username_lookup_v1
  * a canary vault_id UUID
  * any 32-char hex substring
  * any 24-char Crockford VLT-* handle
  * an unresolved ``{TOKEN}`` template placeholder

Canary values are used so a positive detection is unambiguous even
if the real production values happened to look plain.

These invariants are the frontier of the 98c5afd privacy design.
Nothing about the vault-AI-name introduction may soften them.
"""

from __future__ import annotations

import base64
import re

import pytest


CANARY_CANONICAL_USERNAME = "canary_alexa_2026_07_20"
CANARY_USERNAME_LOOKUP_V1 = bytes(range(1, 33))                 # 32 bytes
CANARY_USERNAME_LOOKUP_V1_B64 = base64.urlsafe_b64encode(
    CANARY_USERNAME_LOOKUP_V1,
).decode("ascii").rstrip("=")
CANARY_USERNAME_LOOKUP_V1_HEX = CANARY_USERNAME_LOOKUP_V1.hex()
CANARY_VAULT_ID = "d3b07384-d9a8-4b6f-8e2e-7c1234567890"
CANARY_DISPLAY_NAME = "Canary Display Name 2026 07 20"


def _assemble_prompt_context(vault_name=None) -> str:
    from tools import STATIC_VAULT_SYSTEM_PROMPT, build_vault_runtime_context
    runtime = build_vault_runtime_context(
        vault_name=vault_name,
        vault_state="unlocked",
        locale="auto",
        enabled_features="files, credentials, inheritance",
        has_memory="yes",
        has_relationships="yes",
        has_expiry="yes",
    )
    return STATIC_VAULT_SYSTEM_PROMPT + "\n" + runtime


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("VAULTAI_ENV", "test")
    yield


class TestPromptDoesNotLeakIdentifiers:
    def test_no_canonical_username_in_prompt(self):
        prompt = _assemble_prompt_context(vault_name="Nova")
        assert CANARY_CANONICAL_USERNAME not in prompt
        assert "canary_alexa" not in prompt.lower()

    def test_no_username_lookup_v1_in_prompt(self):
        prompt = _assemble_prompt_context(vault_name="Nova")
        assert CANARY_USERNAME_LOOKUP_V1_B64 not in prompt
        assert CANARY_USERNAME_LOOKUP_V1_HEX not in prompt

    def test_no_vault_id_uuid_in_prompt(self):
        prompt = _assemble_prompt_context(vault_name="Nova")
        assert CANARY_VAULT_ID not in prompt

    def test_no_32_char_hex_substring_in_prompt(self):
        """A 32-character hex substring in the assembled prompt would
        indicate either a raw ``vault_name`` random hex slipped
        through, or a lookup identifier serialized in place. Both
        are leaks.
        """
        prompt = _assemble_prompt_context(vault_name="Nova")
        assert re.search(r"[0-9a-fA-F]{32}", prompt) is None

    def test_no_vlt_display_handle_in_prompt(self):
        prompt = _assemble_prompt_context(vault_name="Nova")
        assert re.search(r"VLT-[0-9A-HJKMNP-TV-Z]{4}", prompt) is None

    def test_no_display_name_leak_in_prompt(self):
        """We deliberately do NOT include the human's display name
        in the LLM prompt (per the 2026-07-20 review preference).
        Positive check: even if a caller passed it, the prompt
        builder has no slot for it and it must not appear.
        """
        prompt = _assemble_prompt_context(vault_name="Nova")
        assert CANARY_DISPLAY_NAME not in prompt

    def test_no_unresolved_template_token_in_prompt(self):
        prompt = _assemble_prompt_context(vault_name="Nova")
        # Must find NO occurrence of ``{IDENT}`` where IDENT is a
        # valid template variable name.
        assert re.search(r"\{[A-Z][A-Z0-9_]*\}", prompt) is None

    def test_vault_ai_name_none_still_safe(self):
        """When the row has no vault_ai_name, the fallback literal
        must be "VaultAI" — never a hash, handle, UUID, or template
        token.
        """
        prompt = _assemble_prompt_context(vault_name=None)
        assert "Vault name           : VaultAI" in prompt
        # And still no forbidden shapes.
        assert re.search(r"[0-9a-fA-F]{32}", prompt) is None
        assert re.search(r"VLT-[0-9A-HJKMNP-TV-Z]{4}", prompt) is None
        assert re.search(r"\{[A-Z][A-Z0-9_]*\}", prompt) is None


class TestSourceLevelPrivacyContract:
    def test_chat_prompt_context_takes_vault_id_not_vault_name(self):
        """After 2026-07-20 the prompt-context builder is invoked
        with the AUTHENTICATED vault_id, never with a client-
        supplied vault_name string. If a future refactor puts
        ``vault_name=`` back into the signature, the client-side
        leak surface is reopened.
        """
        import inspect
        from main import _build_chat_prompt_context
        sig = inspect.signature(_build_chat_prompt_context)
        assert "vault_id" in sig.parameters
        assert "vault_name" not in sig.parameters

    def test_chat_prompt_context_returns_vault_ai_name_key(self):
        import inspect
        from main import _build_chat_prompt_context
        src = inspect.getsource(_build_chat_prompt_context)
        assert '"VAULT_NAME"' in src
        # The interim "VAULT_AI_NAME" key from edf366b was reverted
        # when the vault_name concept was unified — the prompt
        # context must never re-introduce two keys for the same
        # concept.
        assert '"VAULT_AI_NAME"' not in src
