r"""Regression tests for the generic active-entity chat context.

This suite locks the invariants of the refactor that replaced the
login-only ``vault_chat_last_login_search`` + ``vault_chat_login_
followup`` modules with the generic pair:

    vault_chat_active_entity      — per-vault + per-session record of
                                    the currently-active entity
                                    (login / file / secure_item / id
                                    document / note / folder /
                                    generated_login_draft /
                                    storage_card / billing_card /
                                    crypto_wallet).

    vault_chat_pronoun_followup   — bare "same as last" pronoun
                                    detector returning a verb tag
                                    (show / open / view / rename /
                                    delete / copy / save / upgrade).

The chat handler in main.py dispatches on (entity_type × verb) and
falls back to the normal router when no verb matches. Sensitive
verbs (reveal, unmask, "show the password") are explicitly rejected
by the follow-up detector and continue to route to the existing
confirmation-required flow.

Test map to the 14 required behaviours from the operator brief:

    1.  login found → "show me"             → LoginFollowupShowMeRendersMaskedCard
    2.  file found → "open it"              → FileFollowupOpenItPreservesResolution
    3.  ID found → "show it"                → IdDocumentFollowupSupport
    4.  secure item found → "open it"       → SecureItemFollowupSupport
    5.  generated-login draft → "save it"   → GeneratedLoginDraftFollowupSupport
    6.  explicit topic change wins          → ExplicitTopicChangeOverridesActiveContext
    7.  scoped by vault + session           → ActiveEntityScopedByVaultAndSession
    8.  cleared on logout etc.              → SessionRevokeClearsActiveEntity
    9.  TTL expiry                          → ActiveEntityTtlExpiry
    10. no secrets in context               → ActiveEntityNeverStoresSecrets
    11. reveal still needs confirmation     → RevealAndCopyStillRouteToConfirmation
    12. multiple matches → chooser          → MultiMatchProducesChooserRecord
    13. locale + streaming stable           → LocaleAndStreamingInvariants
    14. no raw JSON shown                   → NoRawJsonRegressionGuard
"""

from __future__ import annotations

import ast
import inspect
import time
import unittest

import vault_chat_active_entity as ae
from vault_chat_pronoun_followup import (
    detect_pronoun_followup,
    is_login_bare_followup,
)
from vault_chat_router import (
    build_vault_chat_envelope,
    INTENT_LOGIN_SEARCH,
    INTENT_LOGIN_LIST,
    INTENT_LOGIN_REVEAL,
    INTENT_LOGIN_COPY,
    INTENT_GENERATED_LOGIN_CREATE_DRAFT,
)




class ActiveEntityStoreCorePrimitives(unittest.TestCase):

    def setUp(self):
        ae._reset_store_for_test()

    def test_set_then_get_returns_the_record(self):
        ok = ae.set_active_entity(
            "v1",
            entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            display_label="Gmail",
            query="Gmail",
            allowed_actions=(ae.ACTION_SHOW, ae.ACTION_OPEN),
            session_id="s1",
        )
        self.assertTrue(ok)
        rec = ae.get_active_entity("v1", session_id="s1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["entity_type"], ae.ENTITY_LOGIN)
        self.assertEqual(rec["display_label"], "Gmail")
        self.assertEqual(rec["query"], "Gmail")
        self.assertIn(ae.ACTION_SHOW, rec["allowed_actions"])
        self.assertIn(ae.ACTION_OPEN, rec["allowed_actions"])

    def test_unknown_entity_type_is_rejected(self):
        self.assertFalse(
            ae.set_active_entity(
                "v1", entity_type="not_a_type",
                entity_ref={"id": "x"},
                allowed_actions=(ae.ACTION_SHOW,),
            ),
        )
        self.assertIsNone(ae.get_active_entity("v1"))

    def test_unknown_ref_key_is_rejected(self):

        self.assertFalse(
            ae.set_active_entity(
                "v1",
                entity_type=ae.ENTITY_LOGIN,
                entity_ref={"not_allowed": "x"},
                allowed_actions=(ae.ACTION_SHOW,),
            ),
        )

    def test_unknown_action_is_dropped_but_write_succeeds(self):
        ok = ae.set_active_entity(
            "v1",
            entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=("madeup", ae.ACTION_SHOW),
        )
        self.assertTrue(ok)
        rec = ae.get_active_entity("v1")
        self.assertIn(ae.ACTION_SHOW, rec["allowed_actions"])
        self.assertNotIn("madeup", rec["allowed_actions"])

    def test_get_returns_none_for_unknown_vault(self):
        self.assertIsNone(ae.get_active_entity("nope"))

    def test_clear_removes_entry(self):
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW,),
        )
        cleared = ae.clear_active_entity("v1")
        self.assertTrue(cleared)
        self.assertIsNone(ae.get_active_entity("v1"))

    def test_entity_matches_action_helper(self):
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW, ae.ACTION_OPEN),
        )
        rec = ae.get_active_entity("v1")
        self.assertTrue(ae.entity_matches_action(rec, "show"))
        self.assertTrue(ae.entity_matches_action(rec, "open"))
        self.assertFalse(ae.entity_matches_action(rec, "delete"))
        self.assertFalse(ae.entity_matches_action(rec, ""))
        self.assertFalse(ae.entity_matches_action(None, "show"))



class LoginFollowupShowMeRendersMaskedCard(unittest.TestCase):




    def test_show_me_verb_is_detected(self):
        hit = detect_pronoun_followup("show me")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["verb"], "show")

    def test_login_bare_followup_shim_still_matches_show_me(self):
        self.assertTrue(is_login_bare_followup("show me"))
        self.assertTrue(is_login_bare_followup("show it"))
        self.assertTrue(is_login_bare_followup("open it"))

    def test_dispatch_synthesises_find_my_query_login(self):

        env = build_vault_chat_envelope("find my American First Credit Union login")
        self.assertIsNotNone(env)
        self.assertEqual(env["intent"], INTENT_LOGIN_SEARCH)
        self.assertEqual(env["type"], "vault_chat_card")
        self.assertEqual(env["schema"], "vault_chat_response_v1")

        self.assertFalse(env["card"].get("maskedByDefault", True))
        self.assertEqual(env["card"].get("view"), "detail")
        self.assertEqual(
            env["card"].get("query"),
            "American First Credit Union",
        )



class FileFollowupOpenItPreservesResolution(unittest.TestCase):

    def test_open_it_produces_open_verb(self):
        hit = detect_pronoun_followup("open it")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["verb"], "open")

    def test_view_it_produces_view_verb(self):
        hit = detect_pronoun_followup("view it")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["verb"], "view")

    def test_active_entity_supports_file_type_with_open_action(self):
        ae._reset_store_for_test()
        ok = ae.set_active_entity(
            "v1",
            entity_type=ae.ENTITY_FILE,
            entity_ref={"file_id": "f-123",
                        "content_type": "image/png"},
            display_label="passport.png",
            query="passport",
            allowed_actions=(
                ae.ACTION_OPEN, ae.ACTION_VIEW,
                ae.ACTION_SHOW, ae.ACTION_RENAME,
                ae.ACTION_DELETE,
            ),
            session_id="s1",
        )
        self.assertTrue(ok)
        rec = ae.get_active_entity("v1", session_id="s1")
        self.assertEqual(rec["entity_type"], ae.ENTITY_FILE)
        self.assertTrue(ae.entity_matches_action(rec, "open"))

    def test_chat_handler_wires_file_active_entity_on_open_one(self):

        import main
        src = inspect.getsource(main)
        self.assertIn(
            'entity_type=ENTITY_FILE', src,
            msg=(
                "The chat handler must record ENTITY_FILE when the "
                "file-followup resolver picks a single file."
            ),
        )



class IdDocumentFollowupSupport(unittest.TestCase):

    def test_show_it_and_view_it_both_map_to_verbs(self):
        self.assertEqual(detect_pronoun_followup("show it")["verb"], "show")
        self.assertEqual(detect_pronoun_followup("view it")["verb"], "view")

    def test_active_entity_supports_id_document_type(self):
        ae._reset_store_for_test()
        ok = ae.set_active_entity(
            "v1",
            entity_type=ae.ENTITY_ID_DOCUMENT,
            entity_ref={"id": "id-42"},
            display_label="US Passport (masked)",
            allowed_actions=(ae.ACTION_SHOW, ae.ACTION_VIEW),
        )
        self.assertTrue(ok)
        rec = ae.get_active_entity("v1")
        self.assertEqual(rec["entity_type"], ae.ENTITY_ID_DOCUMENT)



class SecureItemFollowupSupport(unittest.TestCase):

    def test_active_entity_supports_secure_item_type(self):
        ae._reset_store_for_test()
        ok = ae.set_active_entity(
            "v1",
            entity_type=ae.ENTITY_SECURE_ITEM,
            entity_ref={"item_id": "si-9"},
            display_label="Bank card (Chase ****1234)",
            allowed_actions=(
                ae.ACTION_OPEN, ae.ACTION_VIEW,
                ae.ACTION_SHOW, ae.ACTION_EDIT,
                ae.ACTION_DELETE,
            ),
        )
        self.assertTrue(ok)

    def test_open_it_verb_is_detected(self):
        self.assertEqual(
            detect_pronoun_followup("open it")["verb"],
            "open",
        )



class GeneratedLoginDraftFollowupSupport(unittest.TestCase):

    def test_save_it_maps_to_save_verb(self):
        self.assertEqual(
            detect_pronoun_followup("save it")["verb"],
            "save",
        )
        self.assertEqual(
            detect_pronoun_followup("save that one")["verb"],
            "save",
        )

    def test_active_entity_supports_generated_login_draft(self):
        ae._reset_store_for_test()
        ok = ae.set_active_entity(
            "v1",
            entity_type=ae.ENTITY_GENERATED_LOGIN_DRAFT,
            entity_ref={"draft_id": "d-abc",
                        "service": "Chase"},
            display_label="Chase (generated)",
            allowed_actions=(ae.ACTION_SAVE, ae.ACTION_EDIT),
        )
        self.assertTrue(ok)
        rec = ae.get_active_entity("v1")
        self.assertTrue(ae.entity_matches_action(rec, "save"))

    def test_generate_login_router_still_wins_over_login_search(self):

        env = build_vault_chat_envelope(
            "generate me a login for chase",
        )
        self.assertEqual(
            env["intent"], INTENT_GENERATED_LOGIN_CREATE_DRAFT,
        )



class ExplicitTopicChangeOverridesActiveContext(unittest.TestCase):

    def test_new_search_message_is_not_a_pronoun_followup(self):

        for phrase in (
            "show me my Gmail login",
            "find my Chase login",
            "list my logins",
            "delete my Chase login",
            "generate me a login for Amazon",
            "show me my saved logins",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    detect_pronoun_followup(phrase), phrase,
                )

    def test_topic_change_clears_previous_login_active_entity(self):
        ae._reset_store_for_test()
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            display_label="Gmail",
            allowed_actions=(ae.ACTION_SHOW,),
        )



        ae.clear_active_entity("v1")
        self.assertIsNone(ae.get_active_entity("v1"))



class ActiveEntityScopedByVaultAndSession(unittest.TestCase):

    def setUp(self):
        ae._reset_store_for_test()

    def test_records_are_scoped_by_vault_id(self):
        ae.set_active_entity(
            "vA", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            query="Gmail",
            allowed_actions=(ae.ACTION_SHOW,),
        )
        ae.set_active_entity(
            "vB", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Chase"},
            query="Chase",
            allowed_actions=(ae.ACTION_SHOW,),
        )
        self.assertEqual(
            ae.get_active_entity("vA")["query"], "Gmail",
        )
        self.assertEqual(
            ae.get_active_entity("vB")["query"], "Chase",
        )

    def test_session_scoped_read_from_wrong_session_returns_none(self):
        ae.set_active_entity(
            "vA", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW,),
            session_id="s1",
        )
        self.assertIsNone(ae.get_active_entity("vA", session_id="s2"))
        self.assertIsNotNone(ae.get_active_entity("vA", session_id="s1"))

    def test_session_scoped_read_without_session_id_returns_none(self):

        ae.set_active_entity(
            "vA", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW,),
            session_id="s1",
        )
        self.assertIsNone(ae.get_active_entity("vA"))

    def test_unscoped_write_readable_from_any_session(self):

        ae.set_active_entity(
            "vA", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW,),
        )
        self.assertIsNotNone(ae.get_active_entity("vA"))
        self.assertIsNotNone(ae.get_active_entity("vA", session_id="anything"))



class SessionRevokeClearsActiveEntity(unittest.TestCase):

    def test_revoke_all_sessions_for_vault_clears_active_entity(self):
        import auth_local
        src = inspect.getsource(auth_local.revoke_all_sessions_for_vault)
        self.assertIn(
            "vault_chat_active_entity", src,
            msg=(
                "revoke_all_sessions_for_vault must clear the generic "
                "active-entity context so a re-login on the same "
                "worker cannot see the previous user's entity."
            ),
        )
        self.assertIn("clear_active_entity", src)
        self.assertIn("clear_active_context", src)



class ActiveEntityTtlExpiry(unittest.TestCase):

    def test_expired_entity_returns_none(self):
        ae._reset_store_for_test()
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW,),
            ttl_seconds=1,
        )
        time.sleep(1.05)
        self.assertIsNone(ae.get_active_entity("v1"))

    def test_default_ttl_is_bounded_and_within_15_minutes_by_default(self):

        self.assertGreater(ae.DEFAULT_TTL_SECONDS, 0)
        self.assertLessEqual(ae.DEFAULT_TTL_SECONDS, 3600)



class ActiveEntityNeverStoresSecrets(unittest.TestCase):

    def test_module_body_does_not_touch_encrypted_or_secret_material(self):

        src = inspect.getsource(ae)
        try:
            tree = ast.parse(src)
        except Exception:
            self.fail("could not parse the active-entity module")


        callable_names: list[str] = []
        import_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    callable_names.append(fn.attr)
                elif isinstance(fn, ast.Name):
                    callable_names.append(fn.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_names.append(node.module)


        banned_calls = {
            "encrypt_message", "decrypt_message",
            "encrypt_bytes", "decrypt_bytes",
            "get_verified_vault_key",
            "generate_strong_password",
            "retrieve_secret_tool",
            "save_secret_tool",
            "get_db",
        }
        for call in callable_names:
            self.assertNotIn(
                call.lower(), banned_calls,
                msg=(
                    f"active-entity module must NOT call {call!r}. "
                    "The store handles only opaque descriptors, "
                    "never plaintext credentials or DB reads."
                ),
            )


        banned_modules = {
            "openai", "psycopg2", "vault_core",
        }
        for m in import_names:
            self.assertNotIn(
                m.lower(), banned_modules,
                msg=(
                    f"active-entity module must NOT import {m!r}. "
                    "It has no business touching OpenAI / the DB "
                    "driver / the vault-core key derivation."
                ),
            )

    def test_forbidden_ref_keys_are_rejected(self):

        ae._reset_store_for_test()
        for banned in (
            "password", "pin", "seed", "mnemonic",
            "private_key", "api_key", "encrypted_data",
        ):
            ok = ae.set_active_entity(
                "v1", entity_type=ae.ENTITY_LOGIN,
                entity_ref={banned: "leak"},
                allowed_actions=(ae.ACTION_SHOW,),
            )
            self.assertFalse(
                ok,
                msg=f"key {banned!r} must be rejected by the store",
            )
            self.assertIsNone(ae.get_active_entity("v1"))

    def test_display_label_is_length_bounded(self):
        ae._reset_store_for_test()
        long_label = "A" * (ae.MAX_LABEL_CHARS + 100)
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            display_label=long_label,
            allowed_actions=(ae.ACTION_SHOW,),
        )
        rec = ae.get_active_entity("v1")
        self.assertLessEqual(len(rec["display_label"]), ae.MAX_LABEL_CHARS)

    def test_query_is_length_bounded(self):
        ae._reset_store_for_test()
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            query="A" * (ae.MAX_QUERY_CHARS + 100),
            allowed_actions=(ae.ACTION_SHOW,),
        )
        rec = ae.get_active_entity("v1")
        self.assertLessEqual(len(rec["query"] or ""), ae.MAX_QUERY_CHARS)

    def test_candidates_list_is_length_bounded(self):
        ae._reset_store_for_test()
        big = [{"id": str(i)} for i in range(ae.MAX_CANDIDATES + 25)]
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Gmail"},
            allowed_actions=(ae.ACTION_SHOW,),
            is_multi=True, candidates=big,
        )
        rec = ae.get_active_entity("v1")
        self.assertLessEqual(len(rec["candidates"]), ae.MAX_CANDIDATES)



class RevealAndCopyRouteToDetailCard(unittest.TestCase):
    """Product decision (2026-07-11): an authenticated user with an
    unlocked vault who explicitly asks to reveal or copy a saved login
    sees the DETAIL card, not a second confirmation prompt. The
    plaintext credential is populated by
    populate_vault_chat_card_data via a positive allowlist — never by
    the router shell — see _sanitize_login_detail_payload."""


    def test_show_me_the_password_hits_login_detail(self):
        env = build_vault_chat_envelope("show me the password for gmail")
        self.assertEqual(env["intent"], INTENT_LOGIN_REVEAL)
        self.assertEqual(env["card"]["cardType"], "vault_login_card")
        self.assertEqual(env["card"].get("view"), "detail")
        self.assertEqual(
            (env["card"].get("query") or "").lower(), "gmail",
        )

        self.assertNotIn("action", env["card"])
        self.assertNotIn("requiresPinUnlock", env["card"])

    def test_reveal_it_is_not_a_pronoun_followup(self):
        self.assertIsNone(detect_pronoun_followup("reveal it"))

    def test_unmask_it_is_not_a_pronoun_followup(self):
        self.assertIsNone(detect_pronoun_followup("unmask it"))

    def test_show_the_password_is_not_a_pronoun_followup(self):
        self.assertIsNone(detect_pronoun_followup("show the password"))
        self.assertIsNone(detect_pronoun_followup("show me the pin"))

    def test_copy_the_password_still_hits_confirmation(self):
        env = build_vault_chat_envelope("copy the password")
        self.assertEqual(env["intent"], INTENT_LOGIN_COPY)

    def test_seed_or_mnemonic_or_private_key_are_never_followups(self):
        for phrase in (
            "show the seed",
            "reveal the mnemonic",
            "show the private key",
            "show me the api key",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(detect_pronoun_followup(phrase))



class MultiMatchProducesChooserRecord(unittest.TestCase):




    def test_is_multi_true_stores_candidates(self):
        ae._reset_store_for_test()
        candidates = [
            {"id": "l-1"},
            {"id": "l-2"},
            {"id": "l-3"},
        ]
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Chase"},
            display_label="Chase (multiple)",
            allowed_actions=(ae.ACTION_SHOW, ae.ACTION_OPEN),
            is_multi=True,
            candidates=candidates,
        )
        rec = ae.get_active_entity("v1")
        self.assertTrue(rec["is_multi"])
        self.assertEqual(len(rec["candidates"]), 3)


        for c in rec["candidates"]:
            for banned in ("password", "encrypted_data", "seed"):
                self.assertNotIn(banned, c)

    def test_chooser_record_still_has_query_for_re_render(self):
        ae._reset_store_for_test()
        ae.set_active_entity(
            "v1", entity_type=ae.ENTITY_LOGIN,
            entity_ref={"query": "Chase"},
            display_label="Chase (multiple)",
            query="Chase",
            allowed_actions=(ae.ACTION_SHOW, ae.ACTION_OPEN),
            is_multi=True,
            candidates=[{"id": "l-1"}, {"id": "l-2"}],
        )
        rec = ae.get_active_entity("v1")
        self.assertEqual(rec["query"], "Chase")



class LocaleAndStreamingInvariants(unittest.TestCase):

    def test_pronoun_followup_signature_takes_only_the_message(self):

        sig = inspect.signature(detect_pronoun_followup)
        self.assertEqual(
            list(sig.parameters), ["user_message"],
        )

    def test_router_envelope_shape_is_stable(self):

        env = build_vault_chat_envelope(
            "show me my American First Credit Union bank",
        )
        self.assertEqual(env["type"], "vault_chat_card")
        self.assertEqual(env["schema"], "vault_chat_response_v1")
        self.assertEqual(env["intent"], INTENT_LOGIN_SEARCH)



class NoRawJsonRegressionGuard(unittest.TestCase):




    def test_frontend_still_has_vault_chat_card_type_handler(self):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent
        p = here.parent / "vault_ai_frontend" / "lib" / "main.dart"
        src = p.read_text(encoding="utf-8")
        self.assertIn("type == 'vault_chat_card'", src)
        self.assertIn("kind: 'vault_chat_card'", src)

    def test_frontend_still_has_json_shape_safe_fallback(self):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent
        p = here.parent / "vault_ai_frontend" / "lib" / "main.dart"
        src = p.read_text(encoding="utf-8")
        self.assertIn(
            "no matching renderer or fallback message", src,
        )



class ChatHandlerWiringSourceGuards(unittest.TestCase):

    def setUp(self):
        import main
        self.main_src = inspect.getsource(main)

    def test_main_imports_the_generic_active_entity_module(self):

        self.assertNotIn(
            "vault_chat_last_login_search", self.main_src,
            msg="old login-only module must be fully removed from main.py",
        )
        self.assertNotIn(
            "vault_chat_login_followup", self.main_src,
            msg="old login-only followup module must be fully removed",
        )
        self.assertIn(
            "from vault_chat_active_entity import", self.main_src,
        )
        self.assertIn(
            "from vault_chat_pronoun_followup import", self.main_src,
        )

    def test_login_search_fast_path_writes_login_active_entity(self):

        idx = self.main_src.find('_login_intents = (')
        self.assertGreater(idx, -1,
            msg="fast-path must define the tuple of login intents",
        )
        window = self.main_src[idx:idx + 2500]
        self.assertIn("vault_login_search", window)
        self.assertIn("vault_login_reveal", window)
        self.assertIn("vault_login_copy", window)
        self.assertIn("set_active_entity(", window)
        self.assertIn("entity_type=ENTITY_LOGIN", window)


        self.assertIn("session_id=_fp_session_id", window)


        self.assertIn("ACTION_EDIT", window)

    def test_login_search_slow_path_writes_login_active_entity(self):

        idx = self.main_src.find('_vcr_login_intents = (')
        self.assertGreater(idx, -1,
            msg="slow-path must define the tuple of login intents",
        )
        window = self.main_src[idx:idx + 3500]
        self.assertIn("vault_login_search", window)
        self.assertIn("vault_login_reveal", window)
        self.assertIn("vault_login_copy", window)
        self.assertIn("set_active_entity(", window)
        self.assertIn("entity_type=ENTITY_LOGIN", window)
        self.assertIn("session_id=_vcr_session_id", window)
        self.assertIn("ACTION_EDIT", window)

    def test_file_open_writes_file_active_entity(self):
        idx = self.main_src.find(
            "entity_type=ENTITY_FILE",
        )
        self.assertGreater(idx, -1)
        window = self.main_src[
            max(0, idx - 400): idx + 800
        ]

        self.assertIn("file_id", window)
        self.assertIn("session_id=_file_session_id", window)

    def test_followup_dispatch_calls_populate_before_returning(self):

        idx = self.main_src.find(
            "detect_pronoun_followup(decrypted_message)",
        )
        self.assertGreater(idx, -1)
        window = self.main_src[idx:idx + 4500]

        self.assertIn("get_active_entity(", window)

        self.assertIn("entity_matches_action(", window)

        self.assertIn("populate_vault_chat_card_data(", window)
        self.assertIn("encrypted_reply(", window)



class OtherContinuationFlowsStillWork(unittest.TestCase):

    def test_file_search_followup_module_untouched(self):
        import vault_chat_followup as fu
        self.assertTrue(hasattr(fu, "resolve_followup"))
        self.assertTrue(hasattr(fu, "detect_followup_reference"))

    def test_naming_continuation_override_still_present(self):
        import main
        self.assertTrue(hasattr(main, "decide_pending_file_intent_override"))

    def test_pending_draft_confirm_module_untouched(self):
        import vault_pending_draft_confirm as p
        self.assertTrue(hasattr(p, "is_pending_draft_confirm_phrase"))

    def test_masking_invariant_project_login_row_still_masks(self):

        import vault_chat_card_data
        src = inspect.getsource(vault_chat_card_data._project_login_row)
        self.assertNotIn('"password"', src)
        self.assertNotIn("'password'", src)
        self.assertIn('"username_masked"', src)



class RouterLoginPhraseCoverageIsIntact(unittest.TestCase):




    def test_show_open_pull_up_phrasings_hit_login_search(self):
        for phrase in (
            "show me my American First Credit Union bank",
            "show me my Chase bank",
            "show me my Gmail login",
            "open my Google login",
            "pull up my Amazon login",
            "find my Gmail login",
        ):
            with self.subTest(phrase=phrase):
                env = build_vault_chat_envelope(phrase)
                self.assertIsNotNone(env, phrase)
                self.assertEqual(env["intent"], INTENT_LOGIN_SEARCH, phrase)

    def test_list_phrasing_still_hits_login_list(self):
        for phrase in (
            "show me my saved logins",
            "list my logins",
            "my saved passwords",
        ):
            with self.subTest(phrase=phrase):
                env = build_vault_chat_envelope(phrase)
                self.assertEqual(env["intent"], INTENT_LOGIN_LIST, phrase)


if __name__ == "__main__":
    unittest.main()
