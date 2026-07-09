

from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest import mock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCursor:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []
        self._rowcount_queue: list[int] = []
        self._fetch_queue: list = []
        self.rowcount = 0
        self.executed_many: list[tuple[str, list]] = []

    def queue_rowcount(self, n: int):
        self._rowcount_queue.append(n)

    def queue_fetchall(self, rows: list):
        self._fetch_queue.append(("all", rows))

    def queue_fetchone(self, row):
        self._fetch_queue.append(("one", row))

    def execute(self, sql, params=()):
        self.queries.append((sql, tuple(params) if params else ()))
        if self._rowcount_queue:
            self.rowcount = self._rowcount_queue.pop(0)

    def executemany(self, sql, rows):
        self.executed_many.append((sql, list(rows)))

    def fetchall(self):
        if self._fetch_queue and self._fetch_queue[0][0] == "all":
            return self._fetch_queue.pop(0)[1]
        return []

    def fetchone(self):
        if self._fetch_queue and self._fetch_queue[0][0] == "one":
            return self._fetch_queue.pop(0)[1]
        return None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur=None):
        self._cur = cur or _FakeCursor()
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self, *a, **kw):
        return self._cur

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


class ChunkStoreWriteTests(unittest.TestCase):
    def test_write_chunks_encrypts_and_inserts(self):
        from vault_chunker import Chunk
        from vault_chunk_store import write_chunks
        chunks = [
            Chunk(chunk_index=0, char_start=0, char_end=20,
                  text="hello world chunk 1", extraction_source="pdf_text"),
            Chunk(chunk_index=1, char_start=15, char_end=35,
                  text="overlap chunk 2",     extraction_source="pdf_text"),
        ]
        cur = _FakeCursor()
        conn = _FakeConn(cur)
                                                                 
                                                             
        import hashlib
        def fake_encrypt(text, key):
            return "blob:" + hashlib.sha256(text.encode()).hexdigest()
        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.encrypt_message",
                        side_effect=fake_encrypt):
            n = write_chunks(
                vault_id="v1", file_id="f1", chunks=chunks, key=b"K" * 32,
            )
        self.assertEqual(n, 2)
                                         
        first_sql = cur.queries[0][0]
        self.assertIn("DELETE FROM vault_content_chunks", first_sql)
        self.assertEqual(len(cur.executed_many), 1)
        insert_sql, rows = cur.executed_many[0]
        self.assertIn("INSERT INTO vault_content_chunks", insert_sql)
                                                                    
        for row in rows:
            self.assertTrue(row[3].startswith("blob:"))
            self.assertNotIn("hello world chunk 1", repr(row[3]))
            self.assertNotIn("overlap chunk 2", repr(row[3]))
        self.assertEqual(conn.committed, 1)

    def test_write_empty_list_wipes_prior_chunks(self):
        from vault_chunk_store import write_chunks
        cur = _FakeCursor()
        cur.queue_rowcount(3)
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            n = write_chunks(
                vault_id="v1", file_id="f1", chunks=[], key=b"K" * 32,
            )
        self.assertEqual(n, 0)
                                                                
        self.assertIn("DELETE FROM vault_content_chunks", cur.queries[0][0])

    def test_empty_vault_or_file_id_no_db_call(self):
        from vault_chunk_store import write_chunks
        with mock.patch("vault_core.get_db") as gdb:
            self.assertEqual(write_chunks(
                vault_id="", file_id="f", chunks=[], key=b"K"), 0)
            self.assertEqual(write_chunks(
                vault_id="v", file_id="", chunks=[], key=b"K"), 0)
        gdb.assert_not_called()


class ChunkStoreFetchTests(unittest.TestCase):
    def test_fetch_for_file_decrypts_in_index_order(self):
        from vault_chunk_store import fetch_chunks_for_file
        cur = _FakeCursor()
        cur.queue_fetchall([
            ("c-0", 0, "ENC(0)", 0, 20, "pdf_text"),
            ("c-1", 1, "ENC(1)", 15, 35, "pdf_text"),
        ])
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: b.replace("ENC(", "").rstrip(")")):
            out = fetch_chunks_for_file(
                vault_id="v1", file_id="f1", key=b"K" * 32,
            )
        self.assertEqual(len(out), 2)
        self.assertEqual([c.chunk_index for c in out], [0, 1])
        self.assertEqual(out[0].text, "0")
                               
        sql = cur.queries[0][0]
        self.assertIn("WHERE vault_id = %s AND file_id = %s", sql)

    def test_fetch_skips_chunks_that_fail_to_decrypt(self):
        from vault_chunk_store import fetch_chunks_for_file
        cur = _FakeCursor()
        cur.queue_fetchall([
            ("c-0", 0, "BLOB", 0, 20, "pdf_text"),
            ("c-1", 1, "GOOD", 0, 20, "pdf_text"),
        ])
        conn = _FakeConn(cur)
        calls = []
        def dec(b, k):
            calls.append(b)
            if b == "BLOB":
                raise RuntimeError("decrypt failed")
            return "decoded"
        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message", side_effect=dec):
            out = fetch_chunks_for_file(
                vault_id="v1", file_id="f1", key=b"K" * 32,
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].text, "decoded")


class ChunkStoreCountTests(unittest.TestCase):
    def test_count_chunks_returns_total_and_embedded(self):
        from vault_chunk_store import count_chunks_for_vault
        cur = _FakeCursor()
        cur.queue_fetchone((20, 12))
        conn = _FakeConn(cur)
        with mock.patch("vault_core.get_db", return_value=conn):
            out = count_chunks_for_vault("v1")
        self.assertEqual(out, {"total": 20, "embedded": 12, "unembedded": 8})


class BrainIndexerTests(unittest.TestCase):
    def test_index_chunks_for_file_embeds_unembedded_rows(self):
        from vault_brain_indexer import index_chunks_for_file
                                                              
                                                                     
        select_cur = _FakeCursor()
        select_cur.queue_fetchall([
            ("c-0", 0, "ENC(0)"),
            ("c-1", 1, "ENC(1)"),
        ])
        select_conn = _FakeConn(select_cur)
        update_curs = [_FakeCursor() for _ in range(2)]
        for cur in update_curs:
            cur.queue_rowcount(1)
        update_conns = [_FakeConn(c) for c in update_curs]
        conn_iter = iter([select_conn, *update_conns])

        async def fake_embed(text):
            return [float(i % 7) for i in range(1536)]

        with mock.patch("vault_core.get_db",
                        side_effect=lambda: next(conn_iter)), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: "plaintext"):
            report = _run(index_chunks_for_file(
                vault_id="v1", file_id="f1",
                embed_fn=fake_embed, key=b"K" * 32,
            ))
        self.assertEqual(report.chunks_seen, 2)
        self.assertEqual(report.chunks_embedded, 2)
        self.assertEqual(report.chunks_failed, 0)
                                                             
        for cur in update_curs:
            self.assertEqual(len(cur.queries), 1)
            self.assertIn("UPDATE vault_content_chunks", cur.queries[0][0])

    def test_dim_mismatch_marks_failed_no_write(self):
        from vault_brain_indexer import index_chunks_for_file
        select_cur = _FakeCursor()
        select_cur.queue_fetchall([("c-0", 0, "ENC(0)")])
        select_conn = _FakeConn(select_cur)

        async def fake_embed(text):
            return [1.0, 2.0, 3.0]             

                                             
        conn_iter = iter([select_conn])
        with mock.patch("vault_core.get_db",
                        side_effect=lambda: next(conn_iter)), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: "plaintext"):
            report = _run(index_chunks_for_file(
                vault_id="v1", file_id="f1",
                embed_fn=fake_embed, key=b"K" * 32,
            ))
        self.assertEqual(report.chunks_embedded, 0)
        self.assertEqual(report.chunks_failed, 1)

    def test_no_key_short_circuits_with_error(self):
        from vault_brain_indexer import index_chunks_for_file

        async def fake_embed(text):
            return [0.0] * 1536

        with mock.patch("vault_core.get_db") as gdb:
            report = _run(index_chunks_for_file(
                vault_id="v1", file_id="f1",
                embed_fn=fake_embed, key=None,
            ))
        gdb.assert_not_called()
        self.assertEqual(report.error, "no_key")

    def test_empty_scope_returns_empty_scope_error(self):
        from vault_brain_indexer import index_chunks_for_file

        async def fake_embed(text):
            return [0.0] * 1536

        report = _run(index_chunks_for_file(
            vault_id="", file_id="f1",
            embed_fn=fake_embed, key=b"K" * 32,
        ))
        self.assertEqual(report.error, "empty_scope")


class EvidenceBundleTests(unittest.TestCase):
    def _bundle(self, chunks):
        from vault_evidence_bundle import EvidenceBundle, EvidenceChunk
        return EvidenceBundle(
            query="anything",
            vault_id="v-test",
            chunks=tuple(chunks),
            matching_file_ids=tuple(sorted({c.file_id for c in chunks})),
            coverage_at_time={"total": 10, "analyzed": 10},
        )

    def _chunk(self, file_id, text, score=0.5):
        from vault_evidence_bundle import EvidenceChunk
        return EvidenceChunk(
            chunk_id=f"chunk-{file_id}-0",
            file_id=file_id,
            chunk_index=0,
            text=text,
            extraction_source="pdf_text",
            score=score,
            char_start=0, char_end=len(text),
        )

    def test_has_evidence_true_when_chunks_present(self):
        b = self._bundle([self._chunk("f1", "hello")])
        self.assertTrue(b.has_evidence)
        self.assertEqual(b.total_matching_files, 1)

    def test_to_debug_dict_redacts_text_and_query(self):
        b = self._bundle([
            self._chunk("f1", "SECRET-SENTINEL", 0.91),
            self._chunk("f2", "another SECRET",  0.85),
        ])
        debug = b.to_debug_dict()
        flat = repr(debug)
        self.assertNotIn("SECRET-SENTINEL", flat,
            "debug dict must redact chunk text")
        self.assertNotIn("anything", flat,
            "debug dict must NOT echo the query")
                             
        self.assertEqual(debug["n_chunks"], 2)
        self.assertEqual(debug["n_matching_files"], 2)
        self.assertIn(0.91, debug["top_scores"])

    def test_snippets_truncates_long_text(self):
        long_text = "x" * 1000
        b = self._bundle([self._chunk("f1", long_text)])
        snippets = b.snippets(max_chars=100)
        self.assertLessEqual(len(snippets[0]), 100 + 1)             


class BrainRetrievalTests(unittest.TestCase):
    def test_semantic_path_returns_decrypted_evidence(self):
        from vault_brain_retrieval import (
            retrieve_evidence, RETRIEVAL_MODE_SEMANTIC,
        )
        cur = _FakeCursor()
        cur.queue_fetchall([
                                                              
                                                                   
            ("c-1", "f1", 0, "ENC(blue contract)", 0, 40, "pdf_text", 0.92),
            ("c-2", "f2", 0, "ENC(other text)",    0, 20, "pdf_text", 0.78),
        ])
        conn = _FakeConn(cur)

        async def fake_embed(text):
            return [0.1] * 1536

        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: b.replace("ENC(", "").rstrip(")")):
            bundle = _run(retrieve_evidence(
                vault_id="v1", query="blue contract",
                key=b"K" * 32, embed_fn=fake_embed,
                coverage={"total": 10, "analyzed": 10},
            ))
        self.assertEqual(bundle.retrieval_mode, RETRIEVAL_MODE_SEMANTIC)
        self.assertEqual(len(bundle.chunks), 2)
        self.assertEqual(bundle.matching_file_ids, ("f1", "f2"))
                                    
        sql = cur.queries[0][0]
        self.assertIn("vault_id = %s", sql)
        self.assertIn("ORDER BY embedding <=> %s::vector", sql)

    def test_lexical_fallback_when_embedder_returns_none(self):
        from vault_brain_retrieval import (
            retrieve_evidence,
            RETRIEVAL_MODE_LEXICAL,
            RETRIEVAL_MODE_CHUNK_LEXICAL,
        )
        cur = _FakeCursor()
                                                                 
                                                                  
        cur.queue_fetchall([])                                          
        cur.queue_fetchall([
            ("c-1", "f1", 0, "ENC(blue)", 0, 20, "pdf_text", 0.0),
        ])
        conn = _FakeConn(cur)

        async def fake_embed(text):
            return None                        

        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: "blue"):
            bundle = _run(retrieve_evidence(
                vault_id="v1",
                                                           
                                                               
                query="blue contract",
                key=b"K" * 32, embed_fn=fake_embed,
                coverage={},
            ))
        self.assertIn(
            bundle.retrieval_mode,
            (RETRIEVAL_MODE_LEXICAL, RETRIEVAL_MODE_CHUNK_LEXICAL),
        )
        self.assertEqual(len(bundle.chunks), 1)

    def test_empty_query_returns_empty_bundle_no_db_call(self):
        from vault_brain_retrieval import retrieve_evidence

        async def fake_embed(text):
            return [0.1] * 1536

        with mock.patch("vault_core.get_db") as gdb:
            b = _run(retrieve_evidence(
                vault_id="v1", query="   ", key=b"K", embed_fn=fake_embed,
                coverage={},
            ))
        gdb.assert_not_called()
        self.assertFalse(b.has_evidence)

    def test_decrypt_failure_dropped_silently(self):
        from vault_brain_retrieval import retrieve_evidence
        cur = _FakeCursor()
        cur.queue_fetchall([
            ("c-1", "f1", 0, "BAD", 0, 20, "pdf_text", 0.9),
            ("c-2", "f1", 1, "OK",  20, 40, "pdf_text", 0.8),
        ])
        conn = _FakeConn(cur)

        async def fake_embed(text):
            return [0.1] * 1536

        def dec(b, k):
            if b == "BAD":
                raise RuntimeError("decrypt failed")
            return "ok plaintext"

        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message", side_effect=dec):
            bundle = _run(retrieve_evidence(
                vault_id="v1", query="x", key=b"K", embed_fn=fake_embed,
                coverage={},
            ))
        self.assertEqual(len(bundle.chunks), 1)

    def test_credential_memory_sweep_finds_all_matching_files(self):
        from vault_brain_retrieval import (
            retrieve_credential_evidence,
            RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        )
        cur = _FakeCursor()
        cur.queue_fetchall([
            ("c-1", "f1", 0, "ENC1", 0, 60, "file_text"),
            ("c-2", "f2", 0, "ENC2", 0, 60, "file_text"),
            ("c-3", "f3", 0, "ENC3", 0, 40, "file_text"),
        ])
        conn = _FakeConn(cur)

        plaintext = {
            "ENC1": "Gmail\nusername: a@example.com\npassword: secret-one\n",
            "ENC2": "Yahoo\nusername: b@example.com\npassword: secret-two\n",
            "ENC3": "plain note without a login",
        }

        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: plaintext[b]):
            bundle = _run(retrieve_credential_evidence(
                vault_id="v1",
                query="which files have credentials",
                key=b"K" * 32,
                coverage={"total": 3},
            ))

        self.assertEqual(
            bundle.retrieval_mode, RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        )
        self.assertEqual(bundle.matching_file_ids, ("f1", "f2"))
        self.assertEqual(len(bundle.chunks), 2)
        self.assertIn("vault_id = %s", cur.queries[0][0])

    def test_credential_memory_sweep_reads_extracted_text_when_chunks_missing(self):
        from vault_brain_retrieval import (
            retrieve_credential_evidence,
            RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        )
        cur = _FakeCursor()
        cur.queue_fetchall([])
        cur.queue_fetchall([
            ("f-html", "ENC_HTML", True, "text_extraction"),
            ("f-js", "ENC_JS", True, "text_extraction"),
            ("f-note", "ENC_NOTE", True, "text_extraction"),
        ])
        conn = _FakeConn(cur)
                                                                   
                                                                   
        plaintext = {
            "ENC_HTML": (
                "Yahoo Mail\nusername: a@example.com\n"
                "password: secret-one"
            ),
            "ENC_JS": (
                "Gmail account\nusername: chosen@gmail.com\n"
                "password: secret-two"
            ),
            "ENC_NOTE": "plain note without credentials",
        }

        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: plaintext[b]):
            bundle = _run(retrieve_credential_evidence(
                vault_id="v1",
                query="which files have credentials",
                key=b"K" * 32,
                coverage={"total": 3},
            ))

        self.assertEqual(
            bundle.retrieval_mode, RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        )
        self.assertEqual(bundle.matching_file_ids, ("f-html", "f-js"))
        self.assertEqual(len(bundle.chunks), 2)
        self.assertIn("uploaded_files", cur.queries[1][0])
        self.assertIn("vault_id::text = %s", cur.queries[1][0])

    def test_single_credential_lookup_gmail_via_extracted_text(self):


        from vault_brain_retrieval import (
            retrieve_credential_evidence,
            RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        )
        cur = _FakeCursor()
                                                                     
        cur.queue_fetchall([])
        cur.queue_fetchall([
            ("f-gmail", "ENC_GMAIL", True, "text_extraction"),
            ("f-note",  "ENC_NOTE",  True, "text_extraction"),
        ])
        conn = _FakeConn(cur)
        plaintext = {
            "ENC_GMAIL": (
                "Gmail account\nusername: chosen@gmail.com\n"
                "password: secret-gmail-pass"
            ),
            "ENC_NOTE": (
                "shopping list:\n- bread\n- milk\n- eggs"
            ),
        }
        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: plaintext[b]):
            bundle = _run(retrieve_credential_evidence(
                vault_id="v1",
                query="what's my gmail password?",
                key=b"K" * 32,
                coverage={"total": 2, "scanned": 2},
            ))
                                                                 
                                                               
        self.assertEqual(
            bundle.retrieval_mode, RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        )
        self.assertEqual(bundle.matching_file_ids, ("f-gmail",))
        self.assertEqual(len(bundle.chunks), 1)
                                                                    
                                                                   
        debug = bundle.to_debug_dict()
                                                  
        self.assertNotIn("text", debug)
        self.assertNotIn("secret-gmail-pass", str(debug))
        self.assertNotIn("chosen@gmail.com", str(debug))
                                                            
                                                            
        self.assertEqual(
            bundle.chunks[0].extraction_source, "text_extraction",
        )

    def test_single_credential_lookup_no_credentials_returns_empty(self):


        from vault_brain_retrieval import (
            retrieve_credential_evidence,
            RETRIEVAL_MODE_EMPTY,
        )
        cur = _FakeCursor()
        cur.queue_fetchall([])
        cur.queue_fetchall([
            ("f-note", "ENC_NOTE", True, "text_extraction"),
        ])
        conn = _FakeConn(cur)
        plaintext = {
            "ENC_NOTE": "shopping list:\n- bread\n- milk\n- eggs",
        }
        with mock.patch("vault_core.get_db", return_value=conn), \
             mock.patch("vault_core.decrypt_message",
                        side_effect=lambda b, k: plaintext[b]):
            bundle = _run(retrieve_credential_evidence(
                vault_id="v1",
                query="what's my gmail password?",
                key=b"K" * 32,
                coverage={"total": 1, "scanned": 1},
            ))
        self.assertEqual(bundle.retrieval_mode, RETRIEVAL_MODE_EMPTY)
        self.assertEqual(bundle.matching_file_ids, ())
        self.assertEqual(len(bundle.chunks), 0)


class CredentialVerifierMetadataTests(unittest.TestCase):
    def test_credential_verifier_receives_uploaded_file_metadata(self):
        from vault_brain_retrieval import _strict_credential_file_verified

        captured = {}

        def fake_report(rows, *, limit=1, coverage=None):
            captured.update(rows[0])
            return {"matches": [{"file_name": rows[0]["file_name"]}]}

        with mock.patch(
            "vault_inventory.verified_credential_files_report",
            side_effect=fake_report,
        ):
            ok = _strict_credential_file_verified(
                file_id="file-123",
                plaintext="Gmail\nusername: a@example.com\npassword: pass",
                extraction_source="text_extraction",
                file_meta={
                    "file_name": "credentials.html",
                    "saved_name": "saved credentials",
                    "relative_path": "imports/credentials.html",
                    "content_type": "application/octet-stream",
                    "asset_type": "file",
                    "content_sha256": "abc123",
                    "file_size": 99,
                    "detected_service": "gmail",
                    "detected_type": "credentials",
                },
            )

        self.assertTrue(ok)
        self.assertEqual(captured["id"], "file-123")
        self.assertEqual(captured["file_name"], "credentials.html")
        self.assertEqual(captured["relative_path"], "imports/credentials.html")
        self.assertEqual(
            captured["content_type"], "application/octet-stream",
        )
        self.assertEqual(captured["detected_service"], "gmail")


class BrainWorkerDrainTests(unittest.TestCase):
    def test_unhandled_stage_is_released_back(self):
        from vault_brain_worker import drain_content_chunking
        import vault_analysis as va

        class _StubJob:
            pass

                                                                 
        with mock.patch.object(
            va, "claim_next_analysis_job",
            side_effect=[
                {"job_id": "j1", "stage": "ocr", "file_id": "f1"},
                None,
            ],
        ), mock.patch.object(va, "fail_analysis_job") as fail_mock:
            report = drain_content_chunking(
                vault_id="v1", key=b"K" * 32, max_jobs=4,
            )
                                                               
        fail_mock.assert_called_once()
        kwargs = fail_mock.call_args.kwargs
        self.assertTrue(kwargs.get("retry"))
        self.assertEqual(report["processed"], 0)

    def test_max_jobs_zero_returns_empty(self):
        from vault_brain_worker import drain_content_chunking
        report = drain_content_chunking(
            vault_id="v1", key=b"K" * 32, max_jobs=0,
        )
        self.assertEqual(report["processed"], 0)
        self.assertEqual(report["succeeded"], 0)
        self.assertEqual(report["failed"], 0)


class SourceSafetyTests(unittest.TestCase):
    def test_chunk_store_does_not_log_chunk_text(self):
                                                                
                                                                      
        import vault_chunk_store as vcs
        src = inspect.getsource(vcs)
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
            for forbidden in (
                " plaintext", " text,", " text)",
                "encrypted_chunk_text",
            ):
                self.assertNotIn(
                    forbidden, line,
                    f"chunk_store may log chunk text: {line!r}",
                )

    def test_brain_retrieval_does_not_log_query_text(self):
        import vault_brain_retrieval as vbr
        src = inspect.getsource(vbr)
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
                                                                     
                            
            self.assertNotIn(
                " query", line,
                f"brain_retrieval may log the query text: {line!r}",
            )


if __name__ == "__main__":
    unittest.main()
