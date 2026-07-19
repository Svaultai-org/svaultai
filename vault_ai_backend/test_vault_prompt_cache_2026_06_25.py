

from __future__ import annotations

import unittest

import tools


class StaticSystemPromptByteStability(unittest.TestCase):
    def test_static_prompt_has_no_placeholders(self):
                                                          
                                                              
        prompt = tools.STATIC_VAULT_SYSTEM_PROMPT
        for placeholder in (
            "{VAULT_NAME}",
            "{VAULT_STATE}",
            "{LOCALE}",
            "{ENABLED_FEATURES}",
            "{HAS_MEMORY}",
            "{HAS_RELATIONSHIPS}",
            "{HAS_EXPIRY}",
        ):
            with self.subTest(placeholder=placeholder):
                self.assertNotIn(
                    placeholder, prompt,
                    msg=(
                        f"STATIC_VAULT_SYSTEM_PROMPT still "
                        f"contains {placeholder!r}; move it into "
                        "the dynamic runtime-context block."
                    ),
                )

    def test_static_prompt_is_long_enough_to_hit_openai_cache(self):
                                                                  
                                                               
        self.assertGreater(
            len(tools.STATIC_VAULT_SYSTEM_PROMPT), 4096,
            msg=(
                "STATIC_VAULT_SYSTEM_PROMPT is too short to "
                "reliably hit OpenAI's prompt cache (>=1024 "
                "tokens required)."
            ),
        )

    def test_two_consecutive_reads_byte_identical(self):
                                                                 
                                                                 
        a = tools.STATIC_VAULT_SYSTEM_PROMPT
        b = tools.STATIC_VAULT_SYSTEM_PROMPT
        self.assertEqual(a, b)

    def test_static_prompt_does_not_carry_runtime_facts(self):
                                                              
                        
        prompt = tools.STATIC_VAULT_SYSTEM_PROMPT.lower()
        for needle in (
            "timestamp", "currently:", "today is",
            "files in this vault:", "credentials saved:",
        ):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, prompt)


class DynamicRuntimeContextTests(unittest.TestCase):
    # 2026-07-20 (corrected): the runtime context slot is
    # ``vault_name`` — the user-chosen identity used both for
    # signing into the vault AND as the vault AI's name. The
    # interim ``vault_ai_name`` split (edf366b) was reverted; there
    # is one vault_name concept, server-authoritative, sourced from
    # vaults.vault_name for the authenticated vault_id.

    def test_includes_every_required_field(self):
        out = tools.build_vault_runtime_context(
            vault_name="Nova",
            vault_state="unlocked",
            locale="en-US",
            enabled_features="memory timeline; relationships",
            has_memory="on",
            has_relationships="on",
            has_expiry="on",
        )
        for field in (
            "Nova", "unlocked", "en-US",
            "memory timeline", "on",
        ):
            with self.subTest(field=field):
                self.assertIn(field, out)

    def test_different_names_produce_different_blocks(self):
        a = tools.build_vault_runtime_context(vault_name="Alpha")
        b = tools.build_vault_runtime_context(vault_name="Bravo")
        self.assertNotEqual(a, b)

    def test_same_state_produces_same_block(self):
        a = tools.build_vault_runtime_context(
            vault_name="Nova", vault_state="locked",
        )
        b = tools.build_vault_runtime_context(
            vault_name="Nova", vault_state="locked",
        )
        self.assertEqual(a, b)

    def test_defaults_are_safe(self):
        # No vault_name supplied → falls back to the neutral
        # "VaultAI" literal (never a hash, handle, UUID, or
        # template token).
        out = tools.build_vault_runtime_context()
        self.assertIn("RUNTIME CONTEXT", out)
        self.assertIn("VaultAI", out)
        # The pre-2026-07-20 default was "your vault" — with the
        # placeholder-substitution helper in place, the fallback
        # is now the neutral "VaultAI" product name.
        self.assertNotIn("your vault", out.lower())


class LegacySystemPromptAlias(unittest.TestCase):
    def test_system_prompt_alias_points_to_static(self):
                                                                  
                                                            
        self.assertEqual(
            tools.SYSTEM_PROMPT, tools.STATIC_VAULT_SYSTEM_PROMPT,
        )

    def test_legacy_alias_contains_no_runtime_substitutions(self):
        # 2026-07-20: {VAULT_NAME} was removed from the runtime
        # template. {VAULT_AI_NAME} is the replacement identity slot.
        # None of these substitution tokens may reach the static
        # prompt — they only ever live inside the runtime context
        # block (which gets .format()-substituted before send).
        for placeholder in (
            "{VAULT_NAME}", "{VAULT_AI_NAME}", "{VAULT_STATE}",
            "{LOCALE}", "{ENABLED_FEATURES}", "{HAS_MEMORY}",
            "{HAS_RELATIONSHIPS}", "{HAS_EXPIRY}",
        ):
            with self.subTest(placeholder=placeholder):
                self.assertNotIn(placeholder, tools.SYSTEM_PROMPT)


class ChatEndpointWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_chat_endpoint_uses_static_prompt(self):
                                                                 
                                                                 
        self.assertIn("STATIC_VAULT_SYSTEM_PROMPT,", self._src)
        self.assertIn(
            '{"role": "system", "content": STATIC_VAULT_SYSTEM_PROMPT}',
            self._src,
        )

    def test_chat_endpoint_appends_dynamic_context_after_static(self):
                                                                 
                                   
        self.assertIn(
            "build_vault_runtime_context",
            self._src,
        )
        static_idx = self._src.find(
            '"content": STATIC_VAULT_SYSTEM_PROMPT',
        )
        dynamic_idx = self._src.find(
            "_dynamic_context = build_vault_runtime_context",
        )
        self.assertGreater(static_idx, -1)
        self.assertGreater(dynamic_idx, -1)
                                                                 
                                                         
        append_idx = self._src.find(
            '"content": _dynamic_context,',
        )
        self.assertGreater(append_idx, static_idx)

    def test_chat_endpoint_invokes_compressor(self):
        self.assertIn(
            "from vault_history_compressor import compress_messages",
            self._src,
        )

    def test_user_message_appended_last(self):
                                                                 
                                                          
        self.assertIn(
            'messages.append({"role": "user", "content": safe_message})',
            self._src,
        )


class AiStreamCompressionWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_compression_runs_inside_ai_stream(self):
        self.assertIn(
            "from vault_history_compressor import (",
            self._src,
        )
        self.assertIn("compress_messages as _compress", self._src)

    def test_observability_log_for_compression(self):
                                                       
                                
        self.assertIn(
            "[CHAT-TRACE] history_compressed kept=",
            self._src,
        )


if __name__ == "__main__":
    unittest.main()
