

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import unittest
import uuid

from dotenv import load_dotenv
load_dotenv(".env")


_TEST_DB_ENV_VAR = "VAULTAI_TEST_DATABASE_URL"


def _test_db_url() -> str | None:
    return os.environ.get(_TEST_DB_ENV_VAR)


def _have_test_database_url() -> bool:
    return bool(_test_db_url())


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_DIM = 1536
_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOP = {"the", "a", "an", "is", "it", "of", "to", "in", "and", "or",
         "i", "you", "me", "we", "us", "my", "your", "do", "did",
         "does", "have", "has", "had", "that", "this", "those", "these",
         "be", "been", "about", "any", "anything"}


def _det_hash(word: str) -> int:
    return int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)


def _bag(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if raw in _STOP:
            continue
        vec[_det_hash(raw) % _DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


async def fake_embed(text):
    return _bag(text)


@unittest.skipUnless(_have_test_database_url(),
    "Phase 3 E2E requires VAULTAI_TEST_DATABASE_URL "
    "(separate from DATABASE_URL)")
class _Phase3E2EBase(unittest.TestCase):


    SENTINEL = "The blue contract expires on 2027-08-19."

    def setUp(self):
        if not _have_test_database_url():
            self.skipTest(f"{_TEST_DB_ENV_VAR} missing")
        self.vault_id = str(uuid.uuid4())
        self.key = os.urandom(32)
        try:
            self._seed_vault()
        except Exception as exc:
                                                                    
                                                               
            if "vault_content_chunks" in str(exc) \
                    or "does not exist" in str(exc) \
                    or "OperationalError" in type(exc).__name__:
                self.skipTest(
                    f"phase3 schema not present in test DB: {exc!s}"
                )
            raise

    def tearDown(self):
        try:
            import psycopg2
            conn = psycopg2.connect(_test_db_url())
            cur = conn.cursor()
                                                          
                                                                     
            cur.execute(
                "DELETE FROM vault_content_chunks WHERE vault_id = %s",
                (self.vault_id,),
            )
            cur.execute(
                "DELETE FROM vault_analysis_jobs WHERE vault_id = %s",
                (self.vault_id,),
            )
            cur.execute(
                "DELETE FROM uploaded_files WHERE vault_id = %s",
                (self.vault_id,),
            )
            cur.execute(
                "DELETE FROM vaults WHERE vault_id = %s",
                (self.vault_id,),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    def _seed_vault(self):
        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO vaults (vault_id, vault_name, pin_salt,
                                       pin_verifier)
                   VALUES (%s, %s, '0', '0')""",
                (self.vault_id, "phase3-e2e-" + self.vault_id[:8]),
            )
                                                                  
                                                                 
            cur.execute(
                "SELECT COUNT(*) FROM vault_content_chunks WHERE vault_id = %s",
                (self.vault_id,),
            )
            cur.fetchone()
            conn.commit()
        finally:
            conn.close()

    def _seed_file_with_extracted_text(
        self, *, file_name: str, sentinel_text: str,
    ) -> str:


        from vault_core import encrypt_message, encrypt_bytes
        import psycopg2
        file_id = "p3-" + uuid.uuid4().hex[:10]
        encrypted_extracted = encrypt_message(sentinel_text, self.key)
        encrypted_blob = encrypt_bytes(sentinel_text.encode("utf-8"),
                                       self.key)
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO uploaded_files (
                    id, vault_id, file_name, content_type, file_size,
                    encrypted_file_data, extracted_text,
                    extracted_text_encrypted, autosaved_secret,
                    needs_naming, storage_mode, upload_status,
                    created_at, version_number, analysis_status,
                    analysis_pipeline_state, extracted_text_status,
                    extracted_text_source,
                    extracted_text_truncated, extracted_text_char_count,
                    extracted_text_version
                ) VALUES (
                    %s, %s, %s, 'application/pdf', %s,
                    %s, %s,
                    TRUE, FALSE,
                    FALSE, 'inline', 'complete',
                    NOW(), 1, 'analyzed',
                    '{}'::jsonb, 'available',
                    'worker',
                    FALSE, %s,
                    1
                )
                """,
                (file_id, self.vault_id, file_name,
                 len(sentinel_text), encrypted_blob,
                 encrypted_extracted, len(sentinel_text)),
            )
            conn.commit()
        finally:
            conn.close()
        return file_id


class FullBrainSentinelRetrievalTests(_Phase3E2EBase):


    def test_chunk_index_embed_retrieve_loop_finds_sentinel(self):
        from vault_chunker import chunk_extracted_text
        from vault_chunk_store import (
            write_chunks, fetch_chunks_for_file, count_chunks_for_vault,
        )
        from vault_brain_indexer import index_chunks_for_file
        from vault_brain_retrieval import retrieve_evidence

                                                                    
        prefix = "Generic legal preamble text. " * 30
        suffix = " Generic legal closing text. " * 30
        full = prefix + self.SENTINEL + suffix
        file_id = self._seed_file_with_extracted_text(
            file_name="contract-2027.pdf",
            sentinel_text=full,
        )

                                                                  
        chunks = chunk_extracted_text(full, extraction_source="pdf_text")
        written = write_chunks(
            vault_id=self.vault_id, file_id=file_id,
            chunks=chunks, key=self.key,
        )
        self.assertEqual(written, len(chunks))
        self.assertGreater(written, 0)

                                                                  
        fetched = fetch_chunks_for_file(
            vault_id=self.vault_id, file_id=file_id, key=self.key,
        )
        found_sentinel_in_chunks = any(self.SENTINEL in c.text
                                       for c in fetched)
        self.assertTrue(
            found_sentinel_in_chunks,
            "the sentinel sentence must appear in at least one "
            "decrypted chunk after the round-trip",
        )

                                                                   
        report = _run(index_chunks_for_file(
            vault_id=self.vault_id, file_id=file_id,
            embed_fn=fake_embed, key=self.key,
            batch_limit=len(chunks),
        ))
        self.assertEqual(report.chunks_embedded, len(chunks))
        self.assertEqual(report.chunks_failed, 0)

                                                        
        counts = count_chunks_for_vault(self.vault_id)
        self.assertEqual(counts["total"], len(chunks))
        self.assertEqual(counts["embedded"], len(chunks))
        self.assertEqual(counts["unembedded"], 0)

                                                               
        bundle = _run(retrieve_evidence(
            vault_id=self.vault_id,
            query="Do I have anything about a blue contract?",
            key=self.key, embed_fn=fake_embed,
            coverage={"total": 1, "analyzed": 1,
                      "scan_complete": True},
            top_k=5, min_similarity=0.01,
        ))
        self.assertTrue(bundle.has_evidence,
            f"retrieval returned no evidence: {bundle.to_debug_dict()}")
        self.assertIn(
            file_id, bundle.matching_file_ids,
            "the seeded file MUST appear in matching_file_ids — "
            "the retrieval is bound by vault_id but ranked by content",
        )
        snippets_joined = " ".join(c.text for c in bundle.chunks)
        self.assertIn(
            self.SENTINEL, snippets_joined,
            "the actual sentinel sentence MUST appear in at least "
            "one retrieved chunk — that's the user-facing acceptance "
            "of 'answer from the actual text'",
        )

    def test_cross_vault_query_returns_no_evidence(self):


        from vault_chunker import chunk_extracted_text
        from vault_chunk_store import write_chunks
        from vault_brain_indexer import index_chunks_for_file
        from vault_brain_retrieval import retrieve_evidence

                                             
        file_id = self._seed_file_with_extracted_text(
            file_name="contract.pdf",
            sentinel_text=self.SENTINEL,
        )
        chunks = chunk_extracted_text(self.SENTINEL,
                                      extraction_source="pdf_text")
        write_chunks(vault_id=self.vault_id, file_id=file_id,
                     chunks=chunks, key=self.key)
        _run(index_chunks_for_file(
            vault_id=self.vault_id, file_id=file_id,
            embed_fn=fake_embed, key=self.key,
        ))

                                         
        attacker_vault = str(uuid.uuid4())
        bundle = _run(retrieve_evidence(
            vault_id=attacker_vault,
            query="Do I have anything about a blue contract?",
            key=self.key, embed_fn=fake_embed,
            coverage={"total": 0, "scan_complete": True},
        ))
                                                                
                                                                 
        self.assertFalse(bundle.has_evidence)
        self.assertEqual(bundle.matching_file_ids, ())
                                                       
        debug = bundle.to_debug_dict()
        self.assertNotIn("blue contract", repr(debug))

    def test_idempotent_chunk_rewrite_replaces_prior_chunks(self):
        from vault_chunker import chunk_extracted_text
        from vault_chunk_store import write_chunks, count_chunks_for_vault

        file_id = self._seed_file_with_extracted_text(
            file_name="iterating.pdf",
            sentinel_text="first body text " * 50,
        )
        chunks1 = chunk_extracted_text(
            "first body text " * 50, extraction_source="pdf_text",
        )
        write_chunks(vault_id=self.vault_id, file_id=file_id,
                     chunks=chunks1, key=self.key)
        n1 = count_chunks_for_vault(self.vault_id)["total"]
        self.assertEqual(n1, len(chunks1))

                                                                  
        chunks2 = chunk_extracted_text(
            "rewritten body " * 200, extraction_source="pdf_text",
        )
        write_chunks(vault_id=self.vault_id, file_id=file_id,
                     chunks=chunks2, key=self.key)
        n2 = count_chunks_for_vault(self.vault_id)["total"]
        self.assertEqual(n2, len(chunks2),
            "second write must REPLACE the first chunk set, "
            "not append to it")


if __name__ == "__main__":
    unittest.main()
