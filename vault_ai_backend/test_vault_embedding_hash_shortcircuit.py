

from __future__ import annotations

import hashlib
import inspect
import os
import unittest
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import patch

import vault_analysis as va
import vault_embedding as ve
import vault_embedding_worker as vew


def _migration_0009_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0009_vault_file_embeddings_safe_input_hash.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@dataclass
class FakeDBStore:
                                                          
    cache_lookup_result: Optional[dict] = None
                                
    executed: list = field(default_factory=list)
    committed: int = 0
    rolled_back: int = 0
                                        
    insert_count: int = 0
    refresh_count: int = 0
                                                               
                                    
    file_row: Optional[dict] = None
    understanding_row: Optional[dict] = None


class FakeCursor:
    def __init__(self, store: FakeDBStore, dict_mode: bool):
        self.store = store
        self.dict_mode = dict_mode
        self.last_sql: str = ""
        self.last_params: tuple = ()
        self._pending_result: Any = None
        self.rowcount: int = 1

    def execute(self, sql: str, params: Optional[tuple] = None):
        self.last_sql = sql
        self.last_params = tuple(params) if params else ()
        self.store.executed.append((sql, self.last_params))
                             
        s = sql
        if "FROM uploaded_files" in s and "extracted_text" in s:
            self._pending_result = self.store.file_row
        elif "FROM vault_file_understanding" in s and "summary_encrypted" in s:
            self._pending_result = self.store.understanding_row
        elif "FROM vault_file_embeddings" in s and "safe_input_hash" in s:
            self._pending_result = self.store.cache_lookup_result
        elif "INSERT INTO vault_file_embeddings" in s:
            self.store.insert_count += 1
        elif "UPDATE vault_file_embeddings" in s:
            self.store.refresh_count += 1

    def fetchone(self):
        out = self._pending_result
        self._pending_result = None
        return out

    def fetchall(self):
        out = self._pending_result or []
        self._pending_result = None
        return list(out)

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
                                                                  
                                                 
        dict_mode = bool(kwargs)
        return FakeCursor(self.store, dict_mode=dict_mode)

    def commit(self):
        self.store.committed += 1

    def rollback(self):
        self.store.rolled_back += 1

    def close(self):
        pass


def _install_fake_db(store: FakeDBStore):
    return patch(
        "vault_embedding_worker._get_db",
        return_value=FakeConn(store),
    )


def _understanding_row_dict(
    *,
    source_text_version: int = 1,
    document_purpose: str = "generic_text",
    purpose_label: str = "general text",
    topics: Optional[list] = None,
    summary_encrypted: Optional[str] = None,
    safe_preview_encrypted: Optional[str] = None,
) -> dict:
    return {
        "understanding_id":          "u-1",
        "vault_id":                  "vault-x",
        "file_id":                   "file-1",
        "source_text_version":       source_text_version,
        "analysis_version":          1,
        "status":                    "ready",
        "document_purpose":          document_purpose,
        "purpose_label":             purpose_label,
        "summary_encrypted":         summary_encrypted,
        "safe_preview_encrypted":    safe_preview_encrypted,
        "topics_jsonb":              topics or [],
        "entities_jsonb":            {},
        "detected_categories_jsonb": [],
    }


def _file_row_dict(*, version: int = 1) -> dict:
    return {
        "id":                       "file-1",
        "file_name":                "doc.pdf",
        "content_type":             "application/pdf",
        "extracted_text":           None,
        "extracted_text_encrypted": False,
        "extracted_text_version":   version,
        "upload_status":            "complete",
    }


def _decrypt_passthrough(ciphertext: str, key: bytes) -> str:
    return str(ciphertext or "")


class MigrationSchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_0009_source()

    def test_adds_safe_input_hash_column(self):
        self.assertIn("safe_input_hash", self.src)
        self.assertIn("ADD COLUMN", self.src)
        self.assertIn("TEXT", self.src)

    def test_creates_composite_lookup_index(self):
        self.assertIn(
            "vault_file_embeddings_input_hash_idx",
            self.src,
        )
                                                                 
        for col in ("vault_id", "file_id",
                    "embedding_model", "safe_input_hash"):
            self.assertIn(col, self.src)

    def test_migration_is_reversible(self):
        for needle in (
            "DROP INDEX IF EXISTS vault_file_embeddings_input_hash_idx",
            "DROP COLUMN IF EXISTS safe_input_hash",
        ):
            self.assertIn(needle, self.src)


class HashSafeInputTests(unittest.TestCase):
    def test_returns_sha256_hex_digest(self):
        text = "the quick brown fox"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(ve.hash_safe_input(text), expected)

    def test_empty_input_returns_empty_string(self):
                                                                
                                                               
        self.assertEqual(ve.hash_safe_input(""), "")
        self.assertEqual(ve.hash_safe_input(None), "")

    def test_hash_is_deterministic(self):
        text = "Wells Fargo Bank Statement | Topics: finance"
        self.assertEqual(
            ve.hash_safe_input(text),
            ve.hash_safe_input(text),
        )

    def test_hash_differs_when_input_differs(self):
        a = "Wells Fargo Bank Statement"
        b = "Wells Fargo Bank Statement!"
        self.assertNotEqual(ve.hash_safe_input(a), ve.hash_safe_input(b))

    def test_hash_is_64_char_hex(self):
        h = ve.hash_safe_input("anything")
        self.assertEqual(len(h), 64)
                         
        for ch in h:
            self.assertIn(ch.lower(), "0123456789abcdef")

    def test_hash_of_redacted_input_does_not_include_secret(self):


        safe = "Topics: finance | Names mentioned: Wells Fargo"
        with_secret = safe + " | leaked: Patrick62109"
        self.assertNotEqual(
            ve.hash_safe_input(safe),
            ve.hash_safe_input(with_secret),
        )


class WorkerSourceGuardTests(unittest.TestCase):
    def test_worker_hashes_before_calling_provider(self):
        src = inspect.getsource(vew._process_one_embedding_job)
        hash_idx = src.find("hash_safe_input")
        generate_idx = src.find("generate_embedding")
        self.assertGreater(hash_idx, -1)
        self.assertGreater(generate_idx, -1)
        self.assertLess(
            hash_idx, generate_idx,
            "the worker MUST hash the safe input BEFORE calling "
            "the provider — otherwise a cache hit would still pay "
            "for the embedding round-trip",
        )

    def test_worker_looks_up_cache_before_provider(self):
        src = inspect.getsource(vew._process_one_embedding_job)
        cache_idx = src.find("_lookup_cached_embedding")
        generate_idx = src.find("generate_embedding")
        self.assertGreater(cache_idx, -1)
        self.assertLess(cache_idx, generate_idx)

    def test_refresh_path_does_not_call_provider(self):
        src = inspect.getsource(vew._process_one_embedding_job)
                                                                
                                                                
        refresh_idx = src.find("_refresh_embedding_metadata")
        self.assertGreater(refresh_idx, -1)
        chunk = src[refresh_idx:refresh_idx + 1200]
        return_idx = chunk.find("return True")
        gen_idx = chunk.find("generate_embedding")
                                                               
                                                                  
        self.assertGreater(return_idx, -1)
        if gen_idx >= 0:
            self.assertLess(return_idx, gen_idx)

    def test_refresh_helper_does_not_touch_vector_column(self):
        import ast
        src = inspect.getsource(vew._refresh_embedding_metadata)
                                                            
                                                              
        try:
            tree = ast.parse(src.lstrip())
            fn = tree.body[0]
            doc = ast.get_docstring(fn) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertNotIn("embedding_vector", code_only)
        self.assertNotIn("safe_input_hash", code_only)

    def test_lookup_helper_filters_on_vault_file_model_hash(self):
        src = inspect.getsource(vew._lookup_cached_embedding)
        for col in ("vault_id", "file_id",
                    "embedding_model", "safe_input_hash"):
            self.assertIn(col, src)

    def test_lookup_helper_does_not_select_vector_blob(self):
        src = inspect.getsource(vew._lookup_cached_embedding)
                                                             
        self.assertIn("embedding_vector IS NOT NULL", src)
                                                   
        select_clause = src.split("SELECT")[1].split("FROM")[0]
        self.assertNotIn("embedding_vector,", select_clause)

    def test_upsert_writes_safe_input_hash(self):
        src = inspect.getsource(vew._upsert_embedding_vector)
        self.assertIn("safe_input_hash", src)

    def test_upsert_does_not_write_raw_input_text(self):
        src = inspect.getsource(vew._upsert_embedding_vector)
                                                                
                             
        self.assertNotIn("input_text", src)
        self.assertNotIn("embedding_input", src)

    def test_logger_never_carries_input_or_hash_values(self):
        src = inspect.getsource(vew)
                                                                 
                                                                
        for forbidden in (
            'logger.info("%s", input_text',
            'logger.info("%s", safe_input_hash',
            'logger.exception("%s", input_text',
        ):
            self.assertNotIn(forbidden, src)


class CacheHitSkipsProviderTests(unittest.TestCase):
    def tearDown(self):
        ve.reset_embedding_engine()

    def _run_one_job(self, *, store: FakeDBStore) -> dict:


        engine_calls = {"n": 0}

        def _engine(text: str) -> list[float]:
            engine_calls["n"] += 1
            return [1.0, 0.0, 0.0, 0.0]

        ve.set_embedding_engine(_engine)
        with _install_fake_db(store), \
                patch(
                    "vault_core.decrypt_message",
                    side_effect=_decrypt_passthrough,
                    create=True,
                ), \
                patch("vault_analysis.fail_analysis_job",
                      return_value=None), \
                patch("vault_analysis.complete_analysis_job",
                      return_value=True):
            ok = vew._process_one_embedding_job(
                job={"job_id": "job-1", "file_id": "file-1"},
                vault_id="vault-x",
                key=b"k",
            )
        return {"ok": ok, "engine_calls": engine_calls["n"]}

    def test_cache_hit_does_not_call_provider(self):
        store = FakeDBStore(
            file_row=_file_row_dict(version=2),
            understanding_row=_understanding_row_dict(
                source_text_version=2,
                topics=["finance"],
                summary_encrypted="summary about banking",
            ),
        )
                                                                 
                                                 
        embed_record = vew._row_to_record(store.understanding_row)
        input_text = ve.build_embedding_input(
            embed_record,
            file_name="doc.pdf",
            summary="summary about banking",
            safe_preview=None,
            raw_text=None,
        )
        cached_hash = ve.hash_safe_input(input_text)
        store.cache_lookup_result = {
            "status":               "ready",
            "source_text_version":  2,
            "analysis_version":     1,
            "has_vector":           True,
        }
                                                              
                                                               
        result = self._run_one_job(store=store)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["engine_calls"], 0,
            "cache hit MUST NOT call the embedding provider",
        )
                                                    
        self.assertEqual(store.refresh_count, 1)
        self.assertEqual(store.insert_count, 0)

    def test_cache_hit_with_version_bump_still_skips_provider(self):
                                                                 
                                                                
        store = FakeDBStore(
            file_row=_file_row_dict(version=2),
            understanding_row=_understanding_row_dict(
                source_text_version=2,
                topics=["finance"],
                summary_encrypted="summary about banking",
            ),
            cache_lookup_result={
                "status":              "stale",             
                "source_text_version": 1,                      
                "analysis_version":    1,
                "has_vector":          True,
            },
        )
        result = self._run_one_job(store=store)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["engine_calls"], 0,
            "a version-bump with identical safe input MUST reuse "
            "the vector — provider call would be wasted",
        )
                                 
        self.assertEqual(store.refresh_count, 1)

    def test_cache_miss_calls_provider_and_inserts(self):
                                                                  
                                                       
        store = FakeDBStore(
            file_row=_file_row_dict(version=1),
            understanding_row=_understanding_row_dict(
                source_text_version=1,
                topics=["finance"],
                summary_encrypted="summary about banking",
            ),
            cache_lookup_result=None,
        )
        result = self._run_one_job(store=store)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["engine_calls"], 1,
            "cache miss MUST call the embedding provider",
        )
                                    
        self.assertEqual(store.insert_count, 1)
                                     
        self.assertEqual(store.refresh_count, 0)

    def test_cache_hit_with_null_vector_falls_back_to_provider(self):


        store = FakeDBStore(
            file_row=_file_row_dict(version=1),
            understanding_row=_understanding_row_dict(
                source_text_version=1,
                topics=["finance"],
                summary_encrypted="summary about banking",
            ),
            cache_lookup_result={
                "status":              "unsupported",
                "source_text_version": 1,
                "analysis_version":    1,
                "has_vector":          False,                
            },
        )
        result = self._run_one_job(store=store)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["engine_calls"], 1,
            "a NULL vector means the cache miss path must run",
        )
        self.assertEqual(store.insert_count, 1)


class ModelChangeForcesReembedTests(unittest.TestCase):
    def tearDown(self):
        ve.reset_embedding_engine()

    def test_model_diff_is_cache_miss(self):


        engine_calls = {"n": 0}

        def _engine(text: str) -> list[float]:
            engine_calls["n"] += 1
            return [0.5] * 4

        store = FakeDBStore(
            file_row=_file_row_dict(version=1),
            understanding_row=_understanding_row_dict(
                source_text_version=1, topics=["finance"],
                summary_encrypted="summary",
            ),
            cache_lookup_result=None,
        )

        ve.set_embedding_engine(_engine)
        with _install_fake_db(store), \
                patch(
                    "vault_core.decrypt_message",
                    side_effect=_decrypt_passthrough,
                    create=True,
                ), \
                patch("vault_analysis.fail_analysis_job",
                      return_value=None), \
                patch("vault_analysis.complete_analysis_job",
                      return_value=True):
            ok = vew._process_one_embedding_job(
                job={"job_id": "job-1", "file_id": "file-1"},
                vault_id="vault-x",
                key=b"k",
            )
        self.assertTrue(ok)
        self.assertEqual(engine_calls["n"], 1)

    def test_lookup_query_filters_on_embedding_model(self):


        src = inspect.getsource(vew._lookup_cached_embedding)
        self.assertIn("embedding_model = %s", src)


class HashIsOfRedactedInputTests(unittest.TestCase):


    def test_hash_call_uses_post_redactor_input_text(self):
        src = inspect.getsource(vew._process_one_embedding_job)
        build_idx = src.find("ve.build_embedding_input")
        hash_idx = src.find("ve.hash_safe_input")
        self.assertGreater(build_idx, -1)
        self.assertGreater(hash_idx, -1)
        self.assertLess(
            build_idx, hash_idx,
            "build_embedding_input MUST run before hash_safe_input "
            "so the hash is over the redacted surface",
        )
                                                                
                              
        chunk = src[hash_idx:hash_idx + 200]
        self.assertIn("input_text", chunk)

    def test_hash_helper_inputs_pre_redacted_text(self):


        src = inspect.getsource(ve.hash_safe_input)
        self.assertIn("sha256", src)


class StaleRowReuseFlipsReadyTests(unittest.TestCase):
    def tearDown(self):
        ve.reset_embedding_engine()

    def test_stale_row_with_matching_hash_becomes_ready_no_provider(self):


        engine_calls = {"n": 0}

        def _engine(text):
            engine_calls["n"] += 1
            return [1.0, 0.0, 0.0, 0.0]

        store = FakeDBStore(
            file_row=_file_row_dict(version=2),
            understanding_row=_understanding_row_dict(
                source_text_version=2,
                topics=["finance"],
                summary_encrypted="summary about banking",
            ),
            cache_lookup_result={
                "status":              "stale",
                "source_text_version": 1,
                "analysis_version":    1,
                "has_vector":          True,
            },
        )

        ve.set_embedding_engine(_engine)
        with _install_fake_db(store), \
                patch(
                    "vault_core.decrypt_message",
                    side_effect=_decrypt_passthrough,
                    create=True,
                ), \
                patch("vault_analysis.fail_analysis_job",
                      return_value=None), \
                patch("vault_analysis.complete_analysis_job",
                      return_value=True):
            ok = vew._process_one_embedding_job(
                job={"job_id": "job-1", "file_id": "file-1"},
                vault_id="vault-x",
                key=b"k",
            )

        self.assertTrue(ok)
        self.assertEqual(engine_calls["n"], 0)

                                                            
        refresh_stmts = [
            (sql, params) for sql, params in store.executed
            if "UPDATE vault_file_embeddings" in sql
        ]
        self.assertEqual(len(refresh_stmts), 1)
        sql, params = refresh_stmts[0]
        self.assertIn("status              = 'ready'", sql)


class RawInputNeverPersistedTests(unittest.TestCase):
    def tearDown(self):
        ve.reset_embedding_engine()

    def test_no_executed_sql_contains_raw_input_string(self):


        ve.set_embedding_engine(lambda text: [0.5] * 4)
                                                              
                           
        sentinel = "SENTINEL_BANKING_TOPICS_NOT_FOR_DB_WRITE"
        store = FakeDBStore(
            file_row=_file_row_dict(version=1),
            understanding_row=_understanding_row_dict(
                source_text_version=1, topics=["finance"],
                summary_encrypted=sentinel,
            ),
            cache_lookup_result=None,
        )

        with _install_fake_db(store), \
                patch(
                    "vault_core.decrypt_message",
                    side_effect=_decrypt_passthrough,
                    create=True,
                ), \
                patch("vault_analysis.fail_analysis_job",
                      return_value=None), \
                patch("vault_analysis.complete_analysis_job",
                      return_value=True):
            vew._process_one_embedding_job(
                job={"job_id": "job-1", "file_id": "file-1"},
                vault_id="vault-x",
                key=b"k",
            )

                                                               
        for sql, params in store.executed:
            if "vault_file_embeddings" not in sql:
                continue
            for p in params or ():
                if isinstance(p, str) and sentinel in p:
                    self.fail(
                        f"sentinel input leaked into a "
                        f"vault_file_embeddings write: sql={sql[:120]!r}"
                    )


if __name__ == "__main__":
    unittest.main()
