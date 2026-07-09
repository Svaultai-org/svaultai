

from __future__ import annotations

import inspect
import json
import math
import os
import unittest
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import patch

import vault_analysis as va
import vault_embedding as ve
import vault_understanding as vu
import vault_understanding_search as vus


def _migration_0008_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0008_vault_file_embeddings.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _saved_login_text() -> str:
    return "\n".join([
        "AOL", "alice@example.com", "Patrick62109",
        "Apple", "bob@example.com", "MKSherm81765",
        "American Express", "carol@example.com", "e&t082826",
        "Wells Fargo", "dan@example.com", "sunshine6856",
    ])


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "sunshine6856",
    "e&t082826",
)


def _fake_engine_factory(vec_map: dict[str, list[float]]):


    def _engine(text: str) -> list[float]:
        if text in vec_map:
            return list(vec_map[text])
                                                          
        h = abs(hash(text)) % 10_000
        return [
            ((h >> 0) & 0xF) / 16.0,
            ((h >> 4) & 0xF) / 16.0,
            ((h >> 8) & 0xF) / 16.0,
            ((h >> 12) & 0xF) / 16.0,
        ]
    return _engine


@dataclass
class FakeDBStore:
    update_returning_rows: list = field(default_factory=list)
    select_results: list = field(default_factory=list)
    executed: list = field(default_factory=list)
    committed: int = 0
    rolled_back: int = 0


class FakeCursor:
    def __init__(self, store: FakeDBStore):
        self.store = store
        self.last_sql: str = ""
        self.last_params: tuple = ()
        self._select_results = list(store.select_results)
        self._returning_rows: list = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: Optional[tuple] = None):
        self.last_sql = sql
        self.last_params = tuple(params) if params else ()
        self.store.executed.append((sql, self.last_params))
        if "UPDATE vault_file_embeddings" in sql and "RETURNING" in sql:
            self._returning_rows = list(self.store.update_returning_rows)
            self.rowcount = len(self._returning_rows)
        elif "COUNT(*)" in sql:
            self._returning_rows = list(self._select_results)
            self.rowcount = len(self._returning_rows)
        else:
            self._returning_rows = []
            self.rowcount = 1

    def fetchone(self):
        if not self._returning_rows:
            return None
        return self._returning_rows[0]

    def fetchall(self):
        out = list(self._returning_rows)
        self._returning_rows = []
        return out

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, store: FakeDBStore):
        self.store = store

    def cursor(self, *args, **kwargs):
        return FakeCursor(self.store)

    def commit(self):
        self.store.committed += 1

    def rollback(self):
        self.store.rolled_back += 1

    def close(self):
        pass


class MigrationSchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_0008_source()

    def test_table_exists(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS vault_file_embeddings",
            self.src,
        )

    def test_required_columns_present(self):
        for col in (
            "embedding_id",
            "vault_id",
            "file_id",
            "understanding_id",
            "source_text_version",
            "analysis_version",
            "embedding_model",
            "embedding_dim",
            "embedding_source",
            "embedding_vector",
            "status",
            "last_error",
            "created_at",
            "updated_at",
        ):
            self.assertIn(col, self.src, f"missing column: {col}")

    def test_status_enum_includes_all_python_constants(self):
        for status in ve.EMBEDDING_STATUSES:
            self.assertTrue(
                f'"{status}"' in self.src or f"'{status}'" in self.src,
                f"migration must declare status {status!r}",
            )

    def test_source_enum_includes_all_python_constants(self):
        for src in ve.EMBEDDING_SOURCES:
            self.assertTrue(
                f'"{src}"' in self.src or f"'{src}'" in self.src,
                f"migration must declare source {src!r}",
            )

    def test_ready_has_vector_check_constraint(self):
        self.assertIn(
            "vault_file_embeddings_ready_has_vector_chk",
            self.src,
            "ready rows must have a populated vector — a ready "
            "row without a vector is incoherent",
        )

    def test_dim_positive_check_constraint(self):
        self.assertIn(
            "vault_file_embeddings_dim_positive_chk",
            self.src,
        )

    def test_unique_vault_file_index(self):
        self.assertIn(
            "vault_file_embeddings_file_idx",
            self.src,
        )

    def test_vault_status_index(self):
        self.assertIn(
            "vault_file_embeddings_vault_status_idx",
            self.src,
        )

    def test_source_text_version_index_for_stale_detection(self):
        self.assertIn(
            "vault_file_embeddings_source_text_version_idx",
            self.src,
        )

    def test_pgvector_ivfflat_index_for_cosine(self):
        self.assertIn(
            "vault_file_embeddings_vector_idx",
            self.src,
        )
        self.assertIn("vector_cosine_ops", self.src)

    def test_migration_adds_file_embedding_stage_to_check(self):
        self.assertTrue(
            '"file_embedding"' in self.src
            or "'file_embedding'" in self.src,
            "migration must declare the file_embedding stage",
        )
        self.assertIn(
            "vault_analysis_jobs_stage_chk",
            self.src,
        )

    def test_migration_is_reversible(self):
        for needle in (
            "DROP TABLE IF EXISTS vault_file_embeddings",
            "DROP INDEX IF EXISTS vault_file_embeddings_file_idx",
            "DROP INDEX IF EXISTS vault_file_embeddings_vector_idx",
        ):
            self.assertIn(needle, self.src)


class StageConstantTests(unittest.TestCase):
    def test_stage_file_embedding_in_python_stages(self):
        self.assertIn(va.STAGE_FILE_EMBEDDING, va.STAGES)

    def test_stage_name_matches_string(self):
        self.assertEqual(va.STAGE_FILE_EMBEDDING, "file_embedding")


class BuildEmbeddingInputCredentialSafetyTests(unittest.TestCase):
    def test_saved_login_file_skips_summary_and_preview(self):
        understanding = {
            "document_purpose":   "saved_login_list",
            "purpose_label":      "saved login list",
            "topics":             ["credentials"],
            "entities":           {"names": []},
            "detected_categories": ["security"],
        }
        input_text = ve.build_embedding_input(
            understanding,
            file_name="logins.txt",
            summary="Bob's saved logins. Patrick62109 hunter2",
            safe_preview="alice@example.com Patrick62109",
        )
        for sentinel in SENTINELS:
            self.assertNotIn(
                sentinel, input_text,
                f"sentinel {sentinel!r} reached embedding input",
            )

    def test_inline_password_token_pattern_redacted(self):
        understanding = {
            "document_purpose": "generic_text",
            "purpose_label":    "general document",
            "topics":           [],
            "entities":         {},
            "detected_categories": [],
        }
        input_text = ve.build_embedding_input(
            understanding,
            file_name="notes.txt",
            summary="The system was configured. password=hunter2 "
                    "see also api_key=SUPERSECRET-XYZ-123.",
        )
        self.assertNotIn("hunter2", input_text)
        self.assertNotIn("SUPERSECRET-XYZ-123", input_text)

    def test_long_alphanumeric_runs_redacted_inline(self):
                                                                  
        understanding = {
            "document_purpose":   "generic_text",
            "purpose_label":      "general document",
            "topics":             [],
            "entities":           {},
            "detected_categories": [],
        }
        token = "A" * 50
        input_text = ve.build_embedding_input(
            understanding,
            file_name="notes.txt",
            summary=f"key={token} value",
        )
                                                            
                                                                  
        self.assertNotIn(token, input_text)

    def test_raw_text_fallback_redacts_secret_lines(self):
                                                                 
                                            
        text = (
            "Some general notes about my finances.\n"
            "Patrick62109\n"
            "Some more notes."
        )
        input_text = ve.build_embedding_input(
            None,
            file_name="notes.txt",
            raw_text=text,
        )
        self.assertIn("notes about my finances", input_text)
        self.assertNotIn("Patrick62109", input_text)

    def test_empty_understanding_and_no_text_returns_empty_string(self):
        out = ve.build_embedding_input(None, file_name=None)
        self.assertEqual(out, "")

    def test_max_chars_caps_long_input(self):
        understanding = {
            "document_purpose":   "generic_text",
            "purpose_label":      "general document",
            "topics":             [],
            "entities":           {},
            "detected_categories": [],
        }
        big = "x" * 50_000
        out = ve.build_embedding_input(
            understanding,
            file_name="doc.pdf",
            summary=big,
            max_chars=500,
        )
        self.assertLessEqual(len(out), 500)


class BuildEmbeddingInputContentTests(unittest.TestCase):
    def test_finance_topic_expands_to_natural_phrases(self):
        understanding = {
            "document_purpose":   "generic_text",
            "purpose_label":      "general document",
            "topics":             ["finance"],
            "entities":           {"names": ["Wells Fargo"]},
            "detected_categories": ["finance"],
        }
        out = ve.build_embedding_input(
            understanding,
            file_name="jan_statement.pdf",
            summary="January statement summary.",
            safe_preview="Account ending 1234. Balance: $1,234.56.",
        )
                                                                  
                                                
        self.assertIn("bank statement", out.lower())
                          
        self.assertIn("Wells Fargo", out)
                                
        self.assertIn("jan_statement", out)

    def test_travel_topic_expansion_includes_passport_visa(self):
        understanding = {
            "document_purpose":   "generic_text",
            "purpose_label":      "general document",
            "topics":             ["travel"],
            "entities":           {"names": []},
            "detected_categories": ["travel"],
        }
        out = ve.build_embedding_input(
            understanding,
            file_name="trip.pdf",
            summary="Itinerary for the trip.",
        )
        self.assertIn("passport", out.lower())
        self.assertIn("visa", out.lower())

    def test_purpose_label_surfaces(self):
        understanding = {
            "document_purpose":   "application_form",
            "purpose_label":      "application form",
            "topics":             [],
            "entities":           {},
            "detected_categories": [],
        }
        out = ve.build_embedding_input(
            understanding, file_name="app.pdf", summary="",
        )
        self.assertIn("application", out.lower())


class CosineSimilarityTests(unittest.TestCase):
    def test_orthogonal_vectors_zero(self):
        self.assertAlmostEqual(
            ve.cosine_similarity([1, 0], [0, 1]), 0.0,
        )

    def test_parallel_vectors_one(self):
        self.assertAlmostEqual(
            ve.cosine_similarity([1, 2, 3], [2, 4, 6]), 1.0,
        )

    def test_opposite_vectors_minus_one(self):
        self.assertAlmostEqual(
            ve.cosine_similarity([1, 1], [-1, -1]), -1.0,
        )

    def test_dim_mismatch_returns_zero(self):
        self.assertEqual(ve.cosine_similarity([1, 2], [1, 2, 3]), 0.0)

    def test_empty_vector_returns_zero(self):
        self.assertEqual(ve.cosine_similarity([], [1, 2, 3]), 0.0)
        self.assertEqual(ve.cosine_similarity([1, 2, 3], []), 0.0)

    def test_zero_norm_returns_zero(self):
        self.assertEqual(ve.cosine_similarity([0, 0, 0], [1, 2, 3]), 0.0)


class EmbeddingEngineShimTests(unittest.TestCase):
    def tearDown(self):
        ve.reset_embedding_engine()

    def test_engine_injection_replaces_default(self):
        ve.set_embedding_engine(lambda text: [0.1, 0.2, 0.3])
        vec = ve.generate_embedding("hello")
        self.assertEqual(vec, [0.1, 0.2, 0.3])

    def test_engine_error_wraps_in_embedding_error(self):
        def _boom(text):
            raise RuntimeError("provider down")
        ve.set_embedding_engine(_boom)
        with self.assertRaises(ve.EmbeddingError):
            ve.generate_embedding("hello")

    def test_empty_text_raises_embedding_error(self):
        with self.assertRaises(ve.EmbeddingError):
            ve.generate_embedding("")

    def test_engine_returning_non_list_raises(self):
        ve.set_embedding_engine(lambda text: "not a list")
        with self.assertRaises(ve.EmbeddingError):
            ve.generate_embedding("hello")

    def test_engine_returning_empty_list_raises(self):
        ve.set_embedding_engine(lambda text: [])
        with self.assertRaises(ve.EmbeddingError):
            ve.generate_embedding("hello")


class WorkerSourceGuardTests(unittest.TestCase):
    def test_worker_exists_and_drains_via_claim(self):
        import vault_embedding_worker as vew
        src = inspect.getsource(vew.drain_file_embedding)
        self.assertIn("claim_next_analysis_job", src)
        mod_src = inspect.getsource(vew)
        self.assertIn("STAGE_FILE_EMBEDDING", mod_src)
        self.assertIn("_HANDLED_STAGE", src)

    def test_worker_calls_builder_and_generator(self):
        import vault_embedding_worker as vew
        src = inspect.getsource(vew._process_one_embedding_job)
        self.assertIn("build_embedding_input", src)
        self.assertIn("generate_embedding", src)

    def test_worker_drops_plaintext_after_use(self):
        import vault_embedding_worker as vew
        src = inspect.getsource(vew._process_one_embedding_job)
        for needle in (
            "summary = None",
            "safe_preview = None",
            "raw_text = None",
            'input_text = ""',
        ):
            self.assertIn(needle, src,
                          f"worker must drop plaintext local {needle!r} "
                          "after the vector is produced")

    def test_worker_never_persists_input_text(self):
                                                                
                                                              
        import vault_embedding_worker as vew
        src = inspect.getsource(vew._upsert_embedding_vector)
                                                               
                        
        self.assertNotIn("input_text", src)
        self.assertNotIn("embedding_input", src)

    def test_worker_does_not_touch_vault_items_table(self):
        import ast
        import vault_embedding_worker as vew
        src = inspect.getsource(vew)
                                                             
                                                               
        tree = ast.parse(src)
        doc = ast.get_docstring(tree) or ""
        code_only = src.replace(doc, "") if doc else src
        self.assertNotIn("INSERT INTO vault_items", code_only)
        self.assertNotIn("vault_items", code_only)

    def test_worker_never_executes_user_content(self):
        import vault_embedding_worker as vew
        src = inspect.getsource(vew)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_worker_logs_do_not_include_plaintext(self):
        import vault_embedding_worker as vew
        src = inspect.getsource(vew)
        for forbidden in (
            "logger.info(\"%s\", plaintext",
            "logger.info(\"%s\", summary",
            "logger.info(\"%s\", input_text",
            "logger.info(\"%s\", vector",
        ):
            self.assertNotIn(forbidden, src)


class UnderstandingEnqueuesEmbeddingTests(unittest.TestCase):
    def test_understanding_worker_enqueues_embedding_after_upsert(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw._process_one_understanding_job)
        upsert_idx = src.rfind("upsert_understanding")
        enqueue_idx = src.find("enqueue_embedding_after_understanding")
        self.assertGreater(upsert_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(
            upsert_idx, enqueue_idx,
            "understanding upsert must come BEFORE the embedding "
            "enqueue — otherwise a failed upsert would still queue "
            "an embedding job that finds no understanding row",
        )


def _install_fake_vu_db(store: FakeDBStore):
    return patch(
        "vault_understanding._get_db",
        return_value=FakeConn(store),
    )


class MarkStaleEmbeddingsTests(unittest.TestCase):
    def test_helper_exists_and_is_public(self):
        self.assertTrue(
            hasattr(vu, "mark_stale_embeddings_for_changed_text"),
        )

    def test_helper_signature_keyword_only(self):
        sig = inspect.signature(
            vu.mark_stale_embeddings_for_changed_text
        )
        params = sig.parameters
        self.assertIn("vault_id", params)
        self.assertEqual(
            params["file_id"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertIn("current_analysis_version", params)
        self.assertIn("current_model", params)

    def test_helper_sql_compares_versions_and_model(self):
        src = inspect.getsource(
            vu.mark_stale_embeddings_for_changed_text
        )
        self.assertIn("source_text_version", src)
        self.assertIn("extracted_text_version", src)
        self.assertIn("analysis_version", src)
        self.assertIn("embedding_model", src)
                                                                  
        self.assertIn("<>", src)

    def test_helper_status_set_is_stale(self):
        src = inspect.getsource(
            vu.mark_stale_embeddings_for_changed_text
        )
        self.assertIn("'stale'", src)

    def test_helper_skips_processing_rows(self):
        src = inspect.getsource(
            vu.mark_stale_embeddings_for_changed_text
        )
        self.assertIn("'pending'", src)
        self.assertIn("'ready'", src)
        self.assertIn("'stale'", src)
                                                         
        self.assertNotIn(
            "'processing'", src.split("WHERE")[1] if "WHERE" in src else src,
        )

    def test_helper_marks_returned_file_ids_as_stale(self):
        store = FakeDBStore(
            update_returning_rows=[("file-a",), ("file-b",)],
        )
        with _install_fake_vu_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1") as enqueue:
            result = vu.mark_stale_embeddings_for_changed_text(
                "vault-x",
            )
        self.assertEqual(result["stale_marked"], 2)
        self.assertEqual(result["jobs_enqueued"], 2)
        for call in enqueue.call_args_list:
            self.assertEqual(call.kwargs["stage"],
                             va.STAGE_FILE_EMBEDDING)

    def test_helper_enqueue_failure_does_not_stop_others(self):
        store = FakeDBStore(
            update_returning_rows=[("file-a",), ("file-b",), ("file-c",)],
        )
        calls = {"n": 0}

        def _enq(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return "job-id"

        with _install_fake_vu_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      side_effect=_enq):
            result = vu.mark_stale_embeddings_for_changed_text("vault-x")
        self.assertEqual(result["stale_marked"], 3)
        self.assertEqual(result["jobs_enqueued"], 2)

    def test_helper_filters_to_file_id(self):
        store = FakeDBStore(update_returning_rows=[("file-a",)])
        with _install_fake_vu_db(store), \
                patch("vault_analysis.enqueue_analysis_job",
                      return_value="job-1"):
            vu.mark_stale_embeddings_for_changed_text(
                "vault-x", file_id="file-a",
            )
        executed_sql = "\n".join(sql for sql, _ in store.executed)
        self.assertIn("e.file_id = %s", executed_sql)

    def test_helper_is_cross_vault_safe(self):
        src = inspect.getsource(
            vu.mark_stale_embeddings_for_changed_text
        )
        flat = src.replace("\n", " ")
        self.assertIn("u.vault_id = e.vault_id", flat)
        self.assertIn("e.vault_id = %s", flat)

    def test_helper_never_touches_vault_items_or_logs_secrets(self):
        src = inspect.getsource(
            vu.mark_stale_embeddings_for_changed_text
        )
        for forbidden in ("vault_items", "summary_encrypted",
                          "safe_preview_encrypted"):
            self.assertNotIn(forbidden, src)


class StaleHookIntegrationTests(unittest.TestCase):
    def test_text_extraction_worker_calls_embedding_stale_helper(self):
        import vault_analysis_worker as vaw
        src = inspect.getsource(vaw._process_one_text_extraction_job)
        self.assertIn("mark_stale_embeddings_for_changed_text", src)

    def test_ocr_worker_calls_embedding_stale_helper(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow._process_one_ocr_job)
        self.assertIn("mark_stale_embeddings_for_changed_text", src)

    def test_chat_handler_calls_embedding_stale_helper(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn("mark_stale_embeddings_for_changed_text", src)

    def test_chat_handler_runs_embedding_drain_after_understanding(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        understanding_idx = src.find("drain_file_understanding")
        embedding_idx = src.find("drain_file_embedding")
        self.assertGreater(understanding_idx, -1)
        self.assertGreater(embedding_idx, -1)
        self.assertLess(
            understanding_idx, embedding_idx,
            "embedding drain must run AFTER the understanding drain "
            "so a freshly-built understanding row immediately gets "
            "a vector in the same chat turn",
        )


class SearchSemanticTierTests(unittest.TestCase):
    def setUp(self):
                                                          
        bank_vec = [1.0, 0.0, 0.0, 0.0]
        travel_vec = [0.0, 1.0, 0.0, 0.0]
                           
        self.engine_map = {
                                                                 
            "find files about bank problems":           bank_vec,
            "bank problems":                            bank_vec,
            "money issues":                             bank_vec,
            "travel plans":                             travel_vec,
            "find files about travel plans":            travel_vec,
            "Wells Fargo":                              bank_vec,
        }
        ve.set_embedding_engine(_fake_engine_factory(self.engine_map))
        self.bank_vec = bank_vec
        self.travel_vec = travel_vec

    def tearDown(self):
        ve.reset_embedding_engine()

    def _make_row(
        self,
        *,
        file_id: str,
        file_name: str,
        embedding: Optional[list[float]],
        understanding_status: str = "ready",
        embedding_status: str = "ready",
        purpose: str = "generic_text",
        purpose_label: str = "general text",
        topics: Optional[list] = None,
        entities: Optional[dict] = None,
        categories: Optional[list] = None,
    ) -> dict:
        return {
            "file_id":              file_id,
            "file_name":            file_name,
            "saved_name":           None,
            "relative_path":        None,
            "content_type":         None,
            "asset_type":           "file",
            "extracted_text":       None,
            "extracted_text_encrypted": None,
            "understanding_status": understanding_status,
            "document_purpose":     purpose,
            "purpose_label":        purpose_label,
            "summary_encrypted":    None,
            "safe_preview_encrypted": None,
            "topics_jsonb":         topics or [],
            "entities_jsonb":       entities or {},
            "dates_jsonb":          [],
            "detected_categories_jsonb": categories or [],
            "searchable_terms_jsonb": [],
            "embedding_status":     embedding_status,
            "embedding_model":      ve.EMBEDDING_MODEL_DEFAULT,
            "embedding_dim":        len(embedding) if embedding else 0,
            "embedding_vector_text": None,
            "embedding_vector_decoded": embedding,
        }

    def test_query_embeds_via_generate_embedding(self):
                                                                   
                                               
        rows = [self._make_row(
            file_id="bank-1",
            file_name="bank_stuff.pdf",
            embedding=self.bank_vec,
            categories=["finance"],
            topics=["finance"],
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "bank problems",
            )
                                                                 
        self.assertTrue(report["semantic_available"])
        self.assertEqual(report["embedded_count"], 1)

    def test_bank_query_semantic_hit_on_finance_file(self):
                                                                 
                                                                
        rows = [self._make_row(
            file_id="bank-1",
            file_name="january_statement.pdf",
            embedding=self.bank_vec,
            categories=[],                           
            topics=[],                                   
            purpose="generic_text",
            purpose_label="general text",
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "money issues",                        
            )
        self.assertEqual(len(report["results"]), 1)
        m = report["results"][0]
        self.assertEqual(m["match_type"], "semantic")
        self.assertIn(m["tier"],
                      (vus.TIER_SEMANTIC_STRONG, vus.TIER_SEMANTIC_MEDIUM))
        self.assertGreaterEqual(m["similarity"], ve.DEFAULT_MEDIUM_THRESHOLD)

    def test_travel_query_finds_travel_file(self):
        rows = [self._make_row(
            file_id="trip-1",
            file_name="trip_notes.txt",
            embedding=self.travel_vec,
            categories=[],
            topics=[],
            purpose_label="general text",
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "travel plans",
            )
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["match_type"], "semantic")

    def test_exact_entity_beats_semantic(self):
                                                            
                                                                  
        rows = [
            self._make_row(
                file_id="entity-row",
                file_name="hellofargo.pdf",
                embedding=None,                              
                entities={"names": ["Wells Fargo"],
                          "email_domains": []},
            ),
            self._make_row(
                file_id="semantic-row",
                file_name="bank_data.pdf",
                embedding=self.bank_vec,
                                                
                entities={"names": [], "email_domains": []},
            ),
        ]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
                                                
        first = report["results"][0]
        self.assertEqual(first["file_id"], "entity-row")
        self.assertEqual(first["tier"], vus.TIER_ENTITY)

    def test_semantic_strong_beats_filename(self):
                                                              
                                     
        rows = [
            self._make_row(
                file_id="filename-row",
                file_name="bank.txt",                           
                embedding=None,
            ),
            self._make_row(
                file_id="semantic-row",
                file_name="opaque.txt",
                embedding=self.bank_vec,
            ),
        ]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "money issues",                       
            )
                                                     
        first = report["results"][0]
        self.assertEqual(first["file_id"], "semantic-row")

    def test_stale_embedding_downgrades_semantic_match(self):
        rows = [self._make_row(
            file_id="stale-emb",
            file_name="bank.pdf",
            embedding=self.bank_vec,
            embedding_status="stale",
            understanding_status="ready",
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "money issues",
            )
        m = report["results"][0]
        self.assertEqual(m["confidence"], "weak")
        self.assertTrue(m.get("is_stale"))
        self.assertIn("(being refreshed)", m["match_reason"])

    def test_pending_embedding_count_returned(self):
        rows = [
            self._make_row(
                file_id="a", file_name="a.pdf",
                embedding=self.bank_vec, embedding_status="ready",
            ),
            self._make_row(
                file_id="b", file_name="b.pdf",
                embedding=None, embedding_status="pending",
            ),
            self._make_row(
                file_id="c", file_name="c.pdf",
                embedding=None, embedding_status="processing",
            ),
        ]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "bank problems",
            )
        self.assertEqual(report["pending_embedding_count"], 2)
        self.assertEqual(report["embedded_count"], 1)

    def test_semantic_reason_mentions_query_relation(self):
        rows = [self._make_row(
            file_id="bank-1",
            file_name="opaque.pdf",
            embedding=self.bank_vec,
            categories=["finance"],
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "money issues",
            )
        reason = report["results"][0]["match_reason"]
        self.assertIn("semantic match", reason)


class SearchEmbeddingFailureTests(unittest.TestCase):
    def tearDown(self):
        ve.reset_embedding_engine()

    def test_provider_failure_returns_semantic_available_false(self):
        def _boom(text):
            raise RuntimeError("provider down")
        ve.set_embedding_engine(_boom)
                                                       
        rows = [{
            "file_id":              "f-1",
            "file_name":            "doc.pdf",
            "saved_name":           None,
            "relative_path":        None,
            "content_type":         None,
            "asset_type":           "file",
            "extracted_text":       None,
            "extracted_text_encrypted": None,
            "understanding_status": "ready",
            "document_purpose":     "generic_text",
            "purpose_label":        "general text",
            "summary_encrypted":    None,
            "safe_preview_encrypted": None,
            "topics_jsonb":         ["finance"],
            "entities_jsonb":       {},
            "dates_jsonb":          [],
            "detected_categories_jsonb": ["finance"],
            "searchable_terms_jsonb": [],
            "embedding_status":     "ready",
            "embedding_model":      ve.EMBEDDING_MODEL_DEFAULT,
            "embedding_dim":        4,
            "embedding_vector_text": None,
            "embedding_vector_decoded": [1.0, 0.0, 0.0, 0.0],
        }]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "finance",
            )
        self.assertFalse(report["semantic_available"])
                                                   
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["match_type"], "category")


class FormatSearchReplySemanticTests(unittest.TestCase):
    def test_pending_embedding_count_surfaces(self):
        reply = vus.format_search_reply(
            query="money issues",
            results=[{"file_name": "bank.pdf",
                      "match_reason": "semantic match: this file appears"}],
            pending_count=0, stale_count=0,
            pending_embedding_count=4,
        )
        self.assertIn("indexed for semantic search", reply)

    def test_semantic_unavailable_surfaces(self):
        reply = vus.format_search_reply(
            query="money issues",
            results=[],
            pending_count=0, stale_count=0,
            semantic_available=False,
        )
        self.assertIn("Semantic search is temporarily unavailable",
                      reply)

    def test_no_extra_notes_when_clean(self):
        reply = vus.format_search_reply(
            query="money issues",
            results=[{"file_name": "bank.pdf",
                      "match_reason": "semantic match"}],
            pending_count=0, stale_count=0,
            pending_embedding_count=0,
            semantic_available=True,
        )
        self.assertNotIn("Semantic search is temporarily", reply)
        self.assertNotIn("indexed for semantic search", reply)


class FileSearchEnvelopeSemanticTests(unittest.TestCase):
    def test_envelope_carries_similarity_and_counts(self):
        import main
        env = main._build_file_search_envelope(
            query="money issues",
            results=[{
                "file_id": "f1",
                "file_name": "bank.pdf",
                "match_type": "semantic",
                "match_reason": "semantic match: this file appears to be a finance document",
                "confidence": "strong",
                "similarity": 0.82,
            }],
            message="",
            pending_count=0,
            stale_count=0,
            pending_embedding_count=2,
            semantic_available=True,
        )
        payload = json.loads(env)
        self.assertEqual(payload["pending_embedding_count"], 2)
        self.assertTrue(payload["semantic_available"])
        row = payload["results"][0]
        self.assertEqual(row["match_type"], "semantic")
        self.assertEqual(row["similarity"], 0.82)

    def test_envelope_omits_similarity_for_non_semantic_rows(self):
        import main
        env = main._build_file_search_envelope(
            query="x",
            results=[{
                "file_id": "f1",
                "file_name": "doc.pdf",
                "match_type": "filename",
                "match_reason": "filename match: doc.pdf",
                "confidence": "weak",
                                      
            }],
            message="",
            pending_count=0,
        )
        payload = json.loads(env)
        row = payload["results"][0]
        self.assertIsNone(row["similarity"])


class BuilderSafetyTests(unittest.TestCase):
    def test_builder_never_executes_user_content(self):
        src = inspect.getsource(ve)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_redactor_strips_inline_secret_lines(self):
        cleaned = ve._redact_secret_shaped_lines(
            "Some general notes.\npassword: hunter2\nMore notes."
        )
        self.assertIn("general notes", cleaned)
        self.assertNotIn("hunter2", cleaned)

    def test_redactor_strips_bearer_lines(self):
        cleaned = ve._redact_secret_shaped_lines(
            "Authorization context.\n"
            "Bearer eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0\n"
            "End of context."
        )
        self.assertIn("Authorization context", cleaned)
        self.assertNotIn("eyJ", cleaned)

    def test_redactor_keeps_legitimate_names(self):
        cleaned = ve._redact_secret_shaped_lines(
            "Wells Fargo and MailChimp are companies."
        )
        self.assertIn("Wells Fargo", cleaned)
        self.assertIn("MailChimp", cleaned)

    def test_is_secret_shape_catches_password_like_token(self):
        self.assertTrue(ve._is_secret_shape("Patrick62109"))
        self.assertTrue(ve._is_secret_shape("MKSherm81765"))
        self.assertTrue(ve._is_secret_shape("e&t082826"))

    def test_is_secret_shape_lets_brand_names_through(self):
        self.assertFalse(ve._is_secret_shape("Apple"))
        self.assertFalse(ve._is_secret_shape("MailChimp"))
        self.assertFalse(ve._is_secret_shape("WellsFargo"))


class StatusEnumAgreesWithMigrationTests(unittest.TestCase):
    def test_python_enum_matches_migration_check(self):
        src = _migration_0008_source()
        for status in ve.EMBEDDING_STATUSES:
            self.assertTrue(
                f'"{status}"' in src or f"'{status}'" in src,
                f"migration must declare status {status!r}",
            )


class EndToEndSavedLoginSafetyTests(unittest.TestCase):
    def test_saved_login_understanding_produces_safe_input(self):
                                                                   
                                                                 
        record = vu.build_understanding(
            _saved_login_text(),
            file_name="logins.txt",
        )
        input_text = ve.build_embedding_input(
            {
                "document_purpose":    record["document_purpose"],
                "purpose_label":       record["purpose_label"],
                "topics":              record["topics"],
                "entities":            record["entities"],
                "detected_categories": record["detected_categories"],
            },
            file_name="logins.txt",
            summary=record["summary"],
            safe_preview=record["safe_preview"],
        )
        for sentinel in SENTINELS:
            self.assertNotIn(
                sentinel, input_text,
                f"sentinel {sentinel!r} leaked into embedding input",
            )


if __name__ == "__main__":
    unittest.main()
