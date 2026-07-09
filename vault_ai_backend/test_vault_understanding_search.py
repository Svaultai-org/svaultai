

from __future__ import annotations

import inspect
import json
import unittest

import vault_understanding_search as vus
import vault_document_purpose as vp


def _row(
    *,
    file_id,
    file_name="x.pdf",
    saved_name="",
    relative_path="",
    content_type="application/pdf",
    asset_type="file",
    extracted_text=None,
    extracted_text_encrypted=False,
    understanding_status="ready",
    document_purpose=None,
    purpose_label=None,
    summary_encrypted=None,
    safe_preview_encrypted=None,
    topics=None,
    entities=None,
    dates=None,
    categories=None,
    searchable_terms=None,
):
    return {
        "file_id":                  file_id,
        "file_name":                file_name,
        "saved_name":               saved_name,
        "relative_path":            relative_path,
        "content_type":             content_type,
        "asset_type":               asset_type,
        "extracted_text":           extracted_text,
        "extracted_text_encrypted": extracted_text_encrypted,
        "understanding_status":     understanding_status,
        "document_purpose":         document_purpose,
        "purpose_label":            purpose_label,
        "summary_encrypted":        summary_encrypted,
        "safe_preview_encrypted":   safe_preview_encrypted,
        "topics_jsonb":             topics or [],
        "entities_jsonb":           entities or {"names": [], "email_domains": []},
        "dates_jsonb":              dates or [],
        "detected_categories_jsonb": categories or [],
        "searchable_terms_jsonb":   searchable_terms or [],
    }


def _wells_fargo_row():
    return _row(
        file_id="wf",
        file_name="january_statement.pdf",                                     
        saved_name="January Statement",
        document_purpose=vp.PURPOSE_GENERIC_TEXT,
        purpose_label="",
        topics=["finance"],
        entities={
            "names": ["Wells Fargo", "Wells Fargo Bank Statement"],
            "email_domains": ["wellsfargo.com"],
        },
        dates=["2024-01-01", "2024-01-31"],
        categories=["finance"],
        searchable_terms=[
            "wells fargo", "wells fargo bank statement",
            "finance", "wellsfargo.com",
        ],
    )


def _maureen_recipe_row():
    return _row(
        file_id="recipe",
        file_name="pumpkin.txt",
        saved_name="Pumpkin Pie",
        document_purpose=vp.PURPOSE_GENERIC_TEXT,
        topics=[],
        entities={
            "names": ["Maureen"],
            "email_domains": [],
        },
        dates=["2023-12-15"],
        categories=[],
        searchable_terms=["maureen", "pumpkin"],
    )


def _tax_1040_row():
    return _row(
        file_id="tax",
        file_name="1040-2024.pdf",
        saved_name="2024 Tax Return",
        document_purpose=vp.PURPOSE_GOVERNMENT_LEGAL,
        purpose_label="a government, legal, or financial document",
        topics=["taxes"],
        entities={"names": ["Internal Revenue Service"]},
        dates=["2024-04-15"],
        categories=["tax", "finance"],
        searchable_terms=["taxes", "irs", "1040"],
    )


def _saved_login_row():
    return _row(
        file_id="logins",
        file_name="my_notes.txt",                                   
        saved_name="My Notes",
        document_purpose=vp.PURPOSE_SAVED_LOGIN_LIST,
        purpose_label="saved website/app login records",
        topics=["credentials"],
        entities={"names": []},
        categories=["security"],
        searchable_terms=["saved_login_list", "security", "credentials"],
    )


def _credential_export_row():
    return _row(
        file_id="csv",
        file_name="export.csv",
        document_purpose=vp.PURPOSE_CREDENTIAL_EXPORT,
        purpose_label="a password-manager export",
        topics=["credentials"],
        categories=["security"],
        searchable_terms=["credential_export"],
    )


def _filename_only_wells_row():


    return _row(
        file_id="filename_only",
        file_name="wells-cathedral-photo.jpg",                     
        saved_name="Wells Cathedral",
        document_purpose=vp.PURPOSE_GENERIC_TEXT,
        topics=[],
        entities={"names": []},
        categories=[],
        searchable_terms=[],
    )


def _no_understanding_filename_match_row():


    return _row(
        file_id="orphan",
        file_name="wells-cathedral-photo.jpg",
        understanding_status=None,
        document_purpose=None,
    )


def _pending_understanding_row():


    return _row(
        file_id="pending",
        file_name="placeholder.pdf",
        understanding_status="pending",
        document_purpose=None,
    )


class TierOrderTests(unittest.TestCase):
    def test_entity_match_beats_filename_match(self):


        wf = _wells_fargo_row()
        fn = _filename_only_wells_row()
                                                                
                    
        wf_match = vus._score_row(
            row=wf, query_low="wells fargo",
            query_tokens=["wells", "fargo"],
            purpose_hints=[],
            category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        fn_match = vus._score_row(
            row=fn, query_low="wells fargo",
            query_tokens=["wells", "fargo"],
            purpose_hints=[],
            category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(wf_match)
        self.assertIsNotNone(fn_match)
        self.assertEqual(wf_match["match_type"], "entity")
        self.assertEqual(fn_match["match_type"], "filename")
        self.assertLess(
            wf_match["tier"], fn_match["tier"],
            "entity tier (2) MUST beat filename tier (10)",
        )

    def test_purpose_match_beats_entity_topic_filename(self):


        row = _saved_login_row()
        m = vus._score_row(
            row=row, query_low="saved login",
            query_tokens=["saved", "login"],
            purpose_hints=[
                vp.PURPOSE_SAVED_LOGIN_LIST,
                vp.PURPOSE_CREDENTIAL_EXPORT,
            ],
            category_hints=[],
            topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "purpose")
        self.assertEqual(m["tier"], vus.TIER_PURPOSE)


class QueryParsingTests(unittest.TestCase):
    def test_tokenize_strips_stops(self):
        toks = vus._tokenize_query(
            "find files about wells fargo and chase"
        )
                                                                
        self.assertIn("wells", toks)
        self.assertIn("fargo", toks)
        self.assertIn("chase", toks)
        self.assertNotIn("find", toks)
        self.assertNotIn("files", toks)
        self.assertNotIn("about", toks)
        self.assertNotIn("and", toks)

    def test_purpose_hints_from_query(self):
        for phrase, expected in (
            ("find saved-login files",
             vp.PURPOSE_SAVED_LOGIN_LIST),
            ("password manager export",
             vp.PURPOSE_CREDENTIAL_EXPORT),
            ("show me api keys",
             vp.PURPOSE_CONFIG_SECRETS),
            ("any insurance form",
             vp.PURPOSE_INSURANCE_FORM),
        ):
            hints = vus._purpose_hints_from_query(phrase.lower())
            self.assertIn(expected, hints,
                f"phrase {phrase!r} should hint at {expected}")

    def test_category_hints_from_query(self):
        for phrase, expected in (
            ("show me tax documents", "tax"),
            ("any travel files", "travel"),
            ("legal stuff", "legal"),
            ("medical paperwork", "medical"),
            ("show insurance forms", "insurance"),
        ):
            hints = vus._category_hints_from_query(phrase.lower())
            self.assertIn(expected, hints, phrase)

    def test_topic_hints_from_query(self):
        for phrase, expected in (
            ("anything about taxes", "taxes"),
            ("docs about travel", "travel"),
            ("finance documents", "finance"),
        ):
            self.assertIn(
                expected, vus._topic_hints_from_query(phrase.lower()),
                phrase,
            )

    def test_date_hint_from_query(self):
        self.assertEqual(
            vus._date_hint_from_query("any files dated 2024-01-01"),
            "2024-01-01",
        )
        self.assertIsNone(
            vus._date_hint_from_query("any files about Wells Fargo")
        )


class ScorerFireRightTierTests(unittest.TestCase):
    def test_wells_fargo_query_fires_entity_tier(self):
        m = vus._score_row(
            row=_wells_fargo_row(), query_low="wells fargo",
            query_tokens=["wells", "fargo"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "entity")
        self.assertIn("Wells Fargo", m["match_reason"])

    def test_maureen_query_fires_entity_tier(self):
        m = vus._score_row(
            row=_maureen_recipe_row(), query_low="maureen",
            query_tokens=["maureen"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "entity")
        self.assertIn("Maureen", m["match_reason"])

    def test_tax_query_fires_category_tier(self):
        m = vus._score_row(
            row=_tax_1040_row(), query_low="tax documents",
            query_tokens=["tax"],
            purpose_hints=[],
            category_hints=["tax"],
            topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "category")
        self.assertIn("tax", m["match_reason"])

    def test_saved_login_query_fires_purpose_tier(self):
        m = vus._score_row(
            row=_saved_login_row(), query_low="saved login files",
            query_tokens=["saved", "login"],
            purpose_hints=[
                vp.PURPOSE_SAVED_LOGIN_LIST,
                vp.PURPOSE_CREDENTIAL_EXPORT,
            ],
            category_hints=[],
            topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "purpose")
        self.assertIn(
            "saved website/app login records", m["match_reason"],
        )

    def test_credential_export_query_fires_purpose_tier(self):
        m = vus._score_row(
            row=_credential_export_row(),
            query_low="password manager",
            query_tokens=["password", "manager"],
            purpose_hints=[vp.PURPOSE_CREDENTIAL_EXPORT],
            category_hints=[],
            topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "purpose")
        self.assertIn("password-manager", m["match_reason"])

    def test_date_query_fires_date_tier(self):
        m = vus._score_row(
            row=_wells_fargo_row(), query_low="2024-01-01",
            query_tokens=[],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint="2024-01-01", key=None,
        )
        self.assertIsNotNone(m)
                                                             
                                                             
        self.assertEqual(m["match_type"], "date")

    def test_term_match_fires_term_tier(self):
        m = vus._score_row(
            row=_wells_fargo_row(), query_low="finance",
            query_tokens=["finance"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
                                                                  
                                                       
        self.assertIn(m["match_type"], ("term", "topic", "category"))

    def test_filename_only_for_unrelated_file(self):
        m = vus._score_row(
            row=_filename_only_wells_row(),
            query_low="wells",
            query_tokens=["wells"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "filename")

    def test_no_match_returns_None(self):
        m = vus._score_row(
            row=_credential_export_row(),
            query_low="kangaroo",
            query_tokens=["kangaroo"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNone(m)


class ReasonShapeTests(unittest.TestCase):
    def test_explain_match_reason_returns_match_reason(self):
        result = {"match_reason": "entity match: Wells Fargo"}
        self.assertEqual(
            vus.explain_match_reason(result),
            "entity match: Wells Fargo",
        )

    def test_explain_match_reason_safe_on_garbage(self):
        self.assertEqual(vus.explain_match_reason(None), "")
        self.assertEqual(vus.explain_match_reason({}), "")
        self.assertEqual(vus.explain_match_reason("nope"), "")

    def test_purpose_match_reason_uses_label_when_present(self):
        m = vus._score_row(
            row=_saved_login_row(), query_low="saved login",
            query_tokens=["saved", "login"],
            purpose_hints=[vp.PURPOSE_SAVED_LOGIN_LIST],
            category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIn("saved website/app login records",
                      m["match_reason"])

    def test_category_match_reason_includes_tag(self):
        m = vus._score_row(
            row=_tax_1040_row(), query_low="tax",
            query_tokens=["tax"],
            purpose_hints=[], category_hints=["tax"],
            topic_hints=[], date_hint=None, key=None,
        )
        self.assertEqual(m["match_reason"], "category match: tax")

    def test_entity_match_reason_includes_name(self):
        m = vus._score_row(
            row=_wells_fargo_row(), query_low="wells fargo",
            query_tokens=["wells", "fargo"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertTrue(m["match_reason"].startswith("entity match"))


class NoKeySkipsDecryptedTiersTests(unittest.TestCase):
    def test_summary_preview_content_tiers_skipped_when_key_is_None(self):
                                                                 
                                     
        row = _row(
            file_id="enc_only",
            file_name="orphan.pdf",
            document_purpose=vp.PURPOSE_GENERIC_TEXT,
            summary_encrypted="OPAQUE_CIPHERTEXT",
        )
        m = vus._score_row(
            row=row, query_low="anything",
            query_tokens=["anything"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNone(
            m,
            "without a key, summary / preview / content tiers MUST "
            "be skipped — they require decryption",
        )


class EnvelopeShapeTests(unittest.TestCase):
    def test_envelope_carries_match_metadata_per_row(self):
        import main
        env = json.loads(main._build_file_search_envelope(
            query="Wells Fargo",
            results=[{
                "file_id":     "wf",
                "file_name":   "statement.pdf",
                "saved_name":  "January Statement",
                "match_type":  "entity",
                "match_reason": "entity match: Wells Fargo",
                "confidence":  "strong",
                "purpose":     vp.PURPOSE_GENERIC_TEXT,
                "purpose_label": "",
            }],
            message="I found 1 file about \"Wells Fargo\"...",
            pending_count=2,
        ))
        self.assertEqual(env["type"], "file_search_results")
        self.assertEqual(env["query"], "Wells Fargo")
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["pending_count"], 2)
        row = env["results"][0]
        self.assertEqual(row["match_type"], "entity")
        self.assertEqual(row["match_reason"],
                         "entity match: Wells Fargo")
        self.assertEqual(row["match_confidence"], "strong")

    def test_envelope_never_carries_decrypted_summary_or_content(self):
                                                                    
                                                                   
        import main
        hostile = {
            "file_id":           "x",
            "file_name":         "x.pdf",
            "match_type":        "entity",
            "match_reason":      "entity match: X",
            "confidence":        "strong",
                                                
            "summary":             "secret summary",
            "safe_preview":        "secret preview",
            "extracted_text":      "secret content",
            "summary_encrypted":   "OPAQUE_CIPHER",
        }
        env = json.loads(main._build_file_search_envelope(
            query="x", results=[hostile], message="m",
        ))
        wire = json.dumps(env)
        self.assertNotIn("secret summary", wire)
        self.assertNotIn("secret preview", wire)
        self.assertNotIn("secret content", wire)
        self.assertNotIn("OPAQUE_CIPHER", wire)


class ChatHandlerWiringTests(unittest.TestCase):
    def test_intent_prompt_names_search_files_about(self):
        import main
        src = inspect.getsource(main.detect_vault_intent)
        self.assertIn("search_files_about", src)
        for phrase in (
            "find files about Wells Fargo",
            "show files about",
            "documents about",
            "find saved-login files",
        ):
            self.assertIn(phrase, src, phrase)

    def test_chat_handler_branch_exists(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn('intent == "search_files_about"', src)
                                                                
                                                            
        idx = src.find('intent == "search_files_about"')
        body = src[idx:idx + 2500]
        self.assertIn("search_vault_understanding", body)
        self.assertIn("_build_file_search_envelope", body)

    def test_branch_runs_before_analyze_file(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        s_idx = src.find('intent == "search_files_about"')
        a_idx = src.find('intent == "analyze_file"')
        self.assertGreater(s_idx, -1)
        self.assertGreater(a_idx, -1)
        self.assertLess(
            s_idx, a_idx,
            "search_files_about must come before analyze_file so "
            "a 'find files about ...' query never routes to "
            "single-file analysis",
        )


class PendingFilesHonestyTests(unittest.TestCase):
    def test_format_search_reply_mentions_pending_when_no_results(self):
        text = vus.format_search_reply(
            query="Maureen", results=[], pending_count=3,
        )
        self.assertIn("Maureen", text)
        self.assertIn("3", text)
                                                                   
                                                  
        self.assertIn("still being indexed", text)
        self.assertNotIn("try again in a moment", text)
        self.assertNotIn("ask again", text.lower())

    def test_format_search_reply_mentions_pending_with_results(self):
        text = vus.format_search_reply(
            query="Wells Fargo",
            results=[{
                "file_id":      "wf",
                "saved_name":   "January Statement",
                "match_reason": "entity match: Wells Fargo",
            }],
            pending_count=1,
        )
        self.assertIn("I found 1 file", text)
        self.assertIn("entity match: Wells Fargo", text)
        self.assertIn("1 file still being analyzed", text)

    def test_format_search_reply_no_results_no_pending(self):
        text = vus.format_search_reply(
            query="nothing", results=[], pending_count=0,
        )
        self.assertIn("didn't find", text)
        self.assertNotIn("still being analyzed", text)


class LogSafetyTests(unittest.TestCase):
    def test_search_module_does_not_log_plaintext(self):
                                                                  
                  
        src = inspect.getsource(vus)
        for forbidden in (
            'logger.info("%s", plain',
            'logger.info("%s", plaintext',
            'logger.warning("%s", plain',
            'logger.error("%s", plain',
            'print("%s" % plain',
        ):
            self.assertNotIn(forbidden, src)

    def test_search_module_never_executes_user_content(self):
        src = inspect.getsource(vus)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)


class SecondarySortTests(unittest.TestCase):
    def test_ranking_picks_strongest_tier_per_file(self):
                                                     
                                                                  
        results = [
            {                 
                "file_id": "a", "file_name": "wells.pdf",
                "tier": vus.TIER_FILENAME, "confidence": "weak",
                "match_type": "filename",
                "match_reason": "filename match: wells.pdf",
                "saved_name": "Wells",
            },
            {                            
                "file_id": "b", "file_name": "statement.pdf",
                "tier": vus.TIER_ENTITY, "confidence": "strong",
                "match_type": "entity",
                "match_reason": "entity match: Wells Fargo",
                "saved_name": "January Statement",
            },
        ]
        confidence_order = {"strong": 0, "medium": 1, "weak": 2}
        ranked = sorted(
            results,
            key=lambda m: (
                int(m.get("tier") or vus.TIER_FILENAME),
                confidence_order.get(m.get("confidence"), 2),
                (m.get("saved_name") or m.get("file_name") or "").lower(),
            ),
        )
        self.assertEqual(ranked[0]["file_id"], "b")
        self.assertEqual(ranked[1]["file_id"], "a")


class EndToEndShapeTests(unittest.TestCase):
    def test_search_returns_zero_results_for_empty_query(self):
                                                             
        out = vus.search_vault_understanding(
            "vault-X", "", key=None, limit=10,
        )
        self.assertEqual(out["results"], [])
        self.assertEqual(out["pending_count"], 0)

    def test_search_returns_zero_results_for_whitespace_query(self):
        out = vus.search_vault_understanding(
            "vault-X", "   \n  ", key=None, limit=10,
        )
        self.assertEqual(out["results"], [])


if __name__ == "__main__":
    unittest.main()
