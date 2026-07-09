

from __future__ import annotations

import unittest
from contextlib import contextmanager
from typing import Any, Iterable, Optional

import main
from locales import ENGLISH_FORMATTER


class ExplicitDifferentIntentGuardTests(unittest.TestCase):


    SHOULD_FIRE = [
                                               
        "show my saved logins",
        "all the logins",
        "list my files",
        "retrieve my documents",
        "show recordings",
                                                              
        "show all my logins please",
        "ALL THE LOGINS",                                           
        "Show my passwords",                                        
        "find my Gmail credential",                                   
        "delete my Chase login",                               
        "edit my notes",                                        
        "search my recordings",                                
        "open billing",                                            
        "go to settings",                                           
        "my saved logins",                                           
        "my passwords",
    ]

                                                                    
    SHOULD_NOT_FIRE = [
        "vibing",
        "holiday memories",
        "trip notes",
        "graduation 2026",
        "tax 2025",
        "project alpha",
        "the budget",
                                                                
                           
        "save the audio recording to vibing",
        "call it trip notes",
        "name it vibing",
                                                             
        "",
        "   ",
    ]

    def test_should_fire_on_explicit_different_intent_phrases(self):
        for phrase in self.SHOULD_FIRE:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    main.message_signals_explicit_different_intent(phrase),
                    f"guard failed to fire on: {phrase!r}",
                )

    def test_should_not_fire_on_name_replies(self):
        for phrase in self.SHOULD_NOT_FIRE:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    main.message_signals_explicit_different_intent(phrase),
                    f"guard wrongly fired on name reply: {phrase!r}",
                )

    def test_none_input_is_safe(self):
        self.assertFalse(
            main.message_signals_explicit_different_intent(None)
        )


class PendingFileOverrideStateMachineTests(unittest.TestCase):


    def test_pending_file_plus_bare_name_coerces_to_name_file(self):
                                                                      
                                            
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="vibing",
            pending_file_present=True,
        )
        self.assertEqual(final, "name_file")
        self.assertTrue(applied)
        self.assertIsNone(reason)

                                                                        
    def test_pending_file_plus_save_this_as_name_coerces_to_name_file(self):
                                                                   
                                                                     
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="save this as vibing",
            pending_file_present=True,
        )
        self.assertEqual(final, "name_file")
        self.assertTrue(applied)
        self.assertIsNone(reason)

    def test_pending_file_plus_llm_returns_name_file_passes_through(self):
                                                                  
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="name_file",
            message="vibing",
            pending_file_present=True,
        )
        self.assertEqual(final, "name_file")
        self.assertFalse(applied)
        self.assertEqual(reason, "llm_already_name_file")

                                                                        
    def test_pending_file_plus_show_my_saved_logins_downgrades_to_list(self):
                                                                      
                                                             
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="show my saved logins",
            pending_file_present=True,
        )
        self.assertEqual(final, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")

                                                                        
    def test_pending_file_plus_all_the_logins_downgrades_to_list(self):
                                                                     
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="all the logins",
            pending_file_present=True,
        )
        self.assertEqual(final, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")

                                                                       
    def test_llm_picks_list_logins_directly_is_trusted(self):
                                                                       
                     
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="list_logins",
            message="show my saved logins",
            pending_file_present=True,
        )
        self.assertEqual(final, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "llm_explicit_other_intent")

    def test_llm_picks_retrieve_login_is_trusted(self):
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="retrieve_login",
            message="find my Gmail password",
            pending_file_present=True,
        )
        self.assertEqual(final, "retrieve_login")
        self.assertFalse(applied)
        self.assertEqual(reason, "llm_explicit_other_intent")

                                                                        
    def test_pending_file_plus_list_my_files_skips_override(self):
                                                                       
                                                                     
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="list my files",
            pending_file_present=True,
        )
        self.assertEqual(final, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_different_intent")

    def test_pending_file_plus_open_billing_skips_override(self):
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="open billing",
            pending_file_present=True,
        )
        self.assertEqual(final, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_different_intent")

                                                                        
    def test_no_pending_file_passes_intent_through(self):
                                                                    
                                                                
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="vibing",
            pending_file_present=False,
        )
        self.assertEqual(final, "general_chat")
        self.assertFalse(applied)
        self.assertIsNone(reason)

                                                                        
    def test_long_messages_are_not_treated_as_bare_names(self):
                                                                      
                                               
        long_msg = "hello " * 30              
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message=long_msg,
            pending_file_present=True,
        )
        self.assertEqual(final, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "message_not_bare_name")

    def test_question_marks_are_not_treated_as_bare_names(self):
                                          
        final, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="hello?",
            pending_file_present=True,
        )
        self.assertEqual(final, "general_chat")
        self.assertFalse(applied)
        self.assertEqual(reason, "message_not_bare_name")


class _FakeCursor:


    def __init__(self, rows: Iterable[dict[str, Any]]):
        self._rows = list(rows)
        self.executed_sql: Optional[str] = None
        self.executed_params: Optional[tuple] = None

    def execute(self, sql: str, params: tuple) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _FakeConn:


    def __init__(self, rows: Iterable[dict[str, Any]]):
        self._cursor = _FakeCursor(rows)

                                                                     
    def cursor(self, cursor_factory=None):
        return self._cursor

    def close(self):
        pass


@contextmanager
def _patch_get_db(rows: Iterable[dict[str, Any]]):


    original = main.get_db
    fake_conn = _FakeConn(rows)
    main.get_db = lambda: fake_conn                            
    try:
        yield fake_conn
    finally:
        main.get_db = original                            


class ListLoginsToolTests(unittest.TestCase):


    def test_empty_returns_localized_no_saved_logins(self):
                                                                       
                                                                       
        expected = ENGLISH_FORMATTER.no_saved_logins()
        self.assertEqual(
            expected,
            "I don't see any saved logins in this vault yet.",
            "locale string drifted from the bug report spec",
        )
        with _patch_get_db([]):
            actual = main.list_logins_tool(
                vault_id="00000000-0000-4000-8000-0000000000b1",
            )
        self.assertEqual(actual, expected)

    def test_renders_logins_only_no_uploaded_files(self):
                                                                      
                                                                    
        with _patch_get_db([
            {"service": "Gmail"},
            {"service": "Chase"},
        ]) as fake_conn:
            out = main.list_logins_tool(
                vault_id="00000000-0000-4000-8000-0000000000b1",
            )

                            
        self.assertIn("Here are your saved logins:", out)
        self.assertIn("- Gmail", out)
        self.assertIn("- Chase", out)

                                                                     
        sql = fake_conn._cursor.executed_sql or ""
        self.assertIn("item_type", sql.lower())
        self.assertIn("'login'", sql.lower())
                                                        
        self.assertEqual(
            fake_conn._cursor.executed_params,
            ("00000000-0000-4000-8000-0000000000b1",),
        )

    def test_login_keyword_tuple_includes_bug_report_terms(self):
                                                                    
                                                                      
        for keyword in ("login", "logins", "password", "passwords",
                        "credential", "credentials"):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, main.LOGIN_INTENT_KEYWORDS)


class ExtractNamingIntentFromAccompanyingTextTests(unittest.TestCase):


    def test_save_my_id_extracts_id(self):
                                                                  
                                                                      
        self.assertEqual(
            main.extract_naming_intent_from_accompanying_text("save my ID"),
            "id",
        )

    def test_call_this_passport_extracts_passport(self):
                                      
        self.assertEqual(
            main.extract_naming_intent_from_accompanying_text(
                "call this passport"
            ),
            "passport",
        )

    def test_store_as_drivers_license_extracts_license(self):
                                                                       
                                                       
        out = main.extract_naming_intent_from_accompanying_text(
            "store as driver's license"
        )
        self.assertIsNotNone(out)
        self.assertIn("driver", out)
        self.assertIn("license", out)

                                                                       
    def test_save_it_as_vibing_extracts_vibing(self):
                                                                   
                                                                       
        self.assertEqual(
            main.extract_naming_intent_from_accompanying_text(
                "save it as vibing"
            ),
            "vibing",
        )

    def test_call_it_trip_notes(self):
        out = main.extract_naming_intent_from_accompanying_text(
            "call it trip notes"
        )
        self.assertIsNotNone(out)
        self.assertIn("trip", out)

    def test_name_this_graduation_2026(self):
        out = main.extract_naming_intent_from_accompanying_text(
            "name this graduation 2026"
        )
        self.assertIsNotNone(out)
        self.assertIn("graduation", out)

    def test_save_my_receipt(self):
                                                                      
                                                                   
        out = main.extract_naming_intent_from_accompanying_text(
            "save my receipt"
        )
        self.assertEqual(out, "receipt")

    def test_this_is_my_contract(self):
        out = main.extract_naming_intent_from_accompanying_text(
            "this is my contract"
        )
        self.assertEqual(out, "contract")

    def test_named_X_bare_command_less_label(self):
        out = main.extract_naming_intent_from_accompanying_text(
            "named tax 2025"
        )
        self.assertIsNotNone(out)
        self.assertIn("tax", out)

                                                                       
    def test_show_my_saved_logins_returns_none(self):
                                                                      
                                                      
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(
                "show my saved logins"
            )
        )

    def test_all_the_logins_returns_none(self):
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(
                "all the logins"
            )
        )

    def test_list_my_files_returns_none(self):
                                                                  
                                                                     
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(
                "list my files"
            )
        )

    def test_save_my_logins_returns_none(self):
                                                                    
                                                         
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(
                "save my logins"
            )
        )

    def test_questions_return_none(self):
                                                    
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(
                "what is this?"
            )
        )

    def test_multi_line_returns_none(self):
                                                             
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(
                "hello\nworld"
            )
        )

    def test_empty_and_whitespace_return_none(self):
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text("")
        )
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text("   ")
        )
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(None)
        )

    def test_very_long_message_returns_none(self):
                                                                   
                                                       
        long_msg = (
            "this is a very long message that goes on and on and on "
            "with no apparent end and would be a terrible asset name "
            "because the user is clearly just rambling at this point"
        )
        self.assertIsNone(
            main.extract_naming_intent_from_accompanying_text(long_msg)
        )


class BuildUploadMessageModesTests(unittest.TestCase):


    def _sample(self, asset_type: str = "audio") -> dict:
        return {
            "filename": "recording_1780061048177.wav",
            "asset_type": asset_type,
            "file_id": "f1",
        }

    def test_auto_named_returns_single_saved_as_line(self):
        msg = main._build_upload_message(
            self._sample("audio"),
            auto_saved_name="vibing",
        )
        self.assertIn("Saved this recording as", msg)
        self.assertIn("Vibing", msg)
                                                              
        self.assertNotIn("What should I save", msg)
        self.assertNotIn("Tell me what you want to call it", msg)

    def test_prompt_suppressed_returns_no_prompt(self):
                                                                      
                                                                    
        for asset_type in ("audio", "video", "image", "file"):
            with self.subTest(asset_type=asset_type):
                msg = main._build_upload_message(
                    self._sample(asset_type),
                    suppress_naming_prompt=True,
                )
                self.assertTrue(msg.startswith("Saved "))
                self.assertNotIn("What should I save", msg)
                self.assertNotIn("Tell me what you want to call it", msg)
                self.assertNotIn("?", msg)

    def test_legacy_audio_still_prompts(self):
                                                        
        msg = main._build_upload_message(self._sample("audio"))
        self.assertIn("What should I save this recording as", msg)

    def test_legacy_image_still_prompts(self):
        msg = main._build_upload_message(self._sample("image"))
        self.assertIn("Tell me what you want to call it", msg)

    def test_legacy_file_still_prompts(self):
        msg = main._build_upload_message(self._sample("file"))
        self.assertIn("Tell me what you want to call it", msg)

    def test_auto_named_beats_suppress_flag(self):
                                                   
                                                                     
        msg = main._build_upload_message(
            self._sample("audio"),
            suppress_naming_prompt=True,
            auto_saved_name="vibing",
        )
        self.assertIn("Saved this recording as", msg)
        self.assertIn("Vibing", msg)


from document_understanding import classify_naming_text_doc_type
from taxonomy import (
    DOC_TYPE_TO_ASSET_TYPE,
    DOC_TYPE_TO_FAMILY,
    DOC_TYPE_TO_TAGS,
    NAMING_TEXT_TO_DOC_TYPE,
)


class NamingTextDocTypeClassifierTests(unittest.TestCase):


    def test_bare_id_classifies_as_id_card(self):
                                                                  
                                                                
        self.assertEqual(classify_naming_text_doc_type("ID"), "id_card")
        self.assertEqual(classify_naming_text_doc_type("id"), "id_card")
        self.assertEqual(classify_naming_text_doc_type("save my ID"),
                         "id_card")

    def test_passport_classifies_as_passport(self):
                                             
        self.assertEqual(classify_naming_text_doc_type("passport"),
                         "passport")
        self.assertEqual(classify_naming_text_doc_type("save my passport"),
                         "passport")
        self.assertEqual(classify_naming_text_doc_type("my passports"),
                         "passport")

    def test_drivers_license_classifies_as_driver_license(self):
                                                                   
                                                                     
        self.assertEqual(
            classify_naming_text_doc_type("driver's license"),
            "driver_license",
        )
        self.assertEqual(
            classify_naming_text_doc_type("drivers license"),
            "driver_license",
        )
        self.assertEqual(
            classify_naming_text_doc_type("store as driver's license"),
            "driver_license",
        )

    def test_national_id_card_classifies_as_id_card(self):
        self.assertEqual(
            classify_naming_text_doc_type("national id card"),
            "id_card",
        )
        self.assertEqual(
            classify_naming_text_doc_type("identity card"),
            "id_card",
        )

                                                                      
    def test_receipt_invoice_tax(self):
        self.assertEqual(classify_naming_text_doc_type("receipt"),
                         "receipt")
        self.assertEqual(classify_naming_text_doc_type("invoice"),
                         "invoice")
        self.assertEqual(classify_naming_text_doc_type("tax return"),
                         "tax_document")

    def test_travel_family(self):
        self.assertEqual(
            classify_naming_text_doc_type("boarding pass"),
            "boarding_pass",
        )
        self.assertEqual(
            classify_naming_text_doc_type("hotel booking"),
            "hotel_itinerary",
        )
        self.assertEqual(
            classify_naming_text_doc_type("schengen visa"),
            "visa",
        )

    def test_legal_family(self):
        self.assertEqual(classify_naming_text_doc_type("contract"),
                         "contract")
        self.assertEqual(classify_naming_text_doc_type("nda"),
                         "agreement")

    def test_medical_education_family(self):
        self.assertEqual(
            classify_naming_text_doc_type("medical record"),
            "medical_record",
        )
        self.assertEqual(classify_naming_text_doc_type("degree"),
                         "degree")
        self.assertEqual(classify_naming_text_doc_type("certificate"),
                         "certificate")

                                                                      
    def test_bare_id_does_not_false_positive_on_substring(self):
                                                           
                                                                      
        for haystack in ("video", "guide", "ride", "pyramid", "kid"):
            with self.subTest(haystack=haystack):
                                                                      
                                                          
                self.assertIsNone(
                    classify_naming_text_doc_type(haystack),
                    f"bare 'id' false-positived on {haystack!r}",
                )

    def test_phrases_without_doc_label_return_none(self):
                                                                
                                         
        for phrase in (
            "vibing",
            "holiday memories",
            "trip notes",
            "save",
            "save it",
            "",
            "   ",
            None,
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    classify_naming_text_doc_type(phrase)
                )

                                                                      
    def test_longest_phrase_wins_when_multiple_match(self):
                                                                    
                                                                    
        self.assertEqual(
            classify_naming_text_doc_type("driver's license id"),
            "driver_license",
        )


class TaxonomyContractTests(unittest.TestCase):


    def test_every_naming_doc_type_has_tags(self):
                                                                      
                                                                     
        for doc_type, _phrases in NAMING_TEXT_TO_DOC_TYPE:
            with self.subTest(doc_type=doc_type):
                self.assertIn(doc_type, DOC_TYPE_TO_TAGS)
                self.assertTrue(len(DOC_TYPE_TO_TAGS[doc_type]) >= 1)

    def test_id_family_maps_to_identity_document_label(self):
                                                                     
                                           
        for doc_type in ("passport", "id_card", "driver_license"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(
                    DOC_TYPE_TO_FAMILY.get(doc_type),
                    "identity_document",
                )

    def test_id_family_has_id_document_asset_type_override(self):
                                                                  
                                                                       
        for doc_type in ("passport", "id_card", "driver_license"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(
                    DOC_TYPE_TO_ASSET_TYPE.get(doc_type),
                    "id_document",
                )

    def test_identity_doc_type_tags_include_identity_and_government(self):
                                                            
                                                     
        for doc_type in ("passport", "id_card", "driver_license"):
            with self.subTest(doc_type=doc_type):
                tags = DOC_TYPE_TO_TAGS[doc_type]
                self.assertIn("identity", tags)
                self.assertIn("government", tags)

    def test_passport_also_carries_travel_tag(self):
                                                                
                                                     
        self.assertIn("travel", DOC_TYPE_TO_TAGS["passport"])


class _CapturingCursor:


    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params or ()))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass

                                                                  
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _CapturingConn:


    def __init__(self):
        self.cursors: list[_CapturingCursor] = []
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        cur = _CapturingCursor()
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


@contextmanager
def _patch_get_db_for_persist(conn):


    import main as _main
    original = _main.get_db
    _main.get_db = lambda: conn
    try:
        yield
    finally:
        _main.get_db = original


class PersistNamingTextClassificationTests(unittest.TestCase):


    VAULT_ID = "00000000-0000-4000-8000-0000000000c1"

    def test_returns_none_and_writes_nothing_when_no_label(self):
        conn = _CapturingConn()
        with _patch_get_db_for_persist(conn):
            out = main._persist_naming_text_classification(
                vault_id=self.VAULT_ID,
                file_id="f1",
                naming_text="vibing",                    
                file_name="x.wav",
                content_type="audio/wav",
            )
        self.assertIsNone(out)
                                        
        self.assertEqual(conn.cursors, [])
        self.assertFalse(conn.committed)

    def test_id_card_path_upserts_metadata_and_refreshes_asset_type(self):
        conn = _CapturingConn()
        with _patch_get_db_for_persist(conn):
            out = main._persist_naming_text_classification(
                vault_id=self.VAULT_ID,
                file_id="f1",
                naming_text="save my ID",
                file_name="IMG_001.jpg",
                content_type="image/jpeg",
            )
        self.assertEqual(out, "id_card")
                                                      
                                        
        self.assertGreaterEqual(len(conn.cursors), 2)

        first_sql = conn.cursors[0].executed[0][0].lower()
        self.assertIn("insert into vault_document_metadata", first_sql)
        self.assertIn("on conflict", first_sql)
                                                                
                                                                   
        first_params = conn.cursors[0].executed[0][1]
        self.assertEqual(first_params[0], self.VAULT_ID)            
        self.assertEqual(first_params[1], "f1")                    
        self.assertEqual(first_params[2], "id_card")                
        self.assertEqual(first_params[4], 0.85)                       

                                                 
        second_sql = conn.cursors[1].executed[0][0].lower()
        self.assertIn("update uploaded_files", second_sql)
        self.assertIn("set asset_type", second_sql)
        second_params = conn.cursors[1].executed[0][1]
        self.assertEqual(second_params[0], "id_image")

    def test_passport_pdf_refreshes_asset_type_to_id_document(self):
                                                                    
                                                
        conn = _CapturingConn()
        with _patch_get_db_for_persist(conn):
            out = main._persist_naming_text_classification(
                vault_id=self.VAULT_ID,
                file_id="f9",
                naming_text="save my passport",
                file_name="passport_scan.pdf",
                content_type="application/pdf",
            )
        self.assertEqual(out, "passport")
                                     
        second_params = conn.cursors[1].executed[0][1]
        self.assertEqual(second_params[0], "id_document")

    def test_receipt_path_writes_metadata_but_no_asset_type_refresh(self):
                                                                   
                                                                     
        conn = _CapturingConn()
        with _patch_get_db_for_persist(conn):
            out = main._persist_naming_text_classification(
                vault_id=self.VAULT_ID,
                file_id="f2",
                naming_text="save my receipt",
                file_name="scan.pdf",
                content_type="application/pdf",
            )
        self.assertEqual(out, "receipt")
                                                                
        self.assertEqual(len(conn.cursors), 1)
        self.assertIn(
            "insert into vault_document_metadata",
            conn.cursors[0].executed[0][0].lower(),
        )


from semantic_embedder import (
    ALLOWED_FILE_KINDS,
    build_semantic_profile_text,
)


class BuildSemanticProfileTextTests(unittest.TestCase):


    def test_passport_profile_includes_all_three_legs(self):
                                                                  
                                                                     
        text = build_semantic_profile_text(
            saved_name="passport",
            asset_type="id_image",
            doc_type="passport",
            doc_family="identity_document",
            tags=["identity", "government", "travel"],
            file_name="scan.pdf",
        )
        for needle in (
            "passport",                                           
            "id_image",                      
            "identity_document",         
            "identity",               
            "government",             
            "travel",                 
            "scan.pdf",                     
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_dedupes_repeats(self):
                                                                       
        text = build_semantic_profile_text(
            saved_name="passport",
            doc_type="passport",
        )
        self.assertEqual(text.count("passport"), 1)

    def test_lowercases_everything(self):
                                                                   
                                                           
        text = build_semantic_profile_text(
            saved_name="My Passport",
            tags=["Identity"],
        )
        self.assertNotIn("My Passport", text)
        self.assertIn("my passport", text)

    def test_skips_none_and_empty(self):
                                        
        text = build_semantic_profile_text(
            saved_name="vibing",
            asset_type=None,
            doc_type="",
            tags=[],
        )
        self.assertEqual(text, "vibing")

    def test_returns_empty_when_nothing_to_embed(self):
                                                                   
                                                
        self.assertEqual(build_semantic_profile_text(), "")

    def test_allowed_file_kinds_includes_semantic_profile(self):
                                                                    
                                                             
        self.assertIn("semantic_profile", ALLOWED_FILE_KINDS)


class ScoreHybridMatchTests(unittest.TestCase):


    def test_exact_saved_name_match_outranks_vector_only(self):
                                                               
                                                               
        exact = main.score_hybrid_match(
            query_lower="drivers license",
            candidate_saved_name="drivers license",
            candidate_doc_type="driver_license",
            candidate_doc_family="identity_document",
            candidate_tags=["identity", "government"],
            query_doc_type="driver_license",
            query_tags=[],
            vector_score=0.0,
        )
        vec_only = main.score_hybrid_match(
            query_lower="drivers license",
            candidate_saved_name="something_else",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=[],
            query_doc_type=None,
            query_tags=[],
            vector_score=0.85,
        )
        self.assertGreater(exact["score"], vec_only["score"])
        self.assertIn("exact_name", exact["reasons"])
        self.assertIn("vector:0.85", vec_only["reasons"])

    def test_doc_type_match_boosts_when_no_exact_name(self):
                                                                 
                                                                      
        out = main.score_hybrid_match(
            query_lower="show my driver's license",
            candidate_saved_name="dl photo",
            candidate_doc_type="driver_license",
            candidate_doc_family="identity_document",
            candidate_tags=["identity", "government"],
            query_doc_type="driver_license",
            query_tags=[],
            vector_score=0.0,
        )
        self.assertIn("doc_type", out["reasons"])
        self.assertGreaterEqual(out["score"], main.HYBRID_MIN_SCORE)

    def test_family_match_when_only_query_doc_type_differs(self):
                                                                   
                                                   
        out = main.score_hybrid_match(
            query_lower="show my ids",
            candidate_saved_name="passport",
            candidate_doc_type="passport",
            candidate_doc_family="identity_document",
            candidate_tags=["identity", "government", "travel"],
            query_doc_type="id_card",                            
            query_tags=["identity"],                                      
            vector_score=0.0,
        )
                                                                           
                                                                      
        self.assertIn("doc_family", out["reasons"])
        self.assertGreater(out["score"], 0.0)

    def test_tag_overlap_scales_with_count_then_caps(self):
                                                                    
                                                                     
        one = main.score_hybrid_match(
            query_lower="x",
            candidate_saved_name="x",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=["identity"],
            query_doc_type=None,
            query_tags=["identity"],
        )
        two = main.score_hybrid_match(
            query_lower="x",
            candidate_saved_name="x",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=["identity", "government"],
            query_doc_type=None,
            query_tags=["identity", "government"],
        )
                                                                   
                                                
        self.assertGreater(two["score"], one["score"])
                                                           
        cap = main.score_hybrid_match(
            query_lower="x",
            candidate_saved_name="x",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=["a", "b", "c", "d"],
            query_doc_type=None,
            query_tags=["a", "b", "c", "d"],
        )
                                                                 
                                       
        tag_only_score = cap["score"] - main.EXACT_NAME_WEIGHT
        self.assertAlmostEqual(tag_only_score, main.TAG_WEIGHT_MAX, places=4)

    def test_vector_only_match_still_scores_when_above_threshold(self):
                                                                    
                                                               
        out = main.score_hybrid_match(
            query_lower="something_specific",
            candidate_saved_name="random",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=[],
            query_doc_type=None,
            query_tags=[],
            vector_score=0.9,
        )
        self.assertGreater(out["score"], 0.0)
        self.assertEqual(out["reasons"], ["vector:0.90"])

    def test_empty_inputs_score_zero(self):
        out = main.score_hybrid_match(
            query_lower="",
            candidate_saved_name=None,
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=None,
            query_doc_type=None,
            query_tags=None,
            vector_score=0.0,
        )
        self.assertEqual(out["score"], 0.0)
        self.assertEqual(out["reasons"], [])

    def test_min_score_constant_used_in_hybrid_retrieve(self):
                                                                     
                                                 
        self.assertTrue(0.0 < main.HYBRID_MIN_SCORE < main.EXACT_NAME_WEIGHT)


class ExtractQueryTagsTests(unittest.TestCase):
    def test_show_government_documents_picks_government(self):
        tags = main.extract_query_tags("show government documents")
        self.assertIn("government", tags)

    def test_show_my_ids_picks_identity(self):
                                                                    
                                                                  
        tags = main.extract_query_tags("show my ids")
        self.assertIn("identity", tags)

    def test_finance_tag_fires_on_finance_or_finances(self):
        self.assertIn("finance",
                      main.extract_query_tags("my finance documents"))
        self.assertIn("finance",
                      main.extract_query_tags("my finances"))

    def test_no_false_positive_on_substring(self):
                                                                       
        self.assertNotIn(
            "media",
            main.extract_query_tags("intermediate report"),
        )

    def test_empty_query_returns_empty(self):
        self.assertEqual(main.extract_query_tags(""), [])
        self.assertEqual(main.extract_query_tags(None), [])


class MigrationSemanticProfileShapeTests(unittest.TestCase):
    def test_migration_0028_adds_semantic_profile_to_check(self):
                                                                        
                                                                      
        import pathlib
        path = (
            pathlib.Path(__file__).parent
            / "migrations" / "versions"
            / "0001_baseline_vaultid.py"
        )
        self.assertTrue(path.exists(), "baseline migration file missing")
        src = path.read_text()
        self.assertIn("'semantic_profile'", src)
        for kind in (
            "'file_name'", "'saved_name'", "'asset_type'",
            "'detected_service'", "'item_service'", "'item_type'",
        ):
            with self.subTest(kind=kind):
                self.assertIn(kind, src)


from datetime import datetime


class ExtractQueryEntitiesTests(unittest.TestCase):


    def test_country_nigeria_extracted(self):
                                                                      
                
        out = main.extract_query_entities("show the passport from Nigeria")
        kinds_vals = {(e["kind"], e["value"]) for e in out}
        self.assertIn(("country", "nigeria"), kinds_vals)

    def test_state_california_extracted(self):
                                                                     
                                                                 
        out = main.extract_query_entities(
            "show my California driver's license"
        )
        kinds_vals = {(e["kind"], e["value"]) for e in out}
        self.assertIn(("state", "california"), kinds_vals)

    def test_freeform_walmart_extracted(self):
                                                                 
                                                             
        out = main.extract_query_entities("show receipts from Walmart")
        kinds_vals = {(e["kind"], e["value"]) for e in out}
        self.assertIn(("freeform", "walmart"), kinds_vals)

    def test_freeform_london_extracted(self):
                                                               
        out = main.extract_query_entities("show the ID uploaded in London")
        kinds_vals = {(e["kind"], e["value"]) for e in out}
        self.assertIn(("freeform", "london"), kinds_vals)

                                                                        
    def test_explicit_year_extracted(self):
        out = main.extract_query_entities(
            "show receipts from 2024"
        )
        years = {e["value"] for e in out if e["kind"] == "year"}
        self.assertIn("2024", years)

    def test_relative_last_year_extracted_against_now(self):
                                                                 
                                    
        out = main.extract_query_entities(
            "show documents from last year",
            now=datetime(2026, 1, 15),
        )
        years = {e["value"] for e in out if e["kind"] == "year"}
        self.assertIn("2025", years)

    def test_relative_this_year_and_next_year(self):
                                             
        this_year = main.extract_query_entities(
            "show documents from this year",
            now=datetime(2026, 6, 1),
        )
        next_year = main.extract_query_entities(
            "show documents from next year",
            now=datetime(2026, 6, 1),
        )
        self.assertIn(
            "2026",
            {e["value"] for e in this_year if e["kind"] == "year"},
        )
        self.assertIn(
            "2027",
            {e["value"] for e in next_year if e["kind"] == "year"},
        )

                                                                        
    def test_freeform_drops_stopwords(self):
                                                                       
                                                                   
        out = main.extract_query_entities(
            "show documents from the receipt last year",
            now=datetime(2026, 1, 1),
        )
        freeform = {
            e["value"] for e in out if e["kind"] == "freeform"
        }
        for stop in ("the", "the receipt", "last", "last year"):
            self.assertNotIn(stop, freeform)

    def test_freeform_does_not_duplicate_country_or_state(self):
                                                                     
                                                         
        out = main.extract_query_entities("show the passport from Nigeria")
        countries = {(e["kind"], e["value"]) for e in out
                     if e["kind"] == "country"}
        freeforms = {(e["kind"], e["value"]) for e in out
                     if e["kind"] == "freeform"}
        self.assertIn(("country", "nigeria"), countries)
        self.assertNotIn(("freeform", "nigeria"), freeforms)

                                                                       
    def test_country_carries_country_candidate_key(self):
                                                                     
                                                                  
        out = main.extract_query_entities("from Nigeria")
        country_entries = [e for e in out if e["kind"] == "country"]
        self.assertTrue(country_entries)
        self.assertIn("country", country_entries[0]["candidate_keys"])

    def test_freeform_carries_merchant_and_location_candidate_keys(self):
                                                                 
                              
        out = main.extract_query_entities("from Walmart")
        freeform_entries = [e for e in out if e["kind"] == "freeform"]
        self.assertTrue(freeform_entries)
        keys = freeform_entries[0]["candidate_keys"]
        self.assertIn("merchant", keys)
        self.assertIn("location", keys)

                                                                       
    def test_empty_returns_empty(self):
        self.assertEqual(main.extract_query_entities(""), [])
        self.assertEqual(main.extract_query_entities(None), [])
        self.assertEqual(main.extract_query_entities("   "), [])


class EntityLegPrecedenceTests(unittest.TestCase):
    def test_entity_match_outranks_vector_only(self):
                                                                     
                                                            
        nigeria = main.score_hybrid_match(
            query_lower="passport from nigeria",
            candidate_saved_name="passport",
            candidate_doc_type="passport",
            candidate_doc_family="identity_document",
            candidate_tags=["identity", "government", "travel"],
            query_doc_type="passport",
            query_tags=["identity", "government", "travel"],
            vector_score=0.0,
            entity_matches=1,
            matched_entity_values=["Nigeria"],
        )
        vec_only = main.score_hybrid_match(
            query_lower="passport from nigeria",
            candidate_saved_name="random_file",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=[],
            query_doc_type="passport",
            query_tags=["identity", "government", "travel"],
            vector_score=0.9,
            entity_matches=0,
        )
        self.assertGreater(nigeria["score"], vec_only["score"])

    def test_entity_match_reasons_include_matched_values(self):
        out = main.score_hybrid_match(
            query_lower="receipts from walmart",
            candidate_saved_name="electricity bill",
            candidate_doc_type="receipt",
            candidate_doc_family="financial_document",
            candidate_tags=["finance", "receipt"],
            query_doc_type="receipt",
            query_tags=["receipt"],
            vector_score=0.0,
            entity_matches=1,
            matched_entity_values=["Walmart"],
        )
                                                                   
                                               
        joined = " ".join(out["reasons"])
        self.assertIn("entities", joined)
        self.assertIn("Walmart", joined)

    def test_entity_match_caps_at_max(self):
                                                                    
        many = main.score_hybrid_match(
            query_lower="x",
            candidate_saved_name="something_else",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=[],
            query_doc_type=None,
            query_tags=[],
            vector_score=0.0,
            entity_matches=10,
            matched_entity_values=["a"] * 10,
        )
        exact = main.score_hybrid_match(
            query_lower="x",
            candidate_saved_name="x",
            candidate_doc_type=None,
            candidate_doc_family=None,
            candidate_tags=[],
            query_doc_type=None,
            query_tags=[],
            vector_score=0.0,
            entity_matches=0,
        )
        self.assertLessEqual(
            many["score"], exact["score"] + main.ENTITY_WEIGHT_MAX,
        )
                                                                      
                            
        self.assertAlmostEqual(many["score"], main.ENTITY_WEIGHT_MAX, places=4)

    def test_entity_constants_in_expected_range(self):
                                                                
                                                     
        self.assertGreater(
            main.ENTITY_WEIGHT_PER_MATCH * 2, main.VECTOR_WEIGHT,
            "Two entity matches must outrank a perfect vector hit "
            "(spec: entities before vector).",
        )
        self.assertLessEqual(main.ENTITY_WEIGHT_MAX, main.EXACT_NAME_WEIGHT)


class HybridRetrieveEntityLegSqlTests(unittest.TestCase):


    def setUp(self):
                                                                    
                                      
        self.executed: list[tuple[str, tuple]] = []

        class StubCursor:
            def __init__(self_inner):
                self_inner._rows = []

            def execute(self_inner, sql, params=None):
                self.executed.append((sql, params or ()))
                                                              
                                                        
                self_inner._rows = []

            def fetchall(self_inner):
                return list(self_inner._rows)

            def fetchone(self_inner):
                return None

            def close(self_inner):
                pass

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        class StubConn:
            def cursor(self_inner, cursor_factory=None):
                return StubCursor()

            def commit(self_inner):
                pass

            def close(self_inner):
                pass

        self._stub_conn = StubConn

    def _patch_main_get_db(self):
        original = main.get_db
        main.get_db = lambda: self._stub_conn()
        return original

    def _restore(self, original):
        main.get_db = original

                                                                        
    VAULT_ID = "00000000-0000-4000-8000-0000000000d1"

    def test_entity_pass_runs_when_query_has_entities(self):
                                                                     
                                              
        import asyncio
        original = self._patch_main_get_db()
        try:
            asyncio.run(main.hybrid_retrieve_files(
                self.VAULT_ID,
                "show the passport from Nigeria",
                limit=5,
            ))
        finally:
            self._restore(original)

                                                            
        entity_sql = [
            sql for (sql, _params) in self.executed
            if "vault_document_entities" in sql.lower()
        ]
        self.assertTrue(
            entity_sql,
            "entity SQL leg must run when extract_query_entities "
            "returns at least one spec",
        )
                                                                    
                      
        joined = " ".join(s.lower() for s in entity_sql)
        self.assertIn("group by source_file_id", joined)
        self.assertIn("count(*)", joined)
        self.assertIn("array_agg(distinct entity_value)", joined)

    def test_entity_pass_skipped_when_no_query_entities(self):
                                                                    
                                    
        import asyncio
        original = self._patch_main_get_db()
        try:
            asyncio.run(main.hybrid_retrieve_files(
                self.VAULT_ID,
                "vibing",
                limit=5,
            ))
        finally:
            self._restore(original)

        entity_sql = [
            sql for (sql, _params) in self.executed
            if "vault_document_entities" in sql.lower()
        ]
        self.assertEqual(
            entity_sql, [],
            "entity SQL leg must NOT run when the query has no "
            "entity-shaped tokens",
        )

    def test_year_predicate_uses_like(self):
                                                               
                                                
        import asyncio
        original = self._patch_main_get_db()
        try:
            asyncio.run(main.hybrid_retrieve_files(
                self.VAULT_ID,
                "show receipts from 2024",
                limit=5,
            ))
        finally:
            self._restore(original)

        entity_sqls = [
            (sql, params) for (sql, params) in self.executed
            if "vault_document_entities" in sql.lower()
        ]
        self.assertTrue(entity_sqls)
        sql, params = entity_sqls[0]
        self.assertIn("entity_value like", sql.lower())
                                    
        self.assertIn("2024%", params)


if __name__ == "__main__":
    unittest.main()
