

from __future__ import annotations

import os
import unittest
from unittest import mock

import vault_tool_router as vtr


class BucketCoverage(unittest.TestCase):
    def test_every_dispatched_tool_lives_in_a_bucket_or_base(self):


        from vault_knowledge_tools import VAULT_KNOWLEDGE_DISPATCH
        in_buckets: set[str] = set(vtr.BASE_TOOLS)
        for tools in vtr.BUCKET_TOOLS.values():
            in_buckets.update(tools)
        for name in VAULT_KNOWLEDGE_DISPATCH.keys():
            with self.subTest(tool=name):
                self.assertIn(
                    name, in_buckets,
                    msg=(
                        f"Tool {name!r} is dispatchable but has "
                        "no bucket assignment. Add it to one of "
                        "vault_tool_router.BUCKET_TOOLS or to "
                        "BASE_TOOLS."
                    ),
                )


class ClassifierAccuracy(unittest.TestCase):
    EXAMPLES = (
                                    
        ("what's in my vault?",            "vault_state"),
        ("how big is my vault",            "vault_state"),
        ("status of my vault",             "vault_state"),
        ("list my files",                  "file_list"),
        ("show me all my photos",          "file_list"),
        ("what files do i have",           "file_list"),
        ("how many videos do i have",      "file_list"),
        ("find my passport",               "file_search"),
        ("do i have any tax forms",        "file_search"),
        ("where is my insurance card",     "file_search"),
        ("show me what's in this pdf",     "file_read"),
        ("read this file",                 "file_read"),
        ("transcribe this audio",          "file_read"),
        ("look at this photo",             "file_read"),
        ("create a password for chase",    "credentials"),
        ("save it now",                    "credentials"),
        ("generate and save",              "credentials"),
        ("who is in my vault",             "entities"),
        ("what people show up",            "entities"),
        ("what files are related to my passport", "relationships"),
        ("which docs go together",         "relationships"),
        ("what's expiring soon",           "expiry"),
        ("when does my passport expire",   "expiry"),
        ("what should i renew",            "expiry"),
        ("what did i recently add",        "activity"),
        ("show me uploads from this week", "activity"),
    )

    def test_each_example_hits_the_expected_bucket(self):
        for msg, bucket in self.EXAMPLES:
            with self.subTest(msg=msg):
                hits = vtr.select_buckets_for_message(msg)
                self.assertIn(
                    bucket, hits,
                    msg=(
                        f"Message {msg!r} should match bucket "
                        f"{bucket!r} but got {hits!r}"
                    ),
                )


def _fn(name):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        },
    }


class FilterFunctionSchemasTests(unittest.TestCase):
    def test_subset_for_simple_file_search_question(self):
        funcs = [_fn(n) for n in (
            "get_vault_status", "list_vault_files",
            "search_extracted_text", "search_vault_content",
            "read_file_text", "read_image_with_vision",
            "list_secrets", "retrieve_secret", "save_secret",
            "list_expiring_items", "list_file_relationships",
            "list_vault_entities",
        )]
        out = vtr.filter_function_schemas(
            funcs, "find my passport",
        )
        names = {f["function"]["name"] for f in out}
                                                               
        self.assertIn("search_extracted_text", names)
        self.assertIn("list_vault_files", names)
                                       
        self.assertNotIn("list_expiring_items", names)
        self.assertNotIn("list_file_relationships", names)
        self.assertNotIn("list_vault_entities", names)

    def test_base_tools_always_present_for_short_messages(self):
        funcs = [_fn(n) for n in (
            "get_vault_status", "list_vault_files",
            "search_extracted_text", "list_expiring_items",
        )]
        out = vtr.filter_function_schemas(funcs, "hello")
        names = {f["function"]["name"] for f in out}
        for base in vtr.BASE_TOOLS:
            with self.subTest(base=base):
                self.assertIn(base, names)

    def test_secret_tools_kept_by_default(self):
        funcs = [_fn(n) for n in (
            "save_secret", "retrieve_secret", "list_secrets",
            "get_vault_status",
        )]
        out = vtr.filter_function_schemas(funcs, "anything random")
        names = {f["function"]["name"] for f in out}
                                                              
        for n in ("save_secret", "retrieve_secret", "list_secrets"):
            with self.subTest(n=n):
                self.assertIn(n, names)

    def test_subset_size_typically_under_10(self):
                                                               
                                                               
        funcs = [_fn(n) for n in vtr.BASE_TOOLS] + [
            _fn(n) for tools in vtr.BUCKET_TOOLS.values()
            for n in tools
        ]
        out = vtr.filter_function_schemas(
            funcs, "find my passport",
        )
        self.assertLess(
            len(out), 14,
            msg=(
                "A simple file-search message should narrow the "
                f"catalog; got {len(out)} tools."
            ),
        )


class EmptyInputSafety(unittest.TestCase):
    def test_empty_message_still_returns_base_tools(self):
        names = vtr.select_tool_names_for_message("")
        for base in vtr.BASE_TOOLS:
            self.assertIn(base, names)

    def test_whitespace_message_still_returns_base_tools(self):
        names = vtr.select_tool_names_for_message("   ")
        for base in vtr.BASE_TOOLS:
            self.assertIn(base, names)

    def test_none_message_doesnt_crash(self):
        names = vtr.select_tool_names_for_message(None)                
        self.assertIsInstance(names, set)


class KillSwitch(unittest.TestCase):
    def test_disabled_returns_full_catalog(self):
        with mock.patch.dict(
            os.environ,
            {"VAULTAI_TOOL_ROUTER_ENABLED": "false"},
        ):
            names = vtr.select_tool_names_for_message("hello")
                                                          
                                     
        for tools in vtr.BUCKET_TOOLS.values():
            for t in tools:
                with self.subTest(t=t):
                    self.assertIn(t, names)


class AiStreamIntegrationGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_router_is_imported_and_applied_in_ai_stream(self):
        self.assertIn(
            "from vault_tool_router import filter_function_schemas",
            self._src,
        )
        self.assertIn(
            "filter_function_schemas(",
            self._src,
        )

    def test_router_failure_doesnt_break_the_path(self):
                                                             
                          
        idx = self._src.find(
            "from vault_tool_router import filter_function_schemas",
        )
        nearby = self._src[idx: idx + 800]
        self.assertIn("except Exception", nearby)

    def test_planning_call_has_max_tokens_cap(self):
                                                            
                                                                
        self.assertIn("max_tokens=_output_cap", self._src)
        self.assertIn("_create_kwargs", self._src)

    def test_synthesis_call_has_max_tokens_cap(self):
                                                          
                                              
        synth_idx = self._src.find(
            "followup = await stream_client.chat.completions.create",
        )
        self.assertGreater(synth_idx, -1)
        nearby = self._src[synth_idx: synth_idx + 400]
        self.assertIn("max_tokens=_output_cap", nearby)

    def test_output_cap_is_env_overridable(self):
                                                               
        self.assertIn("VAULTAI_CHAT_OUTPUT_TOKENS", self._src)
                                                          
        idx = self._src.find("VAULTAI_CHAT_OUTPUT_TOKENS")
        nearby = self._src[idx: idx + 200]
        self.assertIn('"500"', nearby)


if __name__ == "__main__":
    unittest.main()
