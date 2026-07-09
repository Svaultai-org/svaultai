

from __future__ import annotations

import json
import unittest
from typing import Optional
from unittest.mock import patch

import vault_complete_search as vcs
import vault_chat_result_cards as vcr


class TestTypoTolerance(unittest.TestCase):
    def test_phtos_is_recognised_as_id_class_keyword(self):
        self.assertTrue(vcs._is_id_class_keyword("phtos"))
        self.assertTrue(vcs._is_id_class_keyword("phots"))
        self.assertTrue(vcs._is_id_class_keyword("photoes"))

    def test_passport_typo_recognised(self):
                                                              
                                                                     
        self.assertTrue(vcs._is_id_class_keyword("passprot"))
        self.assertTrue(vcs._is_id_class_keyword("passports"))

    def test_license_typo_recognised(self):
        self.assertTrue(vcs._is_id_class_keyword("licnese"))
        self.assertTrue(vcs._is_id_class_keyword("lisence"))

    def test_short_tokens_remain_exact_match_only(self):
                                                                  
                                                               
        for noise in ("in", "it", "is", "of", "to"):
            with self.subTest(noise=noise):
                self.assertFalse(vcs._is_id_class_keyword(noise))

    def test_unrelated_long_tokens_rejected(self):
                                                                  
        for token in (
            "phone", "photoshop", "photographer",
            "physics", "phonics",
        ):
            with self.subTest(token=token):
                self.assertFalse(vcs._is_id_class_keyword(token))

    def test_filler_stopwords_stripped(self):
                                                               
                      
        for q, expected in [
            ("ok show me all the ID phtos in my vault", ""),
            ("okay where are my photos", ""),
            ("yeah find the passport for Louis", "louis"),
        ]:
            with self.subTest(q=q):
                kind = vcs._infer_doc_kind_from_query(q)
                self.assertEqual(kind, "id_photo")
                entity = vcs._extract_entity_from_query(
                    q, is_id_class_search=True,
                )
                self.assertEqual(entity, expected)


class TestEndToEndTypoRoutes(unittest.TestCase):


    def test_phtos_full_query_routes_to_broad_id_search(self):
        rows = [
            {
                "id": "jpg1", "content_type": "image/jpeg",
                "saved_name": "license.jpg", "asset_type": "image",
                "extracted_text": None,
            },
        ]
        with patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ), patch(
            "vault_inspection_tools.read_image_with_vision",
            return_value='{"error":"vision_disabled"}',
        ):
            raw = vcs.find_in_vault(
                vault_id="v1", key=b"\x00" * 32,
                query="ok show me all the ID phtos in my vault",
            )
        out = json.loads(raw)
                                                      
        self.assertEqual(out.get("query_kind"), "id_photo_visual")
        self.assertEqual(out.get("requested_person_name"), None)
                                                         
        self.assertTrue(out.get("complete"))
                                                             
        self.assertNotEqual(
            out.get("requested_person_name"), "Ok Phtos",
        )


class TestImageFailuresDoNotCrashSearch(unittest.TestCase):


    def _run_with_vision_responses(self, responses: list[str]) -> dict:
        rows = [
            {
                "id": f"f{i}",
                "content_type": "application/octet-stream",
                "saved_name": f"id_{i}.heic",
                "asset_type": "file",
                "extracted_text": None,
            }
            for i in range(len(responses))
        ]
        with patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ), patch(
            "vault_inspection_tools.read_image_with_vision",
            side_effect=responses,
        ):
            raw = vcs.find_in_vault(
                vault_id="v1", key=b"\x00" * 32,
                query="show me my ID photos",
            )
        return json.loads(raw)

    def test_corrupt_heic_does_not_crash_whole_search(self):
                                                                   
                                                                 
        out = self._run_with_vision_responses([
            '{"error":"unsupported_image"}',
            json.dumps({
                "analysis": (
                    "This is a driver license. Name: Louis Lodato. "
                    "Date of birth visible."
                ),
            }),
        ])
                                                     
        self.assertTrue(out["complete"])
                                        
        self.assertGreaterEqual(len(out["hits"]), 0)
                                                                 
                                
        self.assertNotIn("error", out)

    def test_missing_heic_decoder_does_not_crash_whole_search(self):
                                                                     
                                                                 
        out = self._run_with_vision_responses([
            '{"error":"unsupported_image"}',
            '{"error":"unsupported_image"}',
        ])
                                                             
                                                    
        self.assertTrue(out["complete"])
                                                           
                                                      
        self.assertEqual(len(out["hits"]), 0)
        self.assertNotIn("error", out)

    def test_vision_exception_per_image_does_not_crash_search(self):
                                                                        
                                        
        def _flaky(**kwargs):
            if kwargs.get("file_id") == "f0":
                raise RuntimeError("simulated vision crash")
            return json.dumps({"analysis": (
                "ID card. Name: Test User."
            )})

        rows = [
            {"id": "f0", "content_type": "image/jpeg",
             "saved_name": "a.jpg", "asset_type": "image",
             "extracted_text": None},
            {"id": "f1", "content_type": "image/jpeg",
             "saved_name": "b.jpg", "asset_type": "image",
             "extracted_text": None},
        ]
        with patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ), patch(
            "vault_inspection_tools.read_image_with_vision",
            side_effect=_flaky,
        ):
            raw = vcs.find_in_vault(
                vault_id="v1", key=b"\x00" * 32,
                query="show me my ID photos",
            )
        out = json.loads(raw)
        self.assertTrue(out["complete"])
        self.assertNotIn("error", out)


class TestEnvelopeBuilderSafety(unittest.TestCase):


    def _baseline_find_result(self, hits: Optional[list] = None) -> dict:
        return {
            "query": "show me my ID photos",
            "doc_kind": "id_photo",
            "query_kind": "id_photo_visual",
            "is_id_class_search": True,
            "complete": True,
            "partial_inspection": False,
            "hits": hits or [],
            "candidate_id_docs_count": len(hits or []),
            "name_mismatch_count": 0,
            "requested_person_name": None,
            "coverage": {
                "is_complete": True, "query_kind": "id_photo_visual",
                "candidate_id_docs_count": len(hits or []),
                "name_mismatch_count": 0, "weak_hits_dropped": 0,
            },
        }

    def test_thumbnail_render_exception_drops_to_icon_fallback(self):
        hits = [{
            "file_id": "f1", "file_name": "id.jpg",
            "file_kind": "image", "evidence_type": "image_vision",
            "match_type": "vision", "document_type": "driver_license",
            "matched_name": "Louis Lodato", "confidence": 0.92,
            "evidence": "...", "match_status": "exact_name_match",
            "classification_strength": "visual_confirmed",
        }]
                                      
        with patch(
            "vault_chat_result_cards._render_image_thumbnail",
            side_effect=RuntimeError("simulated render crash"),
        ), patch(
            "vault_chat_result_cards._batch_fetch_row_metadata",
            return_value={"f1": {
                "content_type": "image/jpeg",
                "saved_name": "id.jpg", "storage_mode": "inline",
            }},
        ):
            env = vcr.build_find_in_vault_envelope(
                query="show me my ID photos",
                find_result=self._baseline_find_result(hits),
                key=b"\x00" * 32, vault_id="v1",
                thumbnail_fetcher=lambda fid: b"\xff\xd8\xff" + b"\x00" * 32,
            )
        parsed = json.loads(env)
        self.assertEqual(parsed["count"], 1)
                                                                  
                  
        self.assertIsNone(parsed["results"][0]["thumbnail_base64"])
                                                               
        self.assertIn("matching ID photo", parsed["message"])
                             
        self.assertNotEqual(
            parsed.get("error_band"), "system_error",
        )

    def test_thumbnail_fetcher_raises_drops_to_icon_fallback(self):
                                                                     
                                      
        hits = [{
            "file_id": "f1", "file_name": "id.jpg",
            "file_kind": "image", "evidence_type": "image_vision",
            "match_type": "vision", "document_type": "driver_license",
            "matched_name": "X", "confidence": 0.92,
            "evidence": "...", "match_status": "exact_name_match",
            "classification_strength": "visual_confirmed",
        }]

        def _boom(fid):
            raise RuntimeError("decrypt boom")

        with patch(
            "vault_chat_result_cards._batch_fetch_row_metadata",
            return_value={"f1": {"content_type": "image/jpeg",
                                 "saved_name": "id.jpg",
                                 "storage_mode": "inline"}},
        ):
            env = vcr.build_find_in_vault_envelope(
                query="show me my ID photos",
                find_result=self._baseline_find_result(hits),
                key=b"\x00" * 32, vault_id="v1",
                thumbnail_fetcher=_boom,
            )
        parsed = json.loads(env)
        self.assertEqual(parsed["count"], 1)
        self.assertIsNone(parsed["results"][0]["thumbnail_base64"])

    def test_envelope_builder_internal_crash_returns_system_error(self):
                                                                  
                                                                
        with patch(
            "vault_chat_result_cards._build_find_in_vault_envelope_inner",
            side_effect=RuntimeError("internal builder bug"),
        ):
            env = vcr.build_find_in_vault_envelope(
                query="show me my ID photos",
                find_result=self._baseline_find_result(),
                key=b"\x00" * 32, vault_id="v1",
            )
        parsed = json.loads(env)
        self.assertEqual(parsed["error_band"], "system_error")
        self.assertEqual(parsed["exception_class"], "RuntimeError")
        self.assertIn(
            "Something went wrong while searching your vault",
            parsed["message"],
        )
                                                         
        self.assertNotIn("currently unavailable", parsed["message"])
        self.assertNotIn("try again later", parsed["message"])


class TestSystemErrorEnvelope(unittest.TestCase):
    def test_system_error_envelope_shape(self):
        env = vcr.build_system_error_envelope(
            query="show me my ID photos",
            query_kind="id_photo_visual",
            error_slug="tool_raised",
            exception_class="ImportError",
        )
        parsed = json.loads(env)
        self.assertEqual(parsed["type"], "file_search_results")
        self.assertEqual(parsed["count"], 0)
        self.assertEqual(parsed["results"], [])
        self.assertFalse(parsed["is_complete"])
        self.assertEqual(parsed["incomplete_reason"], "tool_raised")
        self.assertEqual(parsed["error_band"], "system_error")
        self.assertEqual(parsed["exception_class"], "ImportError")
                                                             
                     
        self.assertIn(
            "Something went wrong while searching your vault",
            parsed["message"],
        )

    def test_system_error_message_never_says_unavailable(self):
                                                             
                                 
        env = vcr.build_system_error_envelope(
            query="show me my ID photos",
            query_kind="id_photo_visual",
            error_slug="any",
        )
        msg = json.loads(env)["message"].lower()
        for forbidden in (
            "currently unavailable",
            "try again later",
            "search service",
        ):
            self.assertNotIn(forbidden, msg)


class TestTelemetryRedaction(unittest.TestCase):


    def test_system_error_envelope_log_carries_no_user_text(self):
        import logging

        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        rclogger = logging.getLogger("vault_chat_result_cards")
        rclogger.addHandler(sink)
        try:
            vcr.build_system_error_envelope(
                query="ok show me my Bob Smith driver license number 12345",
                query_kind="id_photo_visual",
                error_slug="tool_raised",
                exception_class="ConnectionError",
            )
        finally:
            rclogger.removeHandler(sink)

        joined = "\n".join(r.getMessage() for r in records)
                                                                   
        self.assertIn("tool_raised", joined)
        self.assertIn("ConnectionError", joined)
                                                        
        for forbidden in (
            "Bob Smith", "bob smith",
            "12345", "driver license",
        ):
            self.assertNotIn(forbidden, joined.lower())


class TestBroadSearchNeverGenericUnavailable(unittest.TestCase):


    def test_empty_vault_returns_no_match_not_unavailable(self):
        with patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=[],
        ):
            raw = vcs.find_in_vault(
                vault_id="v1", key=b"\x00" * 32,
                query="show me all ID photos in my vault",
            )
        out = json.loads(raw)
        self.assertTrue(out["complete"])
        self.assertEqual(len(out["hits"]), 0)
        self.assertNotIn("error", out)

                                                               
        with patch(
            "vault_chat_result_cards._batch_fetch_row_metadata",
            return_value={},
        ):
            env = vcr.build_find_in_vault_envelope(
                query="show me all ID photos in my vault",
                find_result=out, key=b"\x00" * 32, vault_id="v1",
            )
        parsed = json.loads(env)
        msg_low = parsed["message"].lower()
        self.assertNotIn("currently unavailable", msg_low)
        self.assertNotIn("try again later", msg_low)
        self.assertIn(
            "couldn't find any id documents",
            msg_low,
        )

    def test_vault_with_only_text_files_returns_no_match_not_unavailable(self):
                                                                 
                                                                 
        rows = [
            {"id": "t1", "content_type": "text/plain",
             "saved_name": "notes.txt", "asset_type": "file",
             "extracted_text": "just some notes"},
        ]
        with patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ):
            raw = vcs.find_in_vault(
                vault_id="v1", key=b"\x00" * 32,
                query="show me all ID photos in my vault",
            )
        out = json.loads(raw)
        self.assertTrue(out["complete"])
        self.assertEqual(len(out["hits"]), 0)
        with patch(
            "vault_chat_result_cards._batch_fetch_row_metadata",
            return_value={},
        ):
            env = vcr.build_find_in_vault_envelope(
                query="show me all ID photos in my vault",
                find_result=out, key=b"\x00" * 32, vault_id="v1",
            )
        msg = json.loads(env)["message"].lower()
        self.assertNotIn("currently unavailable", msg)


if __name__ == "__main__":                    
    unittest.main()
