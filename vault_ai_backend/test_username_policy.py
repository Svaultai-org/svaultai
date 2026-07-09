

from __future__ import annotations

import asyncio
import re
import string
import unittest
from unittest.mock import AsyncMock

from username_policy import (
    ALLOWED_CHARS_EMAIL,
    ALLOWED_CHARS_LETTERS_NUMBERS,
    ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE,
    CONFIDENCE_INFERRED,
    CONFIDENCE_OFFICIAL,
    CONFIDENCE_UNKNOWN,
    PolicyCache,
    UsernamePolicy,
    conservative_default,
    format_policy_note,
    generate_username,
    infer_policy_via_llm,
    resolve_username_policy,
    tighten_policy,
)


def _run(coro):


    return asyncio.run(coro)


class GenerateUsernameTests(unittest.TestCase):
    def test_letters_numbers_policy_produces_no_underscore(self):
                                                                    
                                                                 
        policy = UsernamePolicy(
            service="Capital One",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS,
            min_length=8,
            max_length=16,
            disallow_symbols=True,
            disallow_underscore=True,
        )
                                                                    
                                                                    
        for _ in range(200):
            username = generate_username(policy)
            self.assertNotIn("_", username, msg=f"got {username!r}")
            self.assertRegex(username, r"^[a-z0-9]+$")
            self.assertGreaterEqual(len(username), policy.min_length)
            self.assertLessEqual(len(username), policy.max_length)

    def test_unknown_service_uses_conservative_default(self):
        policy = conservative_default("Some Random Bank")
                                                                    
                                            
        for _ in range(50):
            u = generate_username(policy)
            self.assertNotIn("_", u)
            self.assertRegex(u, r"^[a-z0-9]+$")
            self.assertNotIn(" ", u)

    def test_underscore_allowed_policy_allows_underscore(self):
                                                                   
                                                                
        policy = UsernamePolicy(
            service="Some Forum",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE,
            min_length=10,
            max_length=14,
            disallow_symbols=True,
            disallow_underscore=False,
        )
                                                                     
                                                 
        for _ in range(100):
            u = generate_username(policy)
                                            
            self.assertRegex(u, r"^[a-z0-9_]+$")

    def test_service_name_with_spaces_does_not_leak_into_username(self):
                                                            
                                                                  
        policy = conservative_default("Capital One")
        for _ in range(50):
            u = generate_username(
                policy,
                forbidden_substrings={"capitalone", "capital"},
            )
                                                                 
                                                                   
            self.assertNotIn(" ", u)
                                                                  
                                                             
            self.assertNotIn("capitalone", u)
            self.assertNotIn("capital", u)

    def test_email_required_policy_raises_instead_of_generating(self):
        policy = UsernamePolicy(
            service="Some Email-Login Service",
            allowed_chars=ALLOWED_CHARS_EMAIL,
            email_required=True,
        )
                                                                 
                                                      
        with self.assertRaises(ValueError):
            generate_username(policy)


class TightenPolicyTests(unittest.TestCase):
    def test_tighten_removes_underscores_and_symbols(self):
        loose = UsernamePolicy(
            service="X",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE,
            min_length=4,
            max_length=24,
            disallow_symbols=False,
            disallow_underscore=False,
        )
        tight = tighten_policy(loose)
        self.assertTrue(tight.disallow_underscore)
        self.assertTrue(tight.disallow_symbols)
        self.assertEqual(tight.allowed_chars, ALLOWED_CHARS_LETTERS_NUMBERS)
                                    
        self.assertGreaterEqual(tight.min_length, 8)
        self.assertLessEqual(tight.max_length, 12)
        self.assertEqual(tight.confidence, CONFIDENCE_INFERRED)

    def test_tighten_a_strict_policy_still_narrows_length(self):
                                                                      
                                                             
        policy = UsernamePolicy(
            service="X",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS,
            min_length=4,
            max_length=32,
            disallow_symbols=True,
            disallow_underscore=True,
        )
        tight = tighten_policy(policy)
        self.assertGreaterEqual(tight.min_length, 8)
        self.assertLessEqual(tight.max_length, 12)

    def test_tighten_email_required_is_noop(self):
                                                                   
                                                                    
        policy = UsernamePolicy(
            service="X",
            allowed_chars=ALLOWED_CHARS_EMAIL,
            email_required=True,
        )
        self.assertEqual(tighten_policy(policy), policy)


class ResolveUsernamePolicyCascadeTests(unittest.TestCase):
    def test_cache_hit_short_circuits(self):
        cached = UsernamePolicy(
            service="Capital One",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS,
            min_length=8,
            max_length=16,
            disallow_symbols=True,
            disallow_underscore=True,
            confidence=CONFIDENCE_OFFICIAL,
        )

        class FakeCache:
            def get(self_inner, service):
                return cached if service == "Capital One" else None

            def put(self_inner, _policy):
                raise AssertionError("cache.put must not run on cache hit")

                                                              
        fake_openai = AsyncMock()
        result = _run(
            resolve_username_policy(
                "Capital One", cache=FakeCache(), openai_client=fake_openai,
            )
        )
        self.assertIs(result, cached)
        fake_openai.chat.completions.create.assert_not_called()

    def test_no_client_falls_back_to_conservative_default(self):
                                                                  
                                                                
        captured = {}

        class FakeCache:
            def get(self_inner, _service):
                return None

            def put(self_inner, policy):
                captured["policy"] = policy

        result = _run(
            resolve_username_policy(
                "Mystery Bank", cache=FakeCache(), openai_client=None,
            )
        )
        self.assertEqual(result.confidence, CONFIDENCE_UNKNOWN)
        self.assertEqual(result.allowed_chars, ALLOWED_CHARS_LETTERS_NUMBERS)
        self.assertTrue(result.disallow_underscore)
        self.assertTrue(result.disallow_symbols)
                                                                    
        self.assertIn("policy", captured)
        self.assertEqual(captured["policy"].confidence, CONFIDENCE_UNKNOWN)


class LlmInferenceSecretsSafetyTests(unittest.TestCase):


    def test_llm_prompt_contains_only_the_service_name(self):
        captured_prompt = {}

        class FakeResponse:
            class _Choice:
                class _Message:
                    content = (
                        '{"allowed_chars":"letters_numbers",'
                        '"min_length":8,"max_length":16,'
                        '"disallow_symbols":true,"disallow_underscore":true,'
                        '"email_required":false,'
                        '"source_url":null,"confidence":"unknown"}'
                    )
                message = _Message()
            choices = [_Choice()]

        async def fake_create(**kwargs):
            captured_prompt["messages"] = kwargs.get("messages")
            return FakeResponse()

        class FakeOpenAI:
            class chat:
                class completions:
                    create = staticmethod(fake_create)

                                                                     
        SERVICE = "BNB Bank"
        FORBIDDEN = [
            "PIN=981273",
            "password=Hunter2!@#",
            "session_jwt=ey.fake.token",
            "encrypted_blob=ZmFrZWJsb2I=",
            "user_id=descope_user_abc",
        ]

        result = _run(infer_policy_via_llm(SERVICE, FakeOpenAI()))
        self.assertIsNotNone(result)
        messages = captured_prompt["messages"]
        joined = " ".join(m.get("content", "") for m in messages)
                                                              
        self.assertIn(SERVICE, joined)
        for forbidden in FORBIDDEN:
            self.assertNotIn(forbidden, joined)
                                                                  
        self.assertNotRegex(joined, r"(?i)(pin|password|jwt|token)\s*=")


class FormatPolicyNoteTests(unittest.TestCase):
    def test_official_with_strict_chars_says_letters_and_numbers(self):
        policy = UsernamePolicy(
            service="Capital One",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS,
            disallow_symbols=True,
            disallow_underscore=True,
            confidence=CONFIDENCE_OFFICIAL,
            source_url="https://example.invalid/rules",
        )
        note = format_policy_note(policy)
        self.assertIn("Capital One", note)
        self.assertIn("letters and numbers", note.lower())

    def test_unknown_admits_uncertainty(self):
        policy = conservative_default("Mystery Bank")
        note = format_policy_note(policy)
                                                            
        self.assertIn("conservative", note.lower())
        self.assertIn("Mystery Bank", note)


class RepairFlowSemanticsTests(unittest.TestCase):


    def test_tighten_then_regenerate_username_is_pure_username_op(self):
                                                                      
                                                                 
        loose = UsernamePolicy(
            service="Capital One",
            allowed_chars=ALLOWED_CHARS_LETTERS_NUMBERS_UNDERSCORE,
            disallow_underscore=False,
            disallow_symbols=False,
            min_length=4,
            max_length=24,
        )
        tight = tighten_policy(loose)
        for _ in range(50):
            username = generate_username(tight)
            self.assertNotIn("_", username)
            self.assertRegex(username, r"^[a-z0-9]+$")


if __name__ == "__main__":
    unittest.main()
