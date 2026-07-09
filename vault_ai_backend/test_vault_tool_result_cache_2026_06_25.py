

from __future__ import annotations

import logging
import time
import unittest

import vault_tool_result_cache as cache


_VAULT = "00000000-0000-0000-0000-000000000111"
_VAULT_OTHER = "00000000-0000-0000-0000-000000000222"
_TOKEN_A = "tok-aaaaaa"
_TOKEN_B = "tok-bbbbbb"


class _Base(unittest.TestCase):
    def setUp(self):
        cache.reset_cache_for_tests()


class BasicHitMiss(_Base):
    def test_first_call_misses_then_hits(self):
        c = cache.get_cache()
                              
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        ))
                
        ok = c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
            result='{"total_files":7}',
        )
        self.assertTrue(ok)
                             
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        )
        self.assertEqual(out, '{"total_files":7}')

    def test_hit_returns_byte_identical_string(self):
        c = cache.get_cache()
        body = '{"this":"is exactly that"}'
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_vault_files", args={"kind": "image"},
            result=body,
        )
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_vault_files", args={"kind": "image"},
        )
        self.assertEqual(out, body)


class VaultScope(_Base):
    def test_other_vault_cannot_read_cached_entry(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
            result='{"v":"1"}',
        )
        out = c.get(
            vault_id=_VAULT_OTHER, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        )
        self.assertIsNone(out)


class SessionScope(_Base):
    def test_other_token_cannot_read_cached_entry(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
            result='{"v":"1"}',
        )
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_B,
            tool_name="get_vault_status", args={},
        )
        self.assertIsNone(out)

    def test_invalidate_session_drops_entries(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
            result='{"v":"1"}',
        )
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_B,
            tool_name="get_vault_status", args={},
            result='{"v":"2"}',
        )
        c.invalidate_session(
            vault_id=_VAULT, token_id=_TOKEN_A,
        )
                                  
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        ))
                             
        self.assertEqual(c.get(
            vault_id=_VAULT, token_id=_TOKEN_B,
            tool_name="get_vault_status", args={},
        ), '{"v":"2"}')


class TtlExpiry(_Base):
    def test_entry_expires_after_ttl(self):
        c = cache.ToolResultCache(default_ttl=0.05)
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
            result='{"v":"1"}',
        )
                         
        time.sleep(0.1)
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        )
        self.assertIsNone(out)

    def test_short_ttl_tools_use_shorter_window(self):
        c = cache.ToolResultCache(
            default_ttl=10.0, short_ttl=0.05,
        )
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_activity", args={},
            result='{"v":"a"}',
        )
        time.sleep(0.1)
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_activity", args={},
        ))


class InvalidationRules(_Base):
    def _store_pair(self, c, tool_name):
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name=tool_name, args={},
            result='{"v":"x"}',
        )

    def test_file_uploaded_drops_listings_and_status(self):
        c = cache.get_cache()
        for tool in (
            "list_vault_files", "get_vault_status",
            "search_extracted_text",
        ):
            self._store_pair(c, tool)
        c.invalidate_for_event(
            vault_id=_VAULT, event="file_uploaded",
        )
        for tool in (
            "list_vault_files", "get_vault_status",
            "search_extracted_text",
        ):
            with self.subTest(tool=tool):
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id=_TOKEN_A,
                    tool_name=tool, args={},
                ))

    def test_credential_saved_drops_credential_metadata(self):
        c = cache.get_cache()
        for tool in (
            "list_saved_credentials", "list_secrets",
            "get_credential_metadata",
        ):
            self._store_pair(c, tool)
        c.invalidate_for_event(
            vault_id=_VAULT, event="credential_saved",
        )
        for tool in (
            "list_saved_credentials", "list_secrets",
            "get_credential_metadata",
        ):
            with self.subTest(tool=tool):
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id=_TOKEN_A,
                    tool_name=tool, args={},
                ))

    def test_credential_deleted_drops_credential_metadata(self):
        c = cache.get_cache()
        self._store_pair(c, "list_saved_credentials")
        c.invalidate_for_event(
            vault_id=_VAULT, event="credential_deleted",
        )
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_saved_credentials", args={},
        ))

    def test_file_renamed_drops_metadata_listings_only(self):
        c = cache.get_cache()
        self._store_pair(c, "list_vault_files")
        self._store_pair(c, "get_file_metadata")
                                                    
        self._store_pair(c, "list_expiring_items")
        c.invalidate_for_event(
            vault_id=_VAULT, event="file_renamed",
        )
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_vault_files", args={},
        ))
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_file_metadata", args={},
        ))
                                   
        self.assertIsNotNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_expiring_items", args={},
        ))

    def test_unknown_event_is_a_noop(self):
        c = cache.get_cache()
        self._store_pair(c, "get_vault_status")
        n = c.invalidate_for_event(
            vault_id=_VAULT, event="totally_made_up",
        )
        self.assertEqual(n, 0)
                         
        self.assertIsNotNone(c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        ))

    def test_invalidation_is_vault_scoped(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_vault_files", args={},
            result='{"a":"1"}',
        )
        c.put(
            vault_id=_VAULT_OTHER, token_id=_TOKEN_A,
            tool_name="list_vault_files", args={},
            result='{"b":"2"}',
        )
        c.invalidate_for_event(
            vault_id=_VAULT, event="file_uploaded",
        )
                                       
        self.assertEqual(c.get(
            vault_id=_VAULT_OTHER, token_id=_TOKEN_A,
            tool_name="list_vault_files", args={},
        ), '{"b":"2"}')


class NeverCacheList(_Base):
    _SECRET_OR_WRITE_TOOLS = (
        "retrieve_secret",
        "save_secret",
        "save_generated_credential_after_confirmation",
        "read_file_text",
        "read_image_with_vision",
        "read_media_transcript",
        "read_file_chunk",
    )

    def test_put_refuses_secret_or_write_tools(self):
        c = cache.get_cache()
        for tool in self._SECRET_OR_WRITE_TOOLS:
            with self.subTest(tool=tool):
                stored = c.put(
                    vault_id=_VAULT, token_id=_TOKEN_A,
                    tool_name=tool, args={},
                    result='{"raw":"secret"}',
                )
                self.assertFalse(
                    stored,
                    msg=f"{tool} must NEVER be cached",
                )
                                                       
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id=_TOKEN_A,
                    tool_name=tool, args={},
                ))

    def test_is_cacheable_says_false_for_blocklist(self):
        c = cache.get_cache()
        for tool in self._SECRET_OR_WRITE_TOOLS:
            with self.subTest(tool=tool):
                self.assertFalse(c.is_cacheable(tool))


class WhitelistConsistency(unittest.TestCase):
    def test_no_tool_is_in_both_lists(self):
        overlap = (
            cache.CACHEABLE_TOOLS & cache.NEVER_CACHEABLE_TOOLS
        )
        self.assertEqual(overlap, frozenset())

    def test_every_invalidation_target_is_in_cacheable(self):
                                                                 
                                                               
        for event, tools in cache.INVALIDATION_RULES.items():
            for t in tools:
                with self.subTest(event=event, tool=t):
                    self.assertIn(t, cache.CACHEABLE_TOOLS)


class ArgsNormalisation(_Base):
    def test_whitespace_in_string_arg_still_hits(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="search_extracted_text",
            args={"query": "Louis Iodato"},
            result='{"hits":[]}',
        )
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="search_extracted_text",
            args={"query": "  Louis Iodato  "},
        )
        self.assertEqual(out, '{"hits":[]}')

    def test_key_order_doesnt_matter(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_vault_files",
            args={"kind": "image", "query": "x"},
            result='{"a":1}',
        )
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="list_vault_files",
            args={"query": "x", "kind": "image"},
        )
        self.assertEqual(out, '{"a":1}')

    def test_different_args_get_different_entries(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="search_extracted_text",
            args={"query": "passport"},
            result='{"r":"p"}',
        )
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="search_extracted_text",
            args={"query": "visa"},
        )
        self.assertIsNone(out)


class ObservabilityLogs(_Base):
    def test_logs_contain_closed_set_metadata_only(self):
        c = cache.get_cache()
                                                              
                                                  
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="search_extracted_text",
            args={"query": "secret query payload xyzzy"},
            result='{"hits":[]}',
        )

        captured: list[str] = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        log = logging.getLogger("vault_tool_result_cache")
        handler = _Cap(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            c.get(
                vault_id=_VAULT, token_id=_TOKEN_A,
                tool_name="search_extracted_text",
                args={"query": "secret query payload xyzzy"},
            )
        finally:
            log.removeHandler(handler)
        all_logs = "\n".join(captured)
                                         
        self.assertIn("cache_hit=true", all_logs)
        self.assertIn("tool_name=search_extracted_text", all_logs)
        self.assertIn(
            f"vault_prefix={_VAULT[:8]}", all_logs,
        )
                                               
        self.assertNotIn("secret query payload xyzzy", all_logs)
        self.assertNotIn("args_hash", all_logs)
        self.assertNotIn("query=", all_logs)


class WiringSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()
        with open("routes/login_routes.py", "r", encoding="utf-8") as f:
            cls._login_src = f.read()
        with open("routes/auth_routes.py", "r", encoding="utf-8") as f:
            cls._auth_src = f.read()

    def test_handle_tool_call_calls_cache(self):
        self.assertIn(
            "from vault_tool_result_cache import (",
            self._src,
        )
        self.assertIn("maybe_get_cached(", self._src)
        self.assertIn("maybe_store(", self._src)

    def test_handle_tool_call_accepts_token_id(self):
        self.assertIn(
            "async def handle_tool_call(\n"
            "    tool_name: str, args: dict, vault_id: str, key: bytes,\n"
            "    token_id: str = \"\",\n"
            "):",
            self._src,
        )

    def test_ai_stream_passes_token_id_to_handler(self):
        self.assertIn("token_id=token_id,", self._src)

    def test_chat_endpoint_forwards_principal_token_id(self):
        self.assertIn(
            'token_id=str(principal.get("token_id") or "")',
            self._src,
        )

    def test_save_secret_invalidates_credential_cache(self):
        self.assertIn(
            'invalidate_for_event(\n                    vault_id=vault_id, '
            'event="credential_saved"',
            self._src,
        )

    def test_upload_invalidates_file_cache(self):
        self.assertIn(
            'invalidate_for_event(\n                vault_id=vault_id, '
            'event="file_uploaded"',
            self._src,
        )

    def test_delete_login_invalidates_credential_cache(self):
        self.assertIn(
            'invalidate_for_event(',
            self._login_src,
        )
        self.assertIn('event="credential_deleted"', self._login_src)

    def test_logout_drops_session_cache(self):
        self.assertIn(
            "from vault_tool_result_cache import invalidate_session",
            self._auth_src,
        )


class ArgsDroppingInternalFields(_Base):
    def test_empty_args_treated_as_empty_dict(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args=None,
            result='{"x":1}',
        )
        out = c.get(
            vault_id=_VAULT, token_id=_TOKEN_A,
            tool_name="get_vault_status", args={},
        )
        self.assertEqual(out, '{"x":1}')


class ConfigSurface(unittest.TestCase):
    def test_max_entries_is_positive_int(self):
        self.assertGreater(cache.MAX_CACHE_ENTRIES, 0)

    def test_default_ttl_is_five_minutes_default(self):
                                                                
                                                                  
        import os
        if not os.environ.get("VAULTAI_TOOL_CACHE_TTL_SECS"):
            self.assertEqual(cache.DEFAULT_TTL_SECS, 300.0)


if __name__ == "__main__":
    unittest.main()
