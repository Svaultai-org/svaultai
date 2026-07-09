

from __future__ import annotations

import inspect
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import main


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "e&t082826",
    "sunshine6856", "loul82!Bridge",
    "plaintext-extracted-text-leak",
    "plaintext-summary-leak",
    "plaintext-preview-leak",
)


class IntentPromptTests(unittest.TestCase):
    def _prompt_text(self) -> str:
                                                      
                                                               
        src = inspect.getsource(main)
                                                               
        return src

    def test_related_files_in_intent_list(self):
        src = self._prompt_text()
        self.assertIn("- related_files", src)

    def test_canonical_examples_present(self):
        src = self._prompt_text()
                                                           
        for needle in (
            "what is related to this file",
            "show files related to my Maureen ID",
            "show everything related to my Qatar trip",
            "show supporting documents for this form",
        ):
            self.assertIn(needle, src)

    def test_prompt_distinguishes_from_search_files_about(self):
        src = self._prompt_text()
        self.assertIn(
            "related_files is DIFFERENT from search_files_about",
            src,
        )


def _row(
    *, a: str = "anchor",
    b: str = "other",
    confidence: float = 0.5,
    relationship_type: str = "same_folder",
    updated_at: Optional[datetime] = None,
    file_a_id: Optional[str] = None,
    file_b_id: Optional[str] = None,
    reasons: Optional[list] = None,
    evidence: Optional[dict] = None,
) -> dict:
    return {
        "file_a_id":       file_a_id or a,
        "file_b_id":       file_b_id or b,
        "relationship_type": relationship_type,
        "confidence":      confidence,
        "reasons_jsonb":   reasons or [f"reason for {relationship_type}"],
        "evidence_jsonb":  evidence or {},
        "updated_at":      updated_at or datetime.now(timezone.utc),
    }


class SortingTests(unittest.TestCase):
    def test_higher_confidence_comes_first(self):
        rows = [
            _row(confidence=0.30, relationship_type="same_folder"),
            _row(confidence=0.95, relationship_type="duplicate"),
        ]
        out = main._sort_relationship_rows(rows, anchor_id="anchor")
        self.assertEqual(out[0]["relationship_type"], "duplicate")

    def test_type_priority_breaks_confidence_tie(self):
                                                               
        rows = [
            _row(confidence=0.65, relationship_type="same_folder"),
            _row(confidence=0.65, relationship_type="duplicate"),
        ]
        out = main._sort_relationship_rows(rows, anchor_id="anchor")
        self.assertEqual(out[0]["relationship_type"], "duplicate")
        self.assertEqual(out[1]["relationship_type"], "same_folder")

    def test_recency_breaks_full_tie(self):
        now = datetime.now(timezone.utc)
        rows = [
            _row(
                confidence=0.65,
                relationship_type="same_folder",
                updated_at=now - timedelta(days=30),
            ),
            _row(
                confidence=0.65,
                relationship_type="same_folder",
                updated_at=now,
            ),
        ]
        out = main._sort_relationship_rows(rows, anchor_id="anchor")
                          
        self.assertEqual(
            out[0]["updated_at"], now,
        )


class EnvelopeShapeTests(unittest.TestCase):
    def _anchor(self) -> dict:
        return {
            "file_id":       "zip-anchor",
            "file_name":     "backup.zip",
            "saved_name":    "Backup",
            "relative_path": "/Family/Backups",
            "mime_type":     "application/zip",
            "asset_type":    "archive",
        }

    def _file_metadata_by_id(self) -> dict:
        return {
            "doc-1": {
                "file_id":       "doc-1",
                "file_name":     "notes.pdf",
                "saved_name":    "Notes",
                "relative_path": "/Notes",
                "content_type":  "application/pdf",
                "asset_type":    "file",
            },
        }

    def test_envelope_carries_anchor_count_message(self):
        env = main._build_related_files_graph_envelope(
            anchor=self._anchor(),
            rows=[
                _row(
                    file_a_id="doc-1",
                    file_b_id="zip-anchor",
                    confidence=0.92,
                    relationship_type="front_back_pair",
                    reasons=[
                        "filename pattern suggests front/back pair of an ID",
                    ],
                ),
            ],
            file_metadata_by_id=self._file_metadata_by_id(),
            message="I found 1 file related to Backup.",
        )
        payload = json.loads(env)
        self.assertEqual(payload["type"], "related_files_graph")
        self.assertEqual(payload["anchor"]["file_id"], "zip-anchor")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["message"],
            "I found 1 file related to Backup.",
        )

    def test_each_relationship_row_is_closed_set_safe(self):
        env = main._build_related_files_graph_envelope(
            anchor=self._anchor(),
            rows=[
                _row(
                    file_a_id="doc-1",
                    file_b_id="zip-anchor",
                    confidence=0.92,
                    relationship_type="front_back_pair",
                    reasons=["reason A", "reason B"],
                    evidence={"shared_entity_names": ["Maureen"]},
                ),
            ],
            file_metadata_by_id=self._file_metadata_by_id(),
            message="x",
        )
        payload = json.loads(env)
        row = payload["relationships"][0]
                                  
        for key in (
            "file", "relationship_type", "confidence",
            "confidence_label", "reasons", "evidence",
        ):
            self.assertIn(key, row)
                                           
        for key in (
            "file_id", "file_name", "saved_name",
            "relative_path", "mime_type", "asset_type",
        ):
            self.assertIn(key, row["file"])
        self.assertEqual(row["file"]["file_id"], "doc-1")
                                
        self.assertEqual(row["confidence"], 0.92)
                                         
        self.assertIn(
            row["confidence_label"], ("strong", "medium", "weak"),
        )
                                                      
        self.assertEqual(row["reasons"], ["reason A", "reason B"])

    def test_other_side_picked_correctly_for_anchor_a(self):
                                                         
        env = main._build_related_files_graph_envelope(
            anchor={**self._anchor(), "file_id": "anchor-a"},
            rows=[
                _row(
                    file_a_id="anchor-a",
                    file_b_id="doc-1",
                    confidence=0.5,
                ),
            ],
            file_metadata_by_id={
                "doc-1": {
                    "file_id":      "doc-1",
                    "file_name":    "notes.pdf",
                    "saved_name":   "Notes",
                },
            },
            message="x",
        )
        payload = json.loads(env)
        self.assertEqual(
            payload["relationships"][0]["file"]["file_id"], "doc-1",
        )

    def test_relationship_with_missing_other_metadata_dropped(self):
        env = main._build_related_files_graph_envelope(
            anchor=self._anchor(),
            rows=[
                _row(
                    file_a_id="ghost-id",
                    file_b_id="zip-anchor",
                    confidence=0.6,
                ),
            ],
            file_metadata_by_id={},                       
            message="x",
        )
        payload = json.loads(env)
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["relationships"], [])


class SafetyTests(unittest.TestCase):
    def test_extracted_text_and_summary_keys_never_in_envelope(self):
                                                        
                                                               
        env = main._build_related_files_graph_envelope(
            anchor={
                "file_id":       "zip-anchor",
                "file_name":     "backup.zip",
                "saved_name":    "Backup",
                "extracted_text": "plaintext-extracted-text-leak",
                "summary":        "plaintext-summary-leak",
                "safe_preview":   "plaintext-preview-leak",
                "password":       "hunter2",
            },
            rows=[
                _row(
                    file_a_id="doc-1",
                    file_b_id="zip-anchor",
                    confidence=0.5,
                    evidence={
                                                               
                        "decrypted_summary": "plaintext-summary-leak",
                        "extracted_text":    "plaintext-extracted-text-leak",
                        "password":          "hunter2",
                                                
                        "shared_entity_names": ["Maureen"],
                    },
                ),
            ],
            file_metadata_by_id={
                "doc-1": {
                    "file_id":      "doc-1",
                    "file_name":    "notes.pdf",
                    "saved_name":   "Notes",
                                          
                    "extracted_text": "plaintext-extracted-text-leak",
                    "summary":        "plaintext-summary-leak",
                    "token":          "SUPERSECRET-XYZ-123",
                },
            },
            message="x",
        )
        for sentinel in SENTINELS:
            self.assertNotIn(
                sentinel, env,
                f"sentinel {sentinel!r} leaked through envelope",
            )
                                                     
        payload = json.loads(env)
        self.assertEqual(
            payload["relationships"][0]["evidence"],
            {"shared_entity_names": ["Maureen"]},
        )

    def test_evidence_string_form_decoded_then_filtered(self):
                                                         
                                         
        env = main._build_related_files_graph_envelope(
            anchor={
                "file_id": "anchor", "file_name": "a.pdf",
            },
            rows=[
                _row(
                    file_a_id="doc-1",
                    file_b_id="anchor",
                    confidence=0.7,
                    evidence=json.dumps({
                        "extracted_text": "BAD",
                        "shared_topics": ["finance"],
                    }),
                ),
            ],
            file_metadata_by_id={
                "doc-1": {"file_id": "doc-1", "file_name": "d.pdf"},
            },
            message="x",
        )
        payload = json.loads(env)
        self.assertEqual(
            payload["relationships"][0]["evidence"],
            {"shared_topics": ["finance"]},
        )

    def test_safe_relationship_evidence_drops_unknown_keys(self):
        out = main._safe_relationship_evidence({
            "shared_entity_names": ["Maureen"],
            "shared_topics":       ["finance"],
            "decrypted_summary":   "BAD",
            "password":            "hunter2",
            "extracted_text":      "BAD",
        })
        self.assertEqual(
            set(out.keys()),
            {"shared_entity_names", "shared_topics"},
        )

    def test_safe_file_object_drops_hostile_keys(self):
        out = main._safe_file_object({
            "file_id":         "f1",
            "file_name":       "x.pdf",
            "saved_name":      "X",
            "extracted_text":  "BAD",
            "summary":         "BAD",
            "password":        "hunter2",
        })
        self.assertEqual(
            set(out.keys()),
            {"file_id", "file_name", "saved_name",
             "relative_path", "mime_type", "asset_type"},
        )

    def test_confidence_label_closed_set(self):
        self.assertEqual(main._confidence_label_for(0.95), "strong")
        self.assertEqual(main._confidence_label_for(0.60), "medium")
        self.assertEqual(main._confidence_label_for(0.30), "weak")
                                                       
        self.assertEqual(main._confidence_label_for("not-a-number"), "weak")


class ChatHandlerSourceGuardTests(unittest.TestCase):
    def test_related_files_branch_exists(self):
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn('intent == "related_files"', src)

    def test_branch_uses_resolver(self):
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find('intent == "related_files"')
        self.assertGreater(idx, -1)
        body = src[idx:idx + 6000]
        self.assertIn("_resolve_file_for_analysis", body)

    def test_branch_delegates_to_compose_helper(self):
                                                        
                                                               
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find('intent == "related_files"')
        body = src[idx:idx + 6000]
        self.assertIn("_compose_related_files_envelope", body)

    def test_compose_helper_calls_get_relationships_for_file(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("get_relationships_for_file", src)

    def test_compose_helper_uses_envelope_builder(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("_build_related_files_graph_envelope", src)

    def test_empty_state_message_matches_spec(self):
                                                               
                                                               
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("don't see strong related files", src)
        self.assertIn("related items may appear", src)


class LoadSafeFileMetadataSourceGuardTests(unittest.TestCase):
    def test_uses_closed_set_safe_columns_only(self):
        src = inspect.getsource(main._load_safe_file_metadata)
                                                       
        for col in (
            "file_name", "saved_name", "relative_path",
            "content_type", "asset_type",
        ):
            self.assertIn(col, src)

    def test_never_reads_extracted_text_or_encrypted_blob(self):
        src = inspect.getsource(main._load_safe_file_metadata)
                                                            
                                                              
        self.assertNotIn("extracted_text", src)
        self.assertNotIn("encrypted_file_data", src)
        self.assertNotIn("summary_encrypted", src)

    def test_query_is_vault_scoped(self):
        src = inspect.getsource(main._load_safe_file_metadata)
        self.assertIn("vault_id = %s", src)

    def test_empty_input_returns_empty_dict_without_querying(self):
                                                          
                                                                
        result = main._load_safe_file_metadata("vault-x", [])
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
