

from __future__ import annotations

import re
import string
import unittest
from unittest import mock

from username_policy import (
    UsernamePolicy,
    conservative_default as conservative_username_policy,
    generate_username,
    generate_username_options,
)


class AliasShapeTests(unittest.TestCase):
    def test_alias_is_lowercase_alphanumeric(self):
        policy = conservative_username_policy("Chase Bank")
        for _ in range(50):
            u = generate_username(policy)
            self.assertRegex(
                u, r"^[a-z0-9]+$",
                f"username {u!r} has non-alphanumeric characters",
            )

    def test_alias_length_inside_policy_window(self):
        policy = conservative_username_policy("Chase Bank")
        for _ in range(50):
            u = generate_username(policy)
            self.assertGreaterEqual(len(u), policy.min_length)
            self.assertLessEqual(len(u), policy.max_length)

    def test_alias_has_word_prefix_and_digit_tail(self):
                                                                   
                                    
        policy = conservative_username_policy("Revolut")
        for _ in range(50):
            u = generate_username(policy)
            self.assertRegex(u, r"^[a-z]+\d+$",
                             f"unexpected shape: {u!r}")

    def test_alias_does_not_contain_underscore_or_dot(self):
        policy = conservative_username_policy("Chase Bank")
        for _ in range(50):
            u = generate_username(policy)
            self.assertNotIn("_", u)
            self.assertNotIn(".", u)
            self.assertNotIn(" ", u)


class SafetyFloorTests(unittest.TestCase):


    def test_service_name_chase_never_in_alias(self):
        policy = conservative_username_policy("Chase")
        for _ in range(200):
            u = generate_username(policy, forbidden_substrings={"chase"})
            self.assertNotIn("chase", u)

    def test_service_name_revolut_never_in_alias(self):
        policy = conservative_username_policy("Revolut")
        for _ in range(200):
            u = generate_username(policy, forbidden_substrings={"revolut"})
            self.assertNotIn("revolut", u)

    def test_service_name_with_punctuation_normalised(self):
                                                                   
                                                                  
        policy = conservative_username_policy("Wells Fargo Online")
        for _ in range(200):
            u = generate_username(
                policy,
                forbidden_substrings={"Wells Fargo Online"},
            )
            self.assertNotIn("wellsfargoonline", u)
                                                                  
                                                                
            u2 = generate_username(
                policy,
                forbidden_substrings={"wellsfargo"},
            )
            self.assertNotIn("wellsfargo", u2)

    def test_vault_word_never_in_alias(self):
                                                                  
                  
        policy = conservative_username_policy("Anything")
        for _ in range(500):
            u = generate_username(policy)
            self.assertNotIn("vault", u)
            self.assertNotIn("vaultai", u)

    def test_user_identity_hint_never_in_alias(self):
                                                                  
                                                            
        policy = conservative_username_policy("Chase Bank")
        for _ in range(200):
            u = generate_username(
                policy,
                user_identity_hints=["Chosen", "chosen@goufer.com"],
            )
            self.assertNotIn("chosen", u)
                                                               
                                                    
    def test_short_identity_hints_dropped(self):
                                                               
                                                              
        policy = conservative_username_policy("X")
        u = generate_username(policy, user_identity_hints=["X"])
                                              
        self.assertGreater(len(u), 0)


class BadStyleNeverProducedTests(unittest.TestCase):
    def test_never_emits_servicename_prefix_pattern(self):
                                                                 
                                                                 
        SERVICES = ("Chase", "Revolut", "Wells Fargo", "Amex",
                    "Citibank", "Lloyds", "Monzo")
        for service in SERVICES:
            policy = conservative_username_policy(service)
            stripped = re.sub(r"[^a-z]+", "", service.lower())
            for _ in range(100):
                u = generate_username(
                    policy, forbidden_substrings={service},
                )
                                                  
                self.assertNotIn(stripped, u, f"{u!r} leaks {stripped!r}")

    def test_never_emits_dotted_or_underscored_handle(self):
                                                                   
                                                                   
        policy = conservative_username_policy("Chase")
        for _ in range(100):
            u = generate_username(policy, user_identity_hints=["Chosen"])
            self.assertNotIn(".", u)
            self.assertNotIn("_", u)


class ThreeOptionsTests(unittest.TestCase):
    def test_generate_username_options_returns_three(self):
        policy = conservative_username_policy("Chase Bank")
        opts = generate_username_options(
            policy, n=3, forbidden_substrings={"chase"},
        )
        self.assertEqual(len(opts), 3)

    def test_options_are_distinct(self):
        policy = conservative_username_policy("Chase Bank")
        opts = generate_username_options(
            policy, n=3, forbidden_substrings={"chase"},
        )
        self.assertEqual(len(set(opts)), 3)

    def test_options_all_pass_safety_floor(self):
        policy = conservative_username_policy("Wells Fargo")
        opts = generate_username_options(
            policy, n=3,
            forbidden_substrings={"wells", "wellsfargo"},
            user_identity_hints=["Chosen", "chosen@goufer.com"],
        )
        for u in opts:
            self.assertRegex(u, r"^[a-z0-9]+$")
            self.assertNotIn("wells", u)
            self.assertNotIn("wellsfargo", u)
            self.assertNotIn("vault", u)
            self.assertNotIn("chosen", u)


class HandlerSourceGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_generate_login_branch_uses_generate_username_options(self):
                                                                             
                                                                   
        branch = self._src.find('if intent == "generate_login":')
        self.assertGreater(branch, -1)
        slice_ = self._src[branch:branch + 15000]
        self.assertIn("generate_username_options(", slice_)
        self.assertIn("n=_options_count", slice_)
        self.assertIn("_options_count = 3 if _wants_options else 1", slice_)

    def test_options_mode_only_on_explicit_request(self):
                                                              
                                                         
        branch = self._src.find('if intent == "generate_login":')
        slice_ = self._src[branch:branch + 15000]
        self.assertIn("_wants_options", slice_)
                                                          
        for needle in (
            "options?",
            "alternatives?",
            "choices?",
            "different\\s+usernames?",
        ):
            self.assertIn(needle, slice_)

    def test_default_reply_shape_is_single_username(self):
                                                                   
                                                                 
        branch = self._src.find('if intent == "generate_login":')
        slice_ = self._src[branch:branch + 15000]
        self.assertIn(
            "I created a username and strong password ",
            slice_,
        )
        self.assertIn(
            "Say \\\"save it\\\" and I'll store it in your vault.",
            slice_,
        )

    def test_generate_login_branch_stashes_pending_login_draft(self):
        branch = self._src.find('if intent == "generate_login":')
        slice_ = self._src[branch:branch + 15000]
        self.assertIn('"pending_login_draft"', slice_)

    def test_save_now_phrasing_regex_present(self):
        branch = self._src.find('if intent == "generate_login":')
        slice_ = self._src[branch:branch + 15000]
        self.assertIn("save_now_phrasing", slice_)
                                                                  
        self.assertIn("save\\s+it\\s+now", slice_)
        self.assertIn("generate\\s+and\\s+save", slice_)

    def test_no_unconditional_save_in_default_path(self):
                                                                  
                                                               
        branch = self._src.find('if intent == "generate_login":')
        slice_ = self._src[branch:branch + 15000]
                                                        
        save_idxs = [
            m.start() for m in re.finditer(
                r"save_secret_tool\(", slice_,
            )
        ]
                                                                       
                                                                 
        for idx in save_idxs:
            window = slice_[max(0, idx - 2000):idx]
            self.assertIn(
                "if _save_now_phrasing:", window,
                f"save_secret_tool call at offset {idx} not gated "
                "by _save_now_phrasing",
            )

    def test_pending_login_draft_handler_present(self):
                                                           
                                                                
        memory_ok = self._src.find("memory_ok")
        self.assertGreater(memory_ok, -1)
        self.assertIn('memory.get("pending_login_draft")', self._src)

    def test_generated_login_create_is_not_general_chat(self):
        from vault_chat_general_router import route_general_chat
        from vault_chat_router import build_vault_chat_envelope

        message = "create me a login for GitHub"
        self.assertIsNone(route_general_chat(message, "en"))
        envelope = build_vault_chat_envelope(message)
        self.assertIsNotNone(envelope)
        self.assertEqual(
            envelope.get("intent"),
            "vault_generated_login_create_draft",
        )


class PickHandlerLogicTests(unittest.TestCase):


    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_numeric_pick_pattern_present(self):
                                                                
        self.assertIn(
            "(?:#|option\\s*)?",
            self._src,
        )

    def test_ordinal_words_mapped(self):
        for word in ("first", "second", "third"):
            self.assertIn(word, self._src)

    def test_save_signal_words_recognised(self):
                                           
        self.assertIn("save\\s+(it|that|this)", self._src)


class DefaultIsSingleUsernameTests(unittest.TestCase):


    def test_n_eq_1_returns_exactly_one_username(self):
        policy = conservative_username_policy("Union Bank")
        opts = generate_username_options(
            policy, n=1,
            forbidden_substrings={"union", "unionbank"},
            user_identity_hints=["Chosen"],
        )
        self.assertEqual(len(opts), 1)

    def test_n_eq_1_passes_safety_floor(self):
        policy = conservative_username_policy("Union Bank")
        for _ in range(50):
            opts = generate_username_options(
                policy, n=1,
                forbidden_substrings={"union", "unionbank"},
                user_identity_hints=["Chosen"],
            )
            self.assertEqual(len(opts), 1)
            u = opts[0]
                                                      
            self.assertNotIn("union", u)
            self.assertNotIn("unionbank", u)
            self.assertNotIn("vault", u)
            self.assertNotIn("chosen", u)
                                                          
            self.assertRegex(u, r"^[a-z]+\d+$")


class OptionsModeRegexTests(unittest.TestCase):


    @classmethod
    def setUpClass(cls):
        import re as _re
                                                                 
                                                         
        cls._opts_re = _re.compile(
            r"\b("
            r"options?|"
            r"alternatives?|"
            r"choices?|"
            r"variants?|"
            r"suggestions?|"
            r"different\s+usernames?|"
            r"a\s+few\s+usernames?|"
            r"some\s+usernames?|"
            r"three\s+usernames?"
            r")\b",
            _re.IGNORECASE,
        )

    def _wants_options(self, msg):
        return bool(self._opts_re.search(msg.lower()))

                                                                      
    def test_default_create_request_does_not_request_options(self):
        for msg in (
            "create me username and password for my Union Bank",
            "create username and password for my Chase Bank",
            "make me a login for Wells Fargo",
            "generate a strong password for Gmail",
            "create me a login for Revolut",
        ):
            with self.subTest(msg=msg):
                self.assertFalse(self._wants_options(msg))

                                                         
    def test_explicit_options_request_triggers_options(self):
        for msg in (
            "give me options for my Union Bank username",
            "show me three usernames for Gmail",
            "I want options for the Chase login",
            "give me some usernames for Revolut",
            "what alternatives do you have for Wells Fargo",
            "give me choices for my new login",
            "suggest a few usernames",
            "different usernames please",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(self._wants_options(msg))


class SaveItSignalTests(unittest.TestCase):


    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_save_it_pick_pattern_present(self):
                                                                
                                      
        self.assertIn(
            "save\\s+(it|that|this)",
            self._src,
        )

    def test_save_it_defaults_to_first_option(self):
                                                                  
                                                   
        self.assertIn(
            "if _pick_idx is None:\n                    _pick_idx = 1",
            self._src,
        )

    def test_save_it_triggers_save_secret_tool(self):
        handler = self._src.find('memory.get("pending_login_draft")')
        self.assertGreater(handler, -1)
        slice_ = self._src[handler:handler + 12000]
        self.assertIn("save_secret_tool(", slice_)
        self.assertIn('"service": _draft_service', slice_)


class UnionBankExampleEndToEndTests(unittest.TestCase):


    def test_union_bank_username_safety_floor(self):
                                                           
                                      
        policy = conservative_username_policy("Union Bank")
        opts = generate_username_options(
            policy, n=1,
            forbidden_substrings={"Union Bank"},
            user_identity_hints=["Chosen", "chosen@goufer.com"],
        )
        self.assertEqual(len(opts), 1)
        u = opts[0]
                                                   
        self.assertNotIn("union", u)
        self.assertNotIn("unionbank", u)
        self.assertNotIn("vault", u)
        self.assertNotIn("chosen", u)
        self.assertNotIn("banklogin", u)
        self.assertNotIn(".", u)
        self.assertNotIn("_", u)


if __name__ == "__main__":
    unittest.main()
