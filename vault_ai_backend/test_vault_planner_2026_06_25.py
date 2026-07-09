

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

import vault_planner as vp


class PlannerDecisionShape(unittest.TestCase):
    def test_capability_question_decision_can_skip_tools(self):
        d = vp.PlannerDecision(
            intent="capability_question",
            needs_vault_search=False,
            needs_file_reading=False,
            needs_ocr_image_pdf_reading=False,
            needs_credential_action=False,
            is_simple_capability_question=True,
            needs_stronger_model=False,
            planned_tools=(),
            reasoning="capability q",
            confidence=0.9,
        )
        self.assertTrue(d.can_skip_tools())

    def test_document_search_decision_cannot_skip_tools(self):
        d = vp.PlannerDecision(
            intent="document_search",
            needs_vault_search=True,
            needs_file_reading=True,
            needs_ocr_image_pdf_reading=True,
            needs_credential_action=False,
            is_simple_capability_question=False,
            needs_stronger_model=False,
            planned_tools=("search_extracted_text", "read_image_with_vision"),
            reasoning="user wants an ID document",
            confidence=0.95,
        )
        self.assertFalse(d.can_skip_tools())

    def test_simple_flag_alone_isnt_enough_when_tools_planned(self):
                                                                
                                                                 
        d = vp.PlannerDecision(
            intent="capability_question",
            needs_vault_search=False,
            needs_file_reading=False,
            needs_ocr_image_pdf_reading=False,
            needs_credential_action=False,
            is_simple_capability_question=True,
            needs_stronger_model=False,
            planned_tools=("get_vault_status",),
            reasoning="",
            confidence=0.5,
        )
        self.assertFalse(d.can_skip_tools())


class ToolNameFilter(unittest.TestCase):
    def test_valid_tool_names_pass_through(self):
        out = vp._validate_tools([
            "search_extracted_text",
            "read_file_text",
            "list_vault_files",
        ])
        self.assertEqual(out, (
            "search_extracted_text",
            "read_file_text",
            "list_vault_files",
        ))

    def test_invented_tool_names_are_dropped(self):
        out = vp._validate_tools([
            "search_extracted_text",
            "this_tool_does_not_exist",
            "exfiltrate_vault",
        ])
        self.assertEqual(out, ("search_extracted_text",))

    def test_caps_at_six_tools(self):
        many = ["list_vault_files"] * 10
        out = vp._validate_tools(many)
        self.assertLessEqual(len(out), 6)

    def test_dedupes_repeated_names(self):
        out = vp._validate_tools(["list_vault_files"] * 3)
        self.assertEqual(out, ("list_vault_files",))

    def test_non_list_input_returns_empty(self):
        self.assertEqual(vp._validate_tools(None), ())
        self.assertEqual(vp._validate_tools("string"), ())
        self.assertEqual(vp._validate_tools({"a": 1}), ())


class CoerceDecisionTests(unittest.TestCase):
    def test_well_formed_payload_becomes_decision(self):
        payload = {
            "intent": "document_search",
            "needs_vault_search": True,
            "needs_file_reading": True,
            "needs_ocr_image_pdf_reading": True,
            "needs_credential_action": False,
            "is_simple_capability_question": False,
            "needs_stronger_model": False,
            "planned_tools": [
                "search_extracted_text",
                "find_files_for_entity",
                "read_image_with_vision",
            ],
            "reasoning": "find ID for X",
            "confidence": 0.93,
        }
        d = vp._coerce_decision(payload, source="planner")
        self.assertEqual(d.intent, "document_search")
        self.assertEqual(d.planned_tools, (
            "search_extracted_text",
            "find_files_for_entity",
            "read_image_with_vision",
        ))
        self.assertEqual(d.confidence, 0.93)
        self.assertEqual(d.source, "planner")

    def test_unknown_intent_collapses_to_unknown(self):
        d = vp._coerce_decision(
            {
                "intent": "make_pizza",
                "needs_vault_search": False,
                "needs_file_reading": False,
                "needs_ocr_image_pdf_reading": False,
                "needs_credential_action": False,
                "is_simple_capability_question": False,
                "needs_stronger_model": False,
                "planned_tools": [],
                "reasoning": "x",
                "confidence": 0.1,
            },
            source="planner",
        )
        self.assertEqual(d.intent, "unknown")

    def test_simple_flag_inferred_from_intent_for_safety(self):
                                                               
                                                                
        d = vp._coerce_decision(
            {
                "intent": "capability_question",
                "needs_vault_search": False,
                "needs_file_reading": False,
                "needs_ocr_image_pdf_reading": False,
                "needs_credential_action": False,
                "is_simple_capability_question": False,
                "needs_stronger_model": False,
                "planned_tools": [],
                "reasoning": "",
                "confidence": 0.7,
            },
            source="planner",
        )
        self.assertTrue(d.is_simple_capability_question)
        self.assertTrue(d.can_skip_tools())

    def test_confidence_clamped_to_unit_interval(self):
        d = vp._coerce_decision(
            {
                "intent": "casual_chat",
                "needs_vault_search": False,
                "needs_file_reading": False,
                "needs_ocr_image_pdf_reading": False,
                "needs_credential_action": False,
                "is_simple_capability_question": True,
                "needs_stronger_model": False,
                "planned_tools": [],
                "reasoning": "",
                "confidence": 5.0,
            },
            source="planner",
        )
        self.assertEqual(d.confidence, 1.0)


class ConservativeFallbackTests(unittest.TestCase):
    def test_fallback_keeps_chat_path_alive_with_safe_tools(self):
        d = vp._conservative_fallback("api_error")
        self.assertEqual(d.source, "fallback")
                                                             
                                                               
        self.assertFalse(d.can_skip_tools())
                                             
        self.assertIn("get_vault_status", d.planned_tools)
        self.assertIn("search_extracted_text", d.planned_tools)


def _run(coro):
                                                            
                                                                
    return asyncio.run(coro)


class PlanUserMessageTests(unittest.TestCase):
    def test_empty_message_returns_fallback(self):
        d = _run(vp.plan_user_message(message="   "))
        self.assertEqual(d.source, "fallback")
        self.assertEqual(d.intent, "unknown")

    def test_planner_disabled_flag_returns_fallback(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_PLANNER_ENABLED": "false"},
        ):
            d = _run(vp.plan_user_message(message="anything"))
        self.assertEqual(d.source, "fallback")
        self.assertEqual(d.reasoning, "fallback: planner_disabled")

    def test_no_api_key_returns_fallback(self):
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": ""},
        ):
            d = _run(vp.plan_user_message(message="hi there"))
        self.assertEqual(d.source, "fallback")

    def test_capability_question_happy_path(self):
        fake_payload = {
            "intent": "capability_question",
            "needs_vault_search": False,
            "needs_file_reading": False,
            "needs_ocr_image_pdf_reading": False,
            "needs_credential_action": False,
            "is_simple_capability_question": True,
            "needs_stronger_model": False,
            "planned_tools": [],
            "reasoning": "what can you do",
            "confidence": 0.95,
        }
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message.content = json.dumps(fake_payload)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            return_value=fake_resp,
        )
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"},
        ), mock.patch(
            "openai.AsyncOpenAI", return_value=fake_client,
        ):
            d = _run(vp.plan_user_message(message="what can you do?"))
        self.assertEqual(d.source, "planner")
        self.assertEqual(d.intent, "capability_question")
        self.assertTrue(d.can_skip_tools())

    def test_document_search_happy_path(self):
        fake_payload = {
            "intent": "document_search",
            "needs_vault_search": True,
            "needs_file_reading": True,
            "needs_ocr_image_pdf_reading": True,
            "needs_credential_action": False,
            "is_simple_capability_question": False,
            "needs_stronger_model": False,
            "planned_tools": [
                "search_extracted_text",
                "find_files_for_entity",
                "read_image_with_vision",
            ],
            "reasoning": "find ID for Louis",
            "confidence": 0.92,
        }
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message.content = json.dumps(fake_payload)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            return_value=fake_resp,
        )
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"},
        ), mock.patch(
            "openai.AsyncOpenAI", return_value=fake_client,
        ):
            d = _run(vp.plan_user_message(
                message="Find a photo ID for Louis Iodato",
            ))
        self.assertEqual(d.intent, "document_search")
        self.assertIn("search_extracted_text", d.planned_tools)
        self.assertIn("read_image_with_vision", d.planned_tools)
        self.assertFalse(d.can_skip_tools())

    def test_credential_creation_draft_happy_path(self):
        fake_payload = {
            "intent": "credential_creation_draft",
            "needs_vault_search": False,
            "needs_file_reading": False,
            "needs_ocr_image_pdf_reading": False,
            "needs_credential_action": True,
            "is_simple_capability_question": False,
            "needs_stronger_model": False,
            "planned_tools": ["get_credential_metadata"],
            "reasoning": "create login for Union Bank",
            "confidence": 0.9,
        }
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message.content = json.dumps(fake_payload)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            return_value=fake_resp,
        )
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"},
        ), mock.patch(
            "openai.AsyncOpenAI", return_value=fake_client,
        ):
            d = _run(vp.plan_user_message(
                message="Create username and password for Union Bank",
            ))
        self.assertEqual(d.intent, "credential_creation_draft")
        self.assertTrue(d.needs_credential_action)
        self.assertIn("get_credential_metadata", d.planned_tools)

    def test_malformed_json_falls_back(self):
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message.content = "not valid json {{{"
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            return_value=fake_resp,
        )
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"},
        ), mock.patch(
            "openai.AsyncOpenAI", return_value=fake_client,
        ):
            d = _run(vp.plan_user_message(message="hello"))
        self.assertEqual(d.source, "fallback")
        self.assertIn("malformed_json", d.reasoning)

    def test_api_error_falls_back(self):
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            side_effect=RuntimeError("network down"),
        )
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"},
        ), mock.patch(
            "openai.AsyncOpenAI", return_value=fake_client,
        ):
            d = _run(vp.plan_user_message(message="anything"))
        self.assertEqual(d.source, "fallback")
        self.assertIn("api_error", d.reasoning)

    def test_planner_drops_hallucinated_tools(self):
                                                              
                                                                
        fake_payload = {
            "intent": "document_search",
            "needs_vault_search": True,
            "needs_file_reading": False,
            "needs_ocr_image_pdf_reading": False,
            "needs_credential_action": False,
            "is_simple_capability_question": False,
            "needs_stronger_model": False,
            "planned_tools": [
                "search_extracted_text",
                "tool_that_does_not_exist",
                "evil_exfiltration_tool",
            ],
            "reasoning": "",
            "confidence": 0.5,
        }
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message.content = json.dumps(fake_payload)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = mock.AsyncMock(
            return_value=fake_resp,
        )
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"},
        ), mock.patch(
            "openai.AsyncOpenAI", return_value=fake_client,
        ):
            d = _run(vp.plan_user_message(message="find x"))
        self.assertEqual(d.planned_tools, ("search_extracted_text",))


class AiStreamIntegrationGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_planner_is_invoked_before_tool_partitioning(self):
                                                               
                                                      
        planner_idx = self._src.find(
            "from vault_planner import plan_user_message",
        )
        router_idx = self._src.find(
            "from vault_tool_router import filter_function_schemas",
        )
        self.assertGreater(planner_idx, -1)
        self.assertGreater(router_idx, -1)
        self.assertLess(planner_idx, router_idx)

    def test_can_skip_tools_path_omits_tools_and_tool_choice(self):
                                                           
                                                                 
        self.assertIn("_skip_tools = True", self._src)
        self.assertIn(
            'if not _skip_tools and allowed_tools:',
            self._src,
        )
        self.assertIn('"tools"', self._src)
        self.assertIn('"tool_choice"', self._src)

    def test_planner_drives_tool_surface_when_confident(self):
                                                              
                                                  
        self.assertIn("_planner_tool_names = set(", self._src)
        self.assertIn(
            'fn.get("function", {}).get("name")',
            self._src,
        )

    def test_planner_failure_falls_through_to_regex_router(self):
                                                             
                                                             
        self.assertIn("[CHAT-TRACE] planner failed", self._src)
                                                 
        self.assertIn(
            "from vault_tool_router import filter_function_schemas",
            self._src,
        )

    def test_logger_emits_planner_intent_for_observability(self):
                                                            
                                                                 
        self.assertIn("planner_intent=", self._src)
        self.assertIn("planner_used=", self._src)
        self.assertIn("skip_tools=", self._src)


if __name__ == "__main__":
    unittest.main()
