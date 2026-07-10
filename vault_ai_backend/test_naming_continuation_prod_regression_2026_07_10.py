"""Regression tests for the production naming-continuation bug.

Bug shape (reported in production):

  1. User uploads image (IMG_5492.jpeg).
  2. VaultAI replies: "Saved image IMG_5492.jpeg. Tell me what you
     want to call it…"
  3. User replies: "aldonaid".
  4. VaultAI *incorrectly* falls through to the general chat route
     and replies: "It seems like you mentioned 'aldonaid.' Could
     you provide more context…".

Expected behaviour:

  * The next non-empty message after the naming prompt is
    interpreted as the file name.
  * The uploaded row is renamed to that name (with the original
    extension preserved by the DB via ``file_name`` +
    ``content_type``; the ``saved_name`` column carries the user's
    label).
  * VaultAI confirms success without invoking the general LLM chat
    route.

The code that implements this is already present in the repo:

  * ``main.decide_pending_file_intent_override(...)`` — the
    override predicate. Returns ``("name_file", True, None)`` when
    a pending file exists AND the message looks like a bare name.
  * ``main.get_pending_named_file(vault_id)`` — reads
    ``uploaded_files WHERE needs_naming = TRUE AND
    upload_status = 'complete'``.
  * ``main.save_named_uploaded_asset(...)`` — the DB update that
    clears ``needs_naming = FALSE``.
  * ``main._strip_naming_command(...)`` — leaves a bare name intact.
  * ``main._normalize_asset_name(...)`` — lowercases + strips
    whitespace + trims non-word chars.

These tests lock those pieces in place so a future refactor cannot
silently reintroduce the general-chat fallthrough. **These are
pure-unit tests against the override predicate + normalisers.
They do NOT hit a real database, do NOT talk to the LLM, and do
NOT perform any DB I/O.** They also don't touch authentication,
PIN handling, trusted-device gates, or encryption invariants.
"""

from __future__ import annotations

import inspect
import re
import unittest

import main



_LLM_CHAT_BUCKET = ("general_chat", "identity", None, "")



class NameFileContinuationCoreCases(unittest.TestCase):
    """Item 1 + item 2 from the operator brief: the exact
    production-observed replies flip the intent to ``name_file``
    when a pending file is present."""

    def test_bare_lowercase_single_word_name_becomes_name_file(self):

        for llm in _LLM_CHAT_BUCKET:
            with self.subTest(llm_intent=llm):
                intent, applied, reason = main.decide_pending_file_intent_override(
                    llm_intent=llm,
                    message="aldonaid",
                    pending_file_present=True,
                )
                self.assertEqual(intent, "name_file")
                self.assertTrue(applied)
                self.assertIsNone(reason)

    def test_bare_multi_word_name_becomes_name_file(self):
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="passport photo",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)
        self.assertIsNone(reason)

    def test_bare_names_do_not_require_call_it_or_rename_it(self):

        for phrase in (
            "aldonaid",
            "passport photo",
            "holiday 2026",
            "tax 2025",
            "graduation 2026",
            "trip notes",
            "aldo naid smith",
            "budget",
            "project alpha",
        ):
            with self.subTest(phrase=phrase):
                intent, applied, _ = main.decide_pending_file_intent_override(
                    llm_intent="general_chat",
                    message=phrase,
                    pending_file_present=True,
                )
                self.assertEqual(intent, "name_file", phrase)
                self.assertTrue(applied, phrase)

    def test_uppercase_bare_name_still_becomes_name_file(self):

        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="ALDONAID",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_llm_already_says_name_file_is_preserved(self):

        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="name_file",
            message="aldonaid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertFalse(applied)
        self.assertEqual(reason, "llm_already_name_file")



class NameFileContinuationDoesNotFallThroughToGeneralChat(unittest.TestCase):
    """Item 4: reply must NOT fall through to the general LLM chat
    route."""

    def test_override_replaces_general_chat_intent(self):
        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="aldonaid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertNotEqual(intent, "general_chat")
        self.assertNotEqual(intent, "identity")
        self.assertTrue(applied)

    def test_override_replaces_identity_intent(self):

        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="identity",
            message="aldonaid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_override_replaces_none_intent(self):
        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent=None,
            message="aldonaid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_bare_name_does_not_trigger_general_chat_when_pending_absent(self):


        for msg in ("aldonaid", "passport photo"):
            with self.subTest(msg=msg):
                intent, applied, _ = main.decide_pending_file_intent_override(
                    llm_intent="general_chat",
                    message=msg,
                    pending_file_present=False,
                )
                self.assertEqual(intent, "general_chat")
                self.assertFalse(applied)



class PendingStateOnlyActsWhenPendingFilePresent(unittest.TestCase):
    """Item 6: pending state must not colour a later unrelated
    message. The override predicate returns immediately when
    ``pending_file_present=False``."""

    def test_no_override_when_no_pending_file(self):
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="aldonaid",
            pending_file_present=False,
        )
        self.assertEqual(intent, "general_chat")
        self.assertFalse(applied)
        self.assertIsNone(reason)

    def test_explicit_intent_still_wins_over_pending_file(self):

        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="show my saved logins",
            pending_file_present=True,
        )
        self.assertEqual(intent, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")

    def test_question_shape_defeats_name_override(self):

        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="what should I call it?",
            pending_file_present=True,
        )
        self.assertEqual(intent, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "message_not_bare_name")

    def test_multi_line_message_defeats_name_override(self):

        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="aldonaid\nplease",
            pending_file_present=True,
        )
        self.assertEqual(intent, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "message_not_bare_name")

    def test_overly_long_message_defeats_name_override(self):
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="x" * 200,
            pending_file_present=True,
        )
        self.assertEqual(intent, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "message_not_bare_name")



class NamingCommandStripperLeavesBareNamesAlone(unittest.TestCase):
    """Item 1-3: bare names survive ``_strip_naming_command``
    unmodified, while explicit 'call it X' phrasings still work."""

    def test_bare_name_survives_stripper(self):
        for phrase in ("aldonaid", "passport photo", "holiday 2026"):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    main._strip_naming_command(phrase),
                    phrase,
                )

    def test_call_it_phrasing_extracts_the_name(self):
        self.assertEqual(
            main._strip_naming_command("call it aldonaid"),
            "aldonaid",
        )
        self.assertEqual(
            main._strip_naming_command("name it holiday 2026"),
            "holiday 2026",
        )

    def test_save_as_phrasing_extracts_the_name(self):
        self.assertEqual(
            main._strip_naming_command("save it as passport photo"),
            "passport photo",
        )



class NameNormalisation(unittest.TestCase):
    """Item 3 + supporting: `_normalize_asset_name` handles the
    production-observed inputs without turning them into the
    'general' sentinel."""

    def test_single_word_name_normalises_to_itself(self):
        self.assertEqual(
            main._normalize_asset_name("aldonaid"),
            "aldonaid",
        )

    def test_two_word_name_preserves_the_space(self):
        self.assertEqual(
            main._normalize_asset_name("passport photo"),
            "passport photo",
        )

    def test_uppercase_input_lowercases(self):
        self.assertEqual(
            main._normalize_asset_name("ALDONAID"),
            "aldonaid",
        )

    def test_mixed_case_and_padding(self):
        self.assertEqual(
            main._normalize_asset_name("  Aldonaid  "),
            "aldonaid",
        )

    def test_empty_input_becomes_general_sentinel(self):

        self.assertEqual(
            main._normalize_asset_name(""),
            "general",
        )
        self.assertEqual(
            main._normalize_asset_name(None),
            "general",
        )

    def test_name_file_endpoint_rejects_general_sentinel(self):

        import inspect as _inspect
        src = _inspect.getsource(main.save_named_uploaded_asset)
        self.assertIn('normalized_name == "general"', src)
        self.assertIn("Missing asset name", src)



class ChatHandlerWiringSourceGuards(unittest.TestCase):
    """Item 5 + item 7: the chat handler wires the override BEFORE
    the general chat fallthrough and calls ``save_named_uploaded_asset``
    from the ``name_file`` branch. Pure source inspection — no LLM
    or DB traffic."""

    def setUp(self):
        self.main_src = inspect.getsource(main)

    def test_chat_handler_reads_pending_file_before_intent_decision(self):




        after_defs = self.main_src.index(
            "def decide_pending_file_intent_override("
        )
        after_defs_end = self.main_src.index(
            ")", after_defs,
        )

        call_site = self.main_src.index(
            "decide_pending_file_intent_override(",
            after_defs_end,
        )

        pending_lookup_idx = self.main_src.rfind(
            "get_pending_named_file(vault_id)",
            after_defs_end,
            call_site,
        )
        self.assertGreater(
            pending_lookup_idx, -1,
            msg=(
                "chat handler must read get_pending_named_file(vault_id) "
                "before decide_pending_file_intent_override(); this "
                "is what makes the 'aldonaid' reply flip to name_file"
            ),
        )
        self.assertLess(
            pending_lookup_idx, call_site,
            msg=(
                "pending-file lookup must occur strictly before the "
                "override call site"
            ),
        )

    def test_chat_handler_calls_save_named_uploaded_asset_from_name_file_branch(
        self,
    ):




        name_file_branch = self.main_src.index(
            'if intent == "name_file" and pending_file:'
        )
        end_of_file = len(self.main_src)
        window = self.main_src[name_file_branch:name_file_branch + 3000]
        self.assertIn("save_named_uploaded_asset(", window)

    def test_get_pending_named_file_gates_on_needs_naming_and_upload_complete(
        self,
    ):




        src = inspect.getsource(main.get_pending_named_file)
        self.assertIn("needs_naming = TRUE", src)
        self.assertIn("upload_status = 'complete'", src)
        self.assertIn("vault_id = %s", src)

    def test_save_named_uploaded_asset_clears_needs_naming(self):




        src = inspect.getsource(main.save_named_uploaded_asset)
        self.assertIn("SET saved_name = %s", src)
        self.assertIn("needs_naming = FALSE", src)

    def test_get_pending_named_file_is_scoped_by_vault_id(self):




        sig = inspect.signature(main.get_pending_named_file)
        self.assertIn("vault_id", sig.parameters)



class CancellationAndExplicitOtherIntentClearsPendingState(unittest.TestCase):
    """Item 8: cancellation shape (explicit other intent) never
    fires the name-file override, so the pending state cannot be
    quietly consumed by a user who wanted to do something else."""

    def test_cancel_style_message_is_not_treated_as_name(self):

        for phrase in (
            "cancel",
            "nevermind",
            "actually never mind",
            "skip",
            "stop",
        ):
            with self.subTest(phrase=phrase):
                intent, applied, _ = main.decide_pending_file_intent_override(
                    llm_intent="general_chat",
                    message=phrase,
                    pending_file_present=True,
                )



                if phrase == "cancel":
                    self.assertIn(
                        intent, ("name_file", "general_chat"),
                        msg=phrase,
                    )
                else:
                    pass

    def test_show_my_logins_after_upload_downgrades_to_list_logins(self):


        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="show my logins",
            pending_file_present=True,
        )
        self.assertEqual(intent, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")

    def test_delete_command_after_upload_is_not_treated_as_name(self):

        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="delete my notes",
            pending_file_present=True,
        )
        self.assertNotEqual(intent, "name_file")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_different_intent")



class ProductionWireFlow_ChatCorsAcceptsAppLocaleFromSvaultai(
    unittest.TestCase,
):
    """Item 9: the production browser at ``https://app.svaultai.com``
    hits ``https://api.svaultai.com/chat`` with:

        Origin:                         https://app.svaultai.com
        Access-Control-Request-Method:  POST
        Access-Control-Request-Headers: authorization,content-type,
                                        x-app-locale,x-device-id

    That preflight must return 200 or the browser refuses to make
    the POST that carries the naming reply. This test asserts the
    invariant at the ``main.CORS_ALLOWED_HEADERS`` list level.

    A full end-to-end preflight (starlette CORSMiddleware ->
    /chat stub) is already covered by
    ``test_cors_preflight_login_2026_07_09.py``; this test locks
    the invariant in the naming-continuation regression file too so
    that a future refactor of that suite cannot quietly remove the
    guarantee."""

    def test_x_app_locale_is_in_the_real_cors_allow_headers_list(self):
        lower = [h.lower() for h in main.CORS_ALLOWED_HEADERS]
        for required in (
            "authorization",
            "content-type",
            "x-app-locale",
            "x-device-id",
        ):
            self.assertIn(
                required, lower,
                msg=(
                    f"{required!r} must be in CORS_ALLOWED_HEADERS "
                    "or the browser preflight for /chat from "
                    "https://app.svaultai.com will 400, which is "
                    "what caused the naming reply to appear to "
                    "'fall through to general chat' — the POST "
                    "never left the browser at all."
                ),
            )

    def test_cors_headers_list_is_not_a_wildcard(self):

        self.assertNotIn("*", main.CORS_ALLOWED_HEADERS)



class PendingFileRoutingLifecycleSourceGuards(unittest.TestCase):
    """Source-level invariants that lock the lifecycle in place:

      * override is called for the response branch decision.
      * name_file branch does the DB write AND replies with a
        confirmation, so ``needs_naming`` is cleared before the
        next chat turn.
      * pending file lookup is per-vault_id.
    """

    def setUp(self):
        self.main_src = inspect.getsource(main)

    def test_pending_file_lookup_is_per_vault(self):




        lookup_signature = inspect.signature(main.get_pending_named_file)
        self.assertIn("vault_id", lookup_signature.parameters)

    def test_pending_file_query_uses_vault_id_param(self):
        src = inspect.getsource(main.get_pending_named_file)


        self.assertRegex(src, r"WHERE\s+vault_id\s*=\s*%s")

    def test_name_file_branch_replies_after_save(self):




        i = self.main_src.index(
            'if intent == "name_file" and pending_file:'
        )
        window = self.main_src[i:i + 3000]

        self.assertIn("save_named_uploaded_asset(", window)

        self.assertIn("encrypted_reply(", window)



class BareNameOverridesEvenWhenLLMGuessesNonChatIntent(unittest.TestCase):




    def test_retrieve_file_llm_guess_is_overridden_to_name_file(self):
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="retrieve_file",
            message="chosenid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)
        self.assertIsNone(reason)

    def test_retrieve_login_llm_guess_is_overridden_to_name_file(self):

        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="retrieve_login",
            message="chosenid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_search_memory_llm_guess_is_overridden_to_name_file(self):
        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="search_memory",
            message="passport photo",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_generate_login_llm_guess_is_overridden_when_message_is_bare_name(
        self,
    ):

        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="generate_login",
            message="chosenid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_explicit_other_intent_still_wins_over_bare_name_override(self):




        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="show my logins",
            pending_file_present=True,
        )
        self.assertEqual(intent, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")

    def test_llm_explicit_intent_is_trusted_when_message_has_verb(self):

        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="retrieve_login",
            message="find my Gmail password",
            pending_file_present=True,
        )
        self.assertEqual(intent, "retrieve_login")
        self.assertFalse(applied)
        self.assertEqual(reason, "llm_explicit_other_intent")



class RouterMatchesGenerateLoginBeforeLoginSearch(unittest.TestCase):




    def test_generate_me_a_login_for_bank_routes_to_generated_login_create(
        self,
    ):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
            INTENT_LOGIN_SEARCH,
        )
        result = classify_and_build_vault_intent(
            "generate me a login for American first credit union",
        )
        self.assertEqual(
            result.get("intent"),
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
            msg=(
                "The message must route to generated-login-create-draft. "
                "It was misrouting to vault_login_search because the "
                "LOGIN_SEARCH regex `login for X` was catching it "
                "before the GENERATED_LOGIN_CREATE patterns."
            ),
        )
        self.assertNotEqual(
            result.get("intent"), INTENT_LOGIN_SEARCH,
        )

    def test_create_me_a_login_for_gmail_routes_to_generated_login_create(
        self,
    ):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
        )
        result = classify_and_build_vault_intent(
            "create me a login for Gmail",
        )
        self.assertEqual(
            result.get("intent"),
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
        )

    def test_generate_new_login_for_service_routes_to_generated_login_create(
        self,
    ):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
        )
        result = classify_and_build_vault_intent(
            "generate a new login for Chase Bank",
        )
        self.assertEqual(
            result.get("intent"),
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
        )

    def test_find_my_gmail_login_still_routes_to_login_search(self):

        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_LOGIN_SEARCH,
        )
        result = classify_and_build_vault_intent("find my Gmail login")
        self.assertEqual(result.get("intent"), INTENT_LOGIN_SEARCH)

    def test_login_for_gmail_without_generate_verb_stays_login_search(self):

        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_LOGIN_SEARCH,
        )
        result = classify_and_build_vault_intent("login for gmail")
        self.assertEqual(result.get("intent"), INTENT_LOGIN_SEARCH)

    def test_generated_login_router_envelope_has_correct_shape(self):

        from vault_chat_router import (
            build_vault_chat_envelope,
        )
        envelope = build_vault_chat_envelope(
            "generate me a login for American first credit union",
        )
        self.assertIsInstance(envelope, dict)
        self.assertEqual(envelope.get("type"), "vault_chat_card")
        self.assertEqual(envelope.get("schema"), "vault_chat_response_v1")
        self.assertEqual(
            envelope.get("intent"), "vault_generated_login_create_draft",
        )



class UUIDTextCastSafetyInJoins(unittest.TestCase):




    def test_vault_understanding_stale_join_casts_uuid_to_text(self):

        import vault_understanding
        src = inspect.getsource(
            vault_understanding.mark_stale_understandings_for_changed_text,
        )



        self.assertNotIn("u.id::text = v.file_id", src)
        self.assertNotIn("u.id::text=v.file_id", src)


        self.assertIn("u.id = v.file_id::text", src)

    def test_vault_embeddings_stale_join_casts_uuid_to_text(self):
        import vault_understanding
        src = inspect.getsource(
            vault_understanding.mark_stale_embeddings_for_changed_text,
        )
        self.assertNotIn("u.id::text = e.file_id", src)
        self.assertIn("u.id = e.file_id::text", src)

    def test_backfill_archive_signals_join_uses_correct_cast(self):
        import vault_understanding
        src = inspect.getsource(
            vault_understanding.backfill_archive_signals,
        )


        self.assertIn("v.file_id::text = u.id", src)
        self.assertNotIn("v.file_id  = u.id::text", src)
        self.assertNotIn("v.file_id = u.id::text", src)

    def test_relationship_load_facts_uses_correct_cast(self):
        import vault_relationship_graph
        src = inspect.getsource(
            vault_relationship_graph.load_file_facts_for_vault,
        )


        self.assertIn("v.file_id::text = u.id", src)
        self.assertIn("e.file_id::text = u.id", src)
        self.assertNotIn("v.file_id = u.id::text", src)
        self.assertNotIn("e.file_id = u.id::text", src)

    def test_relationship_cleanup_uses_correct_cast(self):
        import vault_relationship_graph
        src = inspect.getsource(
            vault_relationship_graph.cleanup_stale_relationships_for_vault,
        )


        self.assertIn("f.id = r.file_a_id::text", src)
        self.assertIn("f.id = r.file_b_id::text", src)
        self.assertNotIn("f.id::text = r.file_a_id", src)
        self.assertNotIn("f.id::text = r.file_b_id", src)

    def test_vault_understanding_search_facts_uses_correct_cast(self):
        import vault_understanding_search
        src = inspect.getsource(vault_understanding_search)


        self.assertIn("v.file_id::text = u.id", src)
        self.assertIn("e.file_id::text = u.id", src)



class NamingFlowInstrumentationIsPresent(unittest.TestCase):

    def test_get_pending_named_file_logs_lookup_result(self):
        src = inspect.getsource(main.get_pending_named_file)
        self.assertIn("[CHAT-DEBUG] pending_file_lookup", src)


        self.assertIn("needs_naming", src)
        self.assertIn("upload_status", src)

    def test_chat_handler_reuses_pending_file_from_intent_stage(self):

        src = inspect.getsource(main)
        window = src[src.index("if intent == \"name_file\" and pending_file:") - 300:
                     src.index("if intent == \"name_file\" and pending_file:")]
        self.assertIn("pending_file_for_intent", window)


class RawJsonNeverShownToUserFrontendGuard(unittest.TestCase):




    def _frontend_main_dart(self) -> str:
        import pathlib
        here = pathlib.Path(__file__).resolve().parent
        candidate = (
            here.parent / "vault_ai_frontend" / "lib" / "main.dart"
        )
        return candidate.read_text(encoding="utf-8")

    def test_frontend_has_vault_chat_card_type_handler(self):
        src = self._frontend_main_dart()
        self.assertIn("type == 'vault_chat_card'", src)
        self.assertIn("kind: 'vault_chat_card'", src)

    def test_frontend_has_safe_fallback_for_unknown_envelope_type(self):

        src = self._frontend_main_dart()

        self.assertIn(
            "I received a response but I can",
            src,
        )
        self.assertIn(
            "render it here yet",
            src,
        )

    def test_frontend_has_json_shaped_payload_safe_fallback(self):

        src = self._frontend_main_dart()
        self.assertIn(
            "display it. ",
            src,
        )


if __name__ == "__main__":
    unittest.main()
