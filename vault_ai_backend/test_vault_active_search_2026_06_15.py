

from __future__ import annotations

import json
import unittest
from unittest import mock

import vault_knowledge_tools as vkt
import vault_person_document_lookup as vpdl
from vault_chat_safety_sanitizer import (
    SENTENCE_VAULT_LOCKED,
)
from vault_person_document_lookup import (
    DOC_KIND_GENERIC,
    DOC_KIND_ID_CARD,
    DOC_KIND_PASSPORT,
    detect_person_document_query,
    handle_person_document_query,
)


_KEY = b"\x77" * 32


class ClassifierCatchesOwnerPhrasings(unittest.TestCase):
    def test_find_me_photo_id_card_owner_is_louis_iodato(self):
                                         
        q = detect_person_document_query(
            "find me a photo ID card the owner of the ID "
            "is Louis Iodato"
        )
        self.assertIsNotNone(
            q,
            msg="The operator's exact phrasing must classify as a "
                "person-document query.",
        )
        self.assertIn("Louis", q.person_name)
        self.assertIn("Iodato", q.person_name)
                                                               
                                                          
        self.assertIn(
            q.doc_kind_hint,
            (DOC_KIND_ID_CARD, DOC_KIND_GENERIC),
        )

    def test_find_me_photo_id_whose_owner_is_x(self):
        q = detect_person_document_query(
            "find me a photo ID whose owner is Jane Doe"
        )
        self.assertIsNotNone(q)
        self.assertIn("Jane", q.person_name)
        self.assertIn("Doe", q.person_name)

    def test_id_card_belonging_to_x(self):
        q = detect_person_document_query(
            "show me an ID card belonging to Louis Iodato"
        )
        self.assertIsNotNone(q)
        self.assertIn("Louis", q.person_name)
        self.assertIn("Iodato", q.person_name)

    def test_find_document_containing_x(self):
        q = detect_person_document_query(
            "find document containing Louis Iodato"
        )
        self.assertIsNotNone(q)
        self.assertIn("Louis", q.person_name)
        self.assertIn("Iodato", q.person_name)

    def test_possessive_phrasing(self):
        q = detect_person_document_query(
            "show me Louis Iodato's passport"
        )
        self.assertIsNotNone(q)
        self.assertEqual(q.doc_kind_hint, DOC_KIND_PASSPORT)
                                                                 
                                                          
        self.assertIn("Louis", q.person_name)

    def test_unrelated_messages_still_return_none(self):
                                                                   
        for msg in (
            "good morning",
            "what's in my vault",
            "create a username and password for chase",
            "list my files",
        ):
            with self.subTest(msg=msg):
                self.assertIsNone(detect_person_document_query(msg))


def _patch_understanding_query(rows):

    return mock.patch.object(
        vpdl, "_query_matching_files", return_value=rows,
    )


def _patch_coverage(total, analyzed, pending=0):
    return mock.patch(
        "vault_analysis.analysis_coverage_for_vault",
        return_value={
            "total":      total,
            "analyzed":   analyzed,
            "pending":    pending,
            "processing": 0,
            "failed":     0,
            "unsupported": 0,
        },
    )


class HandlerBroadFallbackTests(unittest.TestCase):
    def test_falls_back_to_identity_when_understanding_empty(self):
                                                              
                                                                  
        identity_hits = [{
            "file_id":       "f-ident-1",
            "file_name":     "louis_iodato_id.pdf",
            "saved_name":    "louis_iodato_id.pdf",
            "relative_path": "/IDs/",
            "match_source":  "identity",
        }]
        with _patch_understanding_query([]), _patch_coverage(
            total=5, analyzed=5,
        ), mock.patch.object(
            vpdl, "_search_identity_columns",
            return_value=identity_hits,
        ), mock.patch.object(
            vpdl, "_search_extracted_text", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_content_chunks", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_any_understanding", return_value=[],
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("Louis Iodato", reply)
        self.assertIn("louis_iodato_id.pdf", reply)
                                                
        self.assertNotIn("couldn't find", reply)
                                 
        self.assertNotIn("{", reply)
        self.assertNotIn('"error"', reply)

    def test_falls_back_to_extracted_text(self):
        extracted_hits = [{
            "file_id":       "f-ext-1",
            "file_name":     "scan42.pdf",
            "saved_name":    "scan42.pdf",
            "relative_path": "/Mixed/",
            "match_source":  "extracted_text",
        }]
        with _patch_understanding_query([]), _patch_coverage(
            total=5, analyzed=5,
        ), mock.patch.object(
            vpdl, "_search_identity_columns", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_extracted_text",
            return_value=extracted_hits,
        ), mock.patch.object(
            vpdl, "_search_content_chunks", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_any_understanding", return_value=[],
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("scan42.pdf", reply)
        self.assertNotIn("couldn't find", reply)

    def test_falls_back_to_content_chunks(self):
        chunk_hits = [{
            "file_id":       "f-chunk-1",
            "file_name":     "id_back.jpg",
            "saved_name":    "id_back.jpg",
            "relative_path": "/Photos/",
            "match_source":  "content_chunk",
        }]
        with _patch_understanding_query([]), _patch_coverage(
            total=5, analyzed=5,
        ), mock.patch.object(
            vpdl, "_search_identity_columns", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_extracted_text", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_content_chunks", return_value=chunk_hits,
        ), mock.patch.object(
            vpdl, "_search_any_understanding", return_value=[],
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("id_back.jpg", reply)
        self.assertNotIn("couldn't find", reply)

    def test_falls_back_to_any_understanding_entities(self):
        ent_hits = [{
            "file_id":       "f-ent-1",
            "file_name":     "contract.pdf",
            "saved_name":    "contract.pdf",
            "relative_path": "/Legal/",
            "match_source":  "understanding_entities",
        }]
        with _patch_understanding_query([]), _patch_coverage(
            total=5, analyzed=5,
        ), mock.patch.object(
            vpdl, "_search_identity_columns", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_extracted_text", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_content_chunks", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_any_understanding", return_value=ent_hits,
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_GENERIC,
            )
        self.assertIn("contract.pdf", reply)
        self.assertNotIn("couldn't find", reply)

    def test_incomplete_coverage_reports_still_scanning(self):
                                                                  
                                                             
        with _patch_understanding_query([]), _patch_coverage(
            total=425, analyzed=244, pending=181,
        ), mock.patch.object(
            vpdl, "_search_identity_columns", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_extracted_text", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_content_chunks", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_any_understanding", return_value=[],
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
                                       
        self.assertNotIn("couldn't find", reply.lower())
                                               
        self.assertIn("244", reply)
        self.assertIn("425", reply)
                                          
        self.assertTrue(
            "continuing" in reply.lower() or "scan" in reply.lower(),
            msg=f"Active-lookup phrasing missing: {reply!r}",
        )
                                                  
        self.assertNotIn("where", reply.lower())

    def test_complete_coverage_with_no_matches_is_hard_not_found(self):
                                                                 
        with _patch_understanding_query([]), _patch_coverage(
            total=5, analyzed=5,
        ), mock.patch.object(
            vpdl, "_search_identity_columns", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_extracted_text", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_content_chunks", return_value=[],
        ), mock.patch.object(
            vpdl, "_search_any_understanding", return_value=[],
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("couldn't find", reply.lower())
        self.assertIn("Louis Iodato", reply)


class SearchVaultContentSchemaTests(unittest.TestCase):
    def test_no_reference_to_brain_chunks_typo(self):
                                                                 
                                                    
        with open(
            "vault_knowledge_tools.py", "r", encoding="utf-8",
        ) as f:
            src = f.read()
        self.assertNotIn(
            "FROM brain_chunks",
            src,
            msg="search_vault_content must query "
                "vault_content_chunks, not the broken "
                "brain_chunks reference.",
        )

    def test_queries_real_vault_content_chunks_table(self):
        with open(
            "vault_knowledge_tools.py", "r", encoding="utf-8",
        ) as f:
            src = f.read()
        self.assertIn("FROM vault_content_chunks", src)

    def test_searches_multiple_sources_not_just_chunks(self):
        with open(
            "vault_knowledge_tools.py", "r", encoding="utf-8",
        ) as f:
            src = f.read()
                                                                    
        self.assertIn(
            "_list_uploaded_files_for_credential_search", src,
        )
                                                          
        self.assertIn("vault_file_understanding", src)
                                                             
        self.assertIn("list_uploaded_files", src)


class SearchVaultContentLockedKeyTests(unittest.TestCase):
    def test_short_key_returns_vault_locked_envelope(self):
        out = vkt.search_vault_content(
            vault_id="v-1", key=b"short", query="anything",
        )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "vault_locked")

    def test_empty_query_returns_empty_query_envelope(self):
        out = vkt.search_vault_content(
            vault_id="v-1", key=_KEY, query="   ",
        )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "empty_query")


class SystemPromptForbidsCantSearchPhrasing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("tools.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_forbidden_phrase_listed_in_prompt(self):
                                                                   
                           
        self.assertIn(
            "I can't search the contents", self._src,
        )
                                                              
                                                        
        forbidden_idx = self._src.find("I can't search the contents")
        nearby = self._src[
            max(0, forbidden_idx - 200): forbidden_idx + 200
        ]
        self.assertTrue(
            "FORBIDDEN" in nearby or "NEVER" in nearby.upper(),
            msg="The forbidden phrasing must be marked as a "
                "hard rule, not just mentioned.",
        )

    def test_search_vault_content_is_directed_for_named_lookups(self):
                                                                     
                                            
        self.assertIn("search_vault_content", self._src)
                                                              
        for phrase in ("photo ID", "passport", "owner"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self._src)

    def test_active_scan_phrasing_is_documented(self):
                                                              
                                                                  
        self.assertIn("still in progress", self._src)
        self.assertIn("reviewed", self._src)

    def test_vault_locked_and_unavailable_handling_documented(self):
                                        
        self.assertIn("vault_locked", self._src)
        self.assertIn("unavailable", self._src)


class VaultScopingGuard(unittest.TestCase):
    def test_broad_search_signatures_require_vault_id(self):
                                                              
                                                             
        import inspect
        for fn in (
            vpdl._search_identity_columns,
            vpdl._search_extracted_text,
            vpdl._search_content_chunks,
            vpdl._search_any_understanding,
            vpdl._gather_broad_matches,
        ):
            params = list(inspect.signature(fn).parameters.keys())
            self.assertEqual(
                params[0], "vault_id",
                msg=f"{fn.__name__} must take vault_id first.",
            )


class LockedKeyBypassesBroadSearch(unittest.TestCase):
    def test_locked_key_returns_locked_sentence_immediately(self):
                                                                    
                                                       
        with mock.patch.object(
            vpdl, "_gather_broad_matches",
            side_effect=AssertionError(
                "broad search must not run when locked"
            ),
        ):
            reply = handle_person_document_query(
                vault_id="v-1", key=b"short",
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertEqual(reply, SENTENCE_VAULT_LOCKED)


class HandlerNeverEmitsForbiddenPhrasings(unittest.TestCase):
    _FORBIDDEN = (
        "I can't search the contents",
        "I cannot search the contents",
        "If you know where",
    )

    def _patch_all_empty(self, total, analyzed):
        return [
            _patch_understanding_query([]),
            _patch_coverage(total=total, analyzed=analyzed,
                            pending=max(0, total - analyzed)),
            mock.patch.object(
                vpdl, "_search_identity_columns", return_value=[],
            ),
            mock.patch.object(
                vpdl, "_search_extracted_text", return_value=[],
            ),
            mock.patch.object(
                vpdl, "_search_content_chunks", return_value=[],
            ),
            mock.patch.object(
                vpdl, "_search_any_understanding", return_value=[],
            ),
        ]

    def _replies_in_both_coverage_states(self):
        out = []
                              
        patches = self._patch_all_empty(total=425, analyzed=244)
        try:
            for p in patches:
                p.start()
            out.append(handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            ))
        finally:
            for p in patches:
                p.stop()
                            
        patches = self._patch_all_empty(total=5, analyzed=5)
        try:
            for p in patches:
                p.start()
            out.append(handle_person_document_query(
                vault_id="v-1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            ))
        finally:
            for p in patches:
                p.stop()
        return out

    def test_replies_never_use_forbidden_phrasing(self):
        for reply in self._replies_in_both_coverage_states():
            for bad in self._FORBIDDEN:
                with self.subTest(reply=reply, bad=bad):
                    self.assertNotIn(bad, reply)


if __name__ == "__main__":
    unittest.main()
