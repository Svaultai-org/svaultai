

from __future__ import annotations

import inspect
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Optional

import main


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "plaintext-extracted-text-leak",
    "plaintext-summary-leak",
    "plaintext-preview-leak",
)


def _edge(
    *,
    a: str = "f-a",
    b: str = "f-b",
    relationship_type: str = "same_folder",
    confidence: float = 0.5,
    reasons: Optional[list] = None,
    evidence: Optional[dict] = None,
    updated_at: Optional[datetime] = None,
) -> dict:
    return {
        "file_a_id":         a,
        "file_b_id":         b,
        "relationship_type": relationship_type,
        "confidence":        confidence,
        "reasons_jsonb":     reasons or [f"reason for {relationship_type}"],
        "evidence_jsonb":    evidence or {},
        "updated_at":        updated_at or datetime.now(timezone.utc),
    }


class IntentPromptTests(unittest.TestCase):
    def _src(self) -> str:
        return inspect.getsource(main)

    def test_vault_clusters_in_intent_list(self):
        self.assertIn("- vault_clusters", self._src())

    def test_canonical_examples_present(self):
        src = self._src()
        for needle in (
            "show me everything connected in my vault",
            "show vault clusters",
            "organize my vault by connected documents",
            "show me my document groups",
        ):
            self.assertIn(needle, src)

    def test_prompt_distinguishes_from_related_files(self):
        self.assertIn(
            "vault_clusters is DIFFERENT from related_files",
            self._src(),
        )


class ClusterBuilderTests(unittest.TestCase):
    def test_single_edge_one_cluster(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b", relationship_type="duplicate",
                  confidence=0.99),
        ])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["file_ids"], ["a", "b"])

    def test_transitive_grouping(self):
                                                 
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b", relationship_type="same_person",
                  confidence=0.9),
            _edge(a="b", b="c", relationship_type="same_company",
                  confidence=0.8),
            _edge(a="c", b="d", relationship_type="same_trip",
                  confidence=0.85),
        ])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["file_ids"], ["a", "b", "c", "d"])
        self.assertEqual(clusters[0]["relationship_count"], 3)

    def test_disjoint_clusters_stay_separate(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b", relationship_type="duplicate",
                  confidence=0.99),
            _edge(a="x", b="y", relationship_type="same_trip",
                  confidence=0.85),
        ])
        self.assertEqual(len(clusters), 2)

    def test_strong_edge_count_pinned(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b", confidence=0.95),
            _edge(a="b", b="c", confidence=0.5),
            _edge(a="c", b="d", confidence=0.8),
        ])
        self.assertEqual(clusters[0]["strong_relationship_count"], 2)

    def test_self_loop_dropped(self):
                                                              
                                                   
        clusters = main._cluster_relationship_edges([
            _edge(a="x", b="x", confidence=0.9),
        ])
        self.assertEqual(clusters, [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(main._cluster_relationship_edges([]), [])

    def test_dedup_reasons_in_order(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b",
                  reasons=["matched company: Wells Fargo", "shared name"]),
            _edge(a="b", b="c",
                  reasons=["matched company: Wells Fargo", "fresh name"]),
        ])
        self.assertEqual(
            clusters[0]["main_reasons"],
            ["matched company: Wells Fargo", "shared name", "fresh name"],
        )


class ClusterTypeSelectionTests(unittest.TestCase):
    def test_identity_beats_supporting(self):
        self.assertEqual(
            main._select_cluster_type(
                {"same_person", "front_back_pair", "supporting_document"},
            ),
            "identity",
        )

    def test_travel(self):
        self.assertEqual(
            main._select_cluster_type({"same_trip"}),
            "travel",
        )

    def test_finance(self):
        self.assertEqual(
            main._select_cluster_type({"same_financial_account"}),
            "finance",
        )

    def test_tax(self):
                                                   
        self.assertEqual(
            main._select_cluster_type(
                {"same_company", "supporting_document"},
            ),
            "tax",
        )

    def test_application(self):
        self.assertEqual(
            main._select_cluster_type({"supporting_document"}),
            "application",
        )

    def test_company(self):
        self.assertEqual(
            main._select_cluster_type({"same_company"}),
            "company",
        )

    def test_duplicates(self):
        self.assertEqual(
            main._select_cluster_type({"duplicate"}),
            "duplicates",
        )
        self.assertEqual(
            main._select_cluster_type({"near_duplicate"}),
            "duplicates",
        )

    def test_archive_content(self):
        self.assertEqual(
            main._select_cluster_type({"archive_contains_signal"}),
            "archive_content",
        )

    def test_same_person_fallback(self):
        self.assertEqual(
            main._select_cluster_type({"same_person"}),
            "same_person",
        )

    def test_same_folder_default(self):
        self.assertEqual(
            main._select_cluster_type({"same_folder"}),
            "same_folder",
        )


class FilterTests(unittest.TestCase):
    def test_drops_same_folder_only(self):
        clusters = [
            {"edge_types": ["same_folder"], "cluster_type": "same_folder"},
        ]
        self.assertEqual(main._filter_meaningful_clusters(clusters), [])

    def test_keeps_same_folder_with_other_evidence(self):
                                                          
                                                           
        clusters = [
            {
                "edge_types": ["same_folder", "same_person"],
                "cluster_type": "same_person",
            },
        ]
        self.assertEqual(
            len(main._filter_meaningful_clusters(clusters)), 1,
        )

    def test_keeps_meaningful_clusters(self):
        clusters = [
            {"edge_types": ["duplicate"], "cluster_type": "duplicates"},
            {"edge_types": ["same_trip"], "cluster_type": "travel"},
        ]
        self.assertEqual(
            len(main._filter_meaningful_clusters(clusters)), 2,
        )


def _cluster(
    *,
    cluster_type="same_folder",
    strong=0,
    files=2,
    latest_ts=0.0,
) -> dict:
    return {
        "cluster_type":              cluster_type,
        "strong_relationship_count": strong,
        "file_ids":                  [f"f-{i}" for i in range(files)],
        "latest_updated_ts":         latest_ts,
    }


class RankingTests(unittest.TestCase):
    def test_strong_count_beats_file_count(self):
        out = main._sort_clusters([
            _cluster(cluster_type="duplicates", strong=0, files=10),
            _cluster(cluster_type="identity",   strong=5, files=3),
        ])
        self.assertEqual(out[0]["cluster_type"], "identity")

    def test_file_count_breaks_strong_tie(self):
        out = main._sort_clusters([
            _cluster(cluster_type="duplicates", strong=3, files=2),
            _cluster(cluster_type="duplicates", strong=3, files=5),
        ])
        self.assertEqual(len(out[0]["file_ids"]), 5)

    def test_type_priority_breaks_file_count_tie(self):
        out = main._sort_clusters([
            _cluster(cluster_type="same_folder", strong=2, files=3),
            _cluster(cluster_type="identity",    strong=2, files=3),
        ])
        self.assertEqual(out[0]["cluster_type"], "identity")

    def test_recency_breaks_type_priority_tie(self):
        out = main._sort_clusters([
            _cluster(cluster_type="travel", strong=1, files=3,
                     latest_ts=100.0),
            _cluster(cluster_type="travel", strong=1, files=3,
                     latest_ts=500.0),
        ])
        self.assertEqual(out[0]["latest_updated_ts"], 500.0)


class ClusterPatternTests(unittest.TestCase):
    def test_duplicate_group_detected(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b", relationship_type="duplicate",
                  confidence=0.99),
        ])
        self.assertEqual(clusters[0]["cluster_type"], "duplicates")

    def test_front_back_id_group_detected(self):
                                                           
                                                            
        clusters = main._cluster_relationship_edges([
            _edge(a="a", b="b", relationship_type="front_back_pair",
                  confidence=0.92),
            _edge(a="a", b="b", relationship_type="same_person",
                  confidence=0.85,
                  evidence={"shared_entity_names": ["Maureen"]}),
        ])
        self.assertEqual(clusters[0]["cluster_type"], "identity")
                                                          
                                                         
        clusters3 = main._cluster_relationship_edges([
            _edge(a="a", b="b", relationship_type="front_back_pair",
                  confidence=0.92),
            _edge(a="a", b="b", relationship_type="same_person",
                  confidence=0.85,
                  evidence={"shared_entity_names": ["Maureen"]}),
            _edge(a="b", b="c", relationship_type="supporting_document",
                  confidence=0.7),
        ])
        self.assertEqual(clusters3[0]["cluster_type"], "identity")

    def test_travel_docs_cluster(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="p", b="b", relationship_type="same_trip",
                  confidence=0.85),
            _edge(a="b", b="h", relationship_type="same_trip",
                  confidence=0.85),
        ])
        self.assertEqual(clusters[0]["cluster_type"], "travel")
        self.assertEqual(set(clusters[0]["file_ids"]),
                         {"p", "b", "h"})

    def test_finance_docs_cluster(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="s", b="t", relationship_type="same_financial_account",
                  confidence=0.9,
                  evidence={"shared_entity_names": ["Wells Fargo"]}),
        ])
        self.assertEqual(clusters[0]["cluster_type"], "finance")

    def test_application_supporting_docs_cluster(self):
        clusters = main._cluster_relationship_edges([
            _edge(a="form", b="id", relationship_type="supporting_document",
                  confidence=0.8),
            _edge(a="form", b="proof", relationship_type="supporting_document",
                  confidence=0.7),
        ])
        self.assertEqual(clusters[0]["cluster_type"], "application")


class EnvelopeShapeTests(unittest.TestCase):
    def _file_metadata(self) -> dict:
        return {
            "a": {
                "file_id":       "a",
                "file_name":     "front.jpg",
                "saved_name":    "Maureen ID — Front",
                "relative_path": "/Family/IDs",
                "content_type":  "image/jpeg",
                "asset_type":    "image",
            },
            "b": {
                "file_id":       "b",
                "file_name":     "back.jpg",
                "saved_name":    "Maureen ID — Back",
                "relative_path": "/Family/IDs",
                "content_type":  "image/jpeg",
                "asset_type":    "image",
            },
        }

    def test_envelope_carries_closed_set_keys(self):
        env = main._build_vault_clusters_envelope_dict(
            clusters=[
                {
                    "file_ids":                 ["a", "b"],
                    "edge_types":               ["same_person",
                                                 "front_back_pair"],
                    "relationship_count":       2,
                    "strong_relationship_count": 2,
                    "max_confidence":           0.92,
                    "latest_updated_ts":        100.0,
                    "main_reasons":             ["front-back pair",
                                                 "shared name"],
                    "cluster_type":             "same_person",
                    "entity_names":             ["Maureen"],
                },
            ],
            file_metadata_by_id=self._file_metadata(),
            message="I found 1 connected group in your vault.",
        )
        self.assertEqual(env["type"], "vault_relationship_clusters")
        self.assertEqual(env["count"], 1)
        c = env["clusters"][0]
        self.assertEqual(c["cluster_type"], "same_person")
        self.assertEqual(c["confidence"], "strong")
        self.assertEqual(c["file_count"], 2)
        self.assertEqual(c["title"], "Maureen documents")
                                                               
        for f in c["representative_files"]:
            self.assertEqual(
                set(f.keys()),
                {"file_id", "file_name", "saved_name",
                 "relative_path", "mime_type", "asset_type"},
            )

    def test_representative_files_cap_supports_detail_view(self):
                                                            
                                                         
        big_metadata = {}
        big_file_ids = []
        for i in range(60):
            fid = f"f-{i}"
            big_file_ids.append(fid)
            big_metadata[fid] = {
                "file_id":       fid,
                "file_name":     f"{fid}.pdf",
                "saved_name":    f"F {i}",
                "relative_path": "/Big",
                "content_type":  "application/pdf",
                "asset_type":    "file",
            }
        env = main._build_vault_clusters_envelope_dict(
            clusters=[
                {
                    "file_ids":                 big_file_ids,
                    "edge_types":               ["same_company"],
                    "relationship_count":       30,
                    "strong_relationship_count": 30,
                    "max_confidence":           0.9,
                    "latest_updated_ts":        1.0,
                    "main_reasons":             ["shared company"],
                    "cluster_type":             "company",
                    "entity_names":             [],
                },
            ],
            file_metadata_by_id=big_metadata,
            message="",
        )
        reps = env["clusters"][0]["representative_files"]
                                                         
        self.assertEqual(len(reps), 50)
                                                             
                                                
        self.assertGreater(len(reps), 5)

    def test_deleted_files_dropped(self):
                                                               
                                                            
        env = main._build_vault_clusters_envelope_dict(
            clusters=[
                {
                    "file_ids":                 ["deleted-a", "deleted-b"],
                    "edge_types":               ["same_person"],
                    "relationship_count":       1,
                    "strong_relationship_count": 1,
                    "max_confidence":           0.9,
                    "latest_updated_ts":        100.0,
                    "main_reasons":             ["shared name"],
                    "cluster_type":             "same_person",
                    "entity_names":             [],
                },
            ],
            file_metadata_by_id={},
            message="",
        )
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["clusters"], [])

    def test_no_sensitive_fields_in_envelope(self):
                                                             
                                                           
        hostile_metadata = {
            "a": {
                "file_id":       "a",
                "file_name":     "x.pdf",
                "saved_name":    "X",
                "relative_path": "/x",
                "content_type":  "application/pdf",
                "asset_type":    "file",
                                                             
                "summary":         "plaintext-summary-leak",
                "safe_preview":    "plaintext-preview-leak",
                "extracted_text":  "plaintext-extracted-text-leak",
                "password":        "hunter2",
                "token":           "SUPERSECRET-XYZ-123",
            },
        }
        env = main._build_vault_clusters_envelope_dict(
            clusters=[
                {
                    "file_ids":                 ["a"],
                    "edge_types":               ["same_company"],
                    "relationship_count":       1,
                    "strong_relationship_count": 1,
                    "max_confidence":           0.8,
                    "latest_updated_ts":        100.0,
                    "main_reasons":             ["shared company"],
                    "cluster_type":             "company",
                    "entity_names":             [],
                },
            ],
            file_metadata_by_id=hostile_metadata,
            message="",
        )
        env_json = json.dumps(env)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, env_json)


class ChatHandlerSourceGuardTests(unittest.TestCase):
    def test_vault_clusters_branch_exists(self):
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn('intent == "vault_clusters"', src)

    def test_branch_calls_compose_helper(self):
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find('intent == "vault_clusters"')
        body = src[idx:idx + 2000]
        self.assertIn("_compose_vault_clusters_envelope", body)

    def test_compose_helper_uses_pure_cluster_builder(self):
        src = inspect.getsource(main._compose_vault_clusters_envelope)
        self.assertIn("_cluster_relationship_edges", src)
        self.assertIn("_filter_meaningful_clusters", src)
        self.assertIn("_sort_clusters", src)

    def test_compose_helper_uses_load_safe_file_metadata(self):
                                                          
                                                          
        src = inspect.getsource(main._compose_vault_clusters_envelope)
        self.assertIn("_load_safe_file_metadata", src)


class SqlSurfaceTests(unittest.TestCase):
    def _code_only(self) -> str:
        import ast
        src = inspect.getsource(main._load_all_relationships_for_vault)
        try:
            doc = ast.get_docstring(ast.parse(src.lstrip())) or ""
        except Exception:
            doc = ""
        return src.replace(doc, "") if doc else src

    def test_query_is_vault_scoped(self):
        src = inspect.getsource(main._load_all_relationships_for_vault)
        self.assertIn("WHERE vault_id = %s", src)

    def test_never_reads_encrypted_columns(self):
        code = self._code_only()
        for col in (
            "encrypted_file_data",
            "extracted_text",
            "summary_encrypted",
            "safe_preview_encrypted",
        ):
            self.assertNotIn(col, code)

    def test_never_decrypts(self):
        code = self._code_only()
        self.assertNotIn("decrypt_message", code)
        self.assertNotIn("decrypt_bytes", code)


if __name__ == "__main__":
    unittest.main()
