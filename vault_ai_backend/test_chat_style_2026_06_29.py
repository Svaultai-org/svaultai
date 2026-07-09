

from __future__ import annotations

import unittest

import vault_chat_style_sanitizer as vsz
import vault_chat_context_gate as vccg
import vault_active_context as vac


class TestStripMarkdown(unittest.TestCase):
    def test_strip_bold(self):
        out, slugs = vsz.sanitize_reply_style(
            "Here is **File Management** for your vault."
        )
        self.assertNotIn("**", out)
        self.assertIn("File Management", out)
        self.assertIn("stripped_bold", slugs)

    def test_strip_underscore_bold(self):
        out, slugs = vsz.sanitize_reply_style(
            "Use __File Management__ to organise."
        )
        self.assertNotIn("__", out)
        self.assertIn("File Management", out)

    def test_strip_italic(self):
        out, slugs = vsz.sanitize_reply_style(
            "Try the *quick search* feature."
        )
        self.assertNotIn("*", out)
        self.assertIn("quick search", out)

    def test_strip_heading(self):
        out, _ = vsz.sanitize_reply_style(
            "# Vault overview\nYou have 12 files."
        )
        self.assertNotIn("#", out)
        self.assertIn("Vault overview", out)

    def test_bold_with_emoji_kept_inside(self):
        out, _ = vsz.sanitize_reply_style(
            "Your **🔐 credentials** are saved."
        )
        self.assertNotIn("**", out)
        self.assertIn("🔐 credentials", out)


class TestStripStiffPreamble(unittest.TestCase):
    def test_im_designed_to(self):
        out, slugs = vsz.sanitize_reply_style(
            "I'm designed to help you manage your vault. "
            "You have 5 files."
        )
        self.assertNotIn("I'm designed to", out)
        self.assertNotIn("designed to help", out)
        self.assertIn("You have 5 files", out)
        self.assertTrue(
            any(s.startswith("dropped_") for s in slugs),
        )

    def test_i_am_designed_to(self):
        out, _ = vsz.sanitize_reply_style(
            "I am designed to help with files. "
            "Try a search."
        )
        self.assertNotIn("designed to", out)
        self.assertIn("Try a search", out)

    def test_as_an_ai_assistant(self):
        out, _ = vsz.sanitize_reply_style(
            "As an AI assistant, I can help you find things. "
            "Ask me anything."
        )
        self.assertNotIn("As an AI", out)
        self.assertIn("Ask me anything", out)

    def test_im_an_ai(self):
        out, _ = vsz.sanitize_reply_style(
            "I'm an AI built to help. Here's your vault."
        )
        self.assertNotIn("I'm an AI", out)
        self.assertIn("Here's your vault", out)

    def test_im_here_to_help_with(self):
        out, _ = vsz.sanitize_reply_style(
            "I'm here to help you with your vault. "
            "What do you need?"
        )
        self.assertNotIn("I'm here to help you with", out)
        self.assertIn("What do you need", out)

    def test_as_a_language_model(self):
        out, _ = vsz.sanitize_reply_style(
            "As a language model I can read files. Try one."
        )
        self.assertNotIn("As a language model", out)
        self.assertIn("Try one", out)

    def test_preamble_only_dropped_when_at_start(self):
                                                                  
                                                             
        out, _ = vsz.sanitize_reply_style(
            "Your vault has 5 files. I'm designed to help."
        )
                                         
        self.assertIn("Your vault has 5 files", out)


class TestCollapseNumberedList(unittest.TestCase):
    def test_short_items_become_comma_list(self):
        out, slugs = vsz.sanitize_reply_style(
            "Here is what I can do:\n"
            "1. Search files\n"
            "2. Read PDFs\n"
            "3. Check expiries\n"
        )
        self.assertIn("collapsed_list", slugs)
                        
        for item in ("Search files", "Read PDFs", "Check expiries"):
            self.assertIn(item, out)
                               
        self.assertNotIn("1.", out)
        self.assertNotIn("2.", out)
        self.assertNotIn("3.", out)


class TestDedupeIntro(unittest.TestCase):
    def test_near_duplicate_first_two_lines_deduped(self):
        out, slugs = vsz.sanitize_reply_style(
            "I can help you with a lot of vault tasks.\n"
            "I can help you with a lot of vault tasks today.\n"
            "Try asking about your IDs."
        )
                                           
        self.assertEqual(
            out.count("I can help you with a lot of vault tasks"), 1,
        )
        self.assertIn("Try asking about your IDs", out)
        self.assertIn("deduped_intro", slugs)


class TestEmojiCap(unittest.TestCase):
    def test_at_most_three_emojis(self):
        out, slugs = vsz.sanitize_reply_style(
            "Sure 🔐 — I can find 🪪 IDs 🔎 documents 📄 receipts 🧾 logins."
        )
                                              
        emoji_count = len(vsz._EMOJI_RE.findall(out))
        self.assertLessEqual(emoji_count, 3)
        self.assertIn("capped_emojis", slugs)

    def test_under_cap_untouched(self):
        out, slugs = vsz.sanitize_reply_style(
            "Sure — I can find 🪪 IDs and 🧾 receipts."
        )
        self.assertNotIn("capped_emojis", slugs)
        self.assertIn("🪪", out)
        self.assertIn("🧾", out)


class TestCombined(unittest.TestCase):
    def test_combined_pass(self):
        ugly = (
            "I'm designed to help. "
            "**File Management**\n"
            "1. Open files\n"
            "2. Compare names\n"
            "3. Organize\n"
            "Use 🔎 search 🔐 logins 🪪 IDs 📄 docs 🧾 forms."
        )
        out, slugs = vsz.sanitize_reply_style(ugly)
        self.assertNotIn("**", out)
        self.assertNotIn("designed to", out)
        self.assertNotIn("1.", out)
        emoji_count = len(vsz._EMOJI_RE.findall(out))
        self.assertLessEqual(emoji_count, 3)
                                              
        self.assertTrue(slugs)

    def test_idempotent_double_call(self):
        ugly = "I'm designed to help. **bold** 🔎 🔐 🪪 📄 🧾"
        once, _ = vsz.sanitize_reply_style(ugly)
        twice, _ = vsz.sanitize_reply_style(once)
        self.assertEqual(once, twice)

    def test_clean_text_is_noop(self):
        clean = (
            "Nice — I can help with that.\n\n"
            "Try asking about your IDs."
        )
        out, slugs = vsz.sanitize_reply_style(clean)
        self.assertEqual(out, clean)
        self.assertFalse(slugs)

    def test_empty_input(self):
        out, slugs = vsz.sanitize_reply_style("")
        self.assertEqual(out, "")
        self.assertFalse(slugs)
        out, slugs = vsz.sanitize_reply_style(None)
        self.assertEqual(out, "")
        self.assertFalse(slugs)


class TestContextHintCapability(unittest.TestCase):


    def test_capability_hint_returned_for_capability_intent(self):
        hint = vccg.context_hint_system_message(
            active_context=None,
            has_pending_draft=False,
            planner_intent="capability_question",
        )
        self.assertIsNotNone(hint)
                                                              
                        
        for fragment in (
            "find, understand, and organize",
            "your vault",
            "show me all ID photos",
            "find my Wells Fargo files",
            "create a login for Union Bank",
            "what documents are expiring?",
            "🔐",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, hint or "")
                                                                
                                                            
        example_block = (hint or "").split("EXAMPLE reply", 1)[-1]
        self.assertNotIn("**", example_block)
                                                                   
                                                    
        self.assertNotIn("I'm designed to", example_block)
        self.assertNotIn("As an AI", example_block)

    def test_active_context_wins_over_planner_intent(self):
                                                                
                                             
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
            has_pending_draft=False,
            planner_intent="capability_question",
        )
        self.assertIsNotNone(hint)
        self.assertIn("ACTIVE CONTEXT: the user just saw a "
                      "file_search_results card", hint or "")

    def test_identity_intent_also_gets_capability_hint(self):
        hint = vccg.context_hint_system_message(
            active_context=None,
            has_pending_draft=False,
            planner_intent="identity_question",
        )
        self.assertIsNotNone(hint)
        self.assertIn("your vault", hint or "")

    def test_capability_hint_carries_style_preamble(self):
                                                               
                                                    
        hint = vccg.context_hint_system_message(
            active_context=None,
            has_pending_draft=False,
            planner_intent="capability_question",
        )
        self.assertIn("Do NOT use markdown asterisks", hint or "")
        self.assertIn("Do NOT use numbered corporate lists", hint or "")
        self.assertIn("Do NOT say", hint or "")


class TestContextHintFileSearchResults(unittest.TestCase):


    def test_hint_mentions_all_listed_file_actions(self):
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
            has_pending_draft=False,
        )
        for action in (
            "open one of the files",
            "compare names",
            "find more files for the same person",
            "extract dates",
            "organize",
        ):
            with self.subTest(action=action):
                self.assertIn(action, hint or "")

    def test_hint_carries_example_user_prompts(self):
                                                                 
                                                                   
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
            has_pending_draft=False,
        )
        for prompt in (
            "open the HEIC one",
            "find all IDs for Louis",
            "show documents with expiry dates",
            "compare these names",
        ):
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, hint or "")

    def test_hint_forbids_credential_draft_mention(self):
                                                               
                           
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
            has_pending_draft=False,
        )
        self.assertIn("DO NOT mention a pending login draft", hint or "")

    def test_hint_has_warm_opener_example(self):
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
            has_pending_draft=False,
        )
                                                             
                    
        self.assertIn("Nice —", hint or "")


class TestSanitizerPrivacy(unittest.TestCase):
    def test_slugs_are_closed_set_strings(self):
        out, slugs = vsz.sanitize_reply_style(
            "**Bold** I'm designed to help. 🔎 🔐 🪪 📄 🧾\n"
            "1. foo\n2. bar"
        )
                                                         
        for slug in slugs:
            self.assertNotIn(" ", slug)
            self.assertTrue(slug.replace("_", "").isalnum())

    def test_sanitizer_does_not_strip_user_content(self):
                                                                  
                                
        out, _ = vsz.sanitize_reply_style(
            "Your vault has these IDs: kendra_chosen.heic, louis_lodato.jpg"
        )
        self.assertIn("kendra_chosen.heic", out)
        self.assertIn("louis_lodato.jpg", out)


if __name__ == "__main__":                    
    unittest.main()
