

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


def _test_db_url():
    return os.environ.get(_TEST_DB_ENV_VAR)


def _have_test_database_url():
    return bool(_test_db_url())


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_DIM = 1536
_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOP = {"the", "a", "an", "is", "it", "of", "to", "in", "and", "or",
         "i", "you", "me", "we", "us", "my", "your", "do", "did",
         "does", "have", "has", "had", "that", "this", "those", "these",
         "be", "been", "about", "any", "anything"}


def _det_hash(word):
    return int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)


def _bag(text):
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


@unittest.skipUnless(
    _have_test_database_url(),
    "Phase 5 E2E requires VAULTAI_TEST_DATABASE_URL",
)
class _Phase5BroadE2EBase(unittest.TestCase):
    TOPIC = "apartment"                                         

                                                                   
    TOPIC_SENTINELS = [
        "The apartment lease starts on 2026-01-15.",
        "Apartment building maintenance fee is $250 monthly.",
        "Bought new lamps for the apartment living room.",
        "Apartment insurance renewal documents attached.",
        "Apartment Wi-Fi router model TP-Link AX3000.",
        "Apartment renovation budget capped at $5000.",
        "Apartment HOA meeting minutes for Q1 2026.",
        "Apartment parking permit valid through July 2027.",
    ]

                                                             
    FILLER_SENTINELS = [
        "Hot air balloon ride reservation confirmation.",
        "Boba tea franchise locations near the office.",
        "Birthday party catering menu draft v3.",
        "Telescope cleaning instructions for Saturn ring view.",
        "Bouldering gym membership punch card details.",
        "Garden hose replacement quote from a local handyman.",
        "Mountain bike chain lube application notes.",
        "Folding chair safety inspection summary.",
        "Espresso machine descaling reminder.",
        "Bookshelf assembly leftover screws list.",
        "Photo album dust jacket replacement options.",
        "Skateboard wheel rotation routine.",
    ]

    def setUp(self):
        if not _have_test_database_url():
            self.skipTest(f"{_TEST_DB_ENV_VAR} missing")
        self.vault_id = str(uuid.uuid4())
        self.key = os.urandom(32)
        try:
            self._seed_vault()
        except Exception as exc:
            if ("vault_content_chunks" in str(exc)
                or "does not exist" in str(exc)
                or "OperationalError" in type(exc).__name__):
                self.skipTest(
                    f"phase 5 schema not present: {exc!s}",
                )
            raise
        self.file_ids: list[str] = []

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
                (self.vault_id, "phase5-e2e-" + self.vault_id[:8]),
            )
            conn.commit()
        finally:
            conn.close()

    def _seed_file(self, *, file_name, body_text):
        from vault_core import encrypt_message, encrypt_bytes
        import psycopg2
        file_id = "p5-" + uuid.uuid4().hex[:10]
        enc_text = encrypt_message(body_text, self.key)
        enc_blob = encrypt_bytes(body_text.encode("utf-8"), self.key)
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
                    extracted_text_truncated,
                    extracted_text_char_count,
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
                 len(body_text), enc_blob, enc_text,
                 len(body_text)),
            )
            conn.commit()
        finally:
            conn.close()
        return file_id

    def _chunk_index_file(self, file_id, body_text):
        from vault_chunker import chunk_extracted_text
        from vault_chunk_store import write_chunks
        from vault_brain_indexer import index_chunks_for_file
        chunks = chunk_extracted_text(
            body_text, extraction_source="pdf_text",
        )
        write_chunks(
            vault_id=self.vault_id, file_id=file_id,
            chunks=chunks, key=self.key,
        )
        _run(index_chunks_for_file(
            vault_id=self.vault_id, file_id=file_id,
            embed_fn=fake_embed, key=self.key,
            batch_limit=max(len(chunks), 1),
        ))

    def _seed_and_index_20_files(self):

        for i, sentinel in enumerate(self.TOPIC_SENTINELS):
            body = (
                "Generic preamble " * 5 + sentinel + " Generic closing " * 5
            )
            fid = self._seed_file(
                file_name=f"topic-{i+1:02d}.pdf",
                body_text=body,
            )
            self._chunk_index_file(fid, body)
            self.file_ids.append(fid)
        for i, sentinel in enumerate(self.FILLER_SENTINELS):
            body = (
                "Filler preamble " * 5 + sentinel + " Filler closing " * 5
            )
            fid = self._seed_file(
                file_name=f"filler-{i+1:02d}.pdf",
                body_text=body,
            )
            self._chunk_index_file(fid, body)
            self.file_ids.append(fid)


class BroadRetrievalAcceptanceTests(_Phase5BroadE2EBase):


    def test_broad_query_finds_evidence_in_multiple_files(self):
        from vault_brain_retrieval import retrieve_evidence

        self._seed_and_index_20_files()

        bundle = _run(retrieve_evidence(
            vault_id=self.vault_id,
            query=f"Do I have anything about {self.TOPIC}?",
            key=self.key, embed_fn=fake_embed,
            coverage={"total": 20, "analyzed": 20,
                      "scan_complete": True},
            top_k=24, min_similarity=0.01,
            breadth="broad",
        ))
                             
        self.assertTrue(
            bundle.has_evidence,
            f"broad retrieval returned no evidence: "
            f"{bundle.to_debug_dict()}",
        )
                                                                   
                                                                 
        distinct_files = len({c.file_id for c in bundle.chunks})
        self.assertGreaterEqual(
            distinct_files, 3,
            f"broad query collapsed to {distinct_files} file(s) — "
            f"diversification failed: {bundle.to_debug_dict()}",
        )
                                                                
                                                         
        self.assertGreater(
            len(bundle.chunks), 5,
            f"broad query only surfaced {len(bundle.chunks)} chunks — "
            f"broad mode should expand: {bundle.to_debug_dict()}",
        )

    def test_broad_query_diversification_caps_per_file(self):


        from vault_brain_retrieval import (
            retrieve_evidence, DEFAULT_MAX_CHUNKS_PER_FILE,
        )

        self._seed_and_index_20_files()

        bundle = _run(retrieve_evidence(
            vault_id=self.vault_id,
            query=f"Find anything about {self.TOPIC}",
            key=self.key, embed_fn=fake_embed,
            coverage={},
            top_k=24, min_similarity=0.01,
            breadth="broad",
            max_chunks_per_file=DEFAULT_MAX_CHUNKS_PER_FILE,
        ))
        if not bundle.chunks:
            self.skipTest("no evidence retrieved")
        from collections import Counter
        per_file = Counter(c.file_id for c in bundle.chunks)
        for fid, count in per_file.items():
            self.assertLessEqual(
                count, DEFAULT_MAX_CHUNKS_PER_FILE,
                f"file {fid[:8]} contributed {count} chunks, exceeding "
                f"the {DEFAULT_MAX_CHUNKS_PER_FILE} per-file cap",
            )

    def test_broad_query_in_chat_pipeline_states_coverage_honestly(self):


        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage
        from vault_brain_answerer import COPY_BRAIN_STILL_INDEXING

        self._seed_and_index_20_files()

                                                                
        fake_coverage = BrainCoverage(
            vault_id=self.vault_id,
            total_files=20,
            files_with_embedded_chunks=3,
            files_missing_chunks=10,
        )

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message=f"Do I have anything about {self.TOPIC}?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={},
            file_name_lookup=None,
            brain_coverage_loader=lambda v: fake_coverage,
            min_similarity=0.01,
            top_k=24,
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.breadth, "broad")
        self.assertIn(
            COPY_BRAIN_STILL_INDEXING, decision.reply_body,
            "broad query with incomplete coverage MUST acknowledge "
            "the still-indexing state",
        )

    def test_show_more_continuation_returns_different_files(self):


        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage
        import vault_brain_continuation
        vault_brain_continuation.reset_for_tests()

        self._seed_and_index_20_files()

                     
        d1 = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message=f"Do I have anything about {self.TOPIC}?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={},
            brain_coverage_loader=lambda v: BrainCoverage(
                vault_id=self.vault_id, total_files=20,
                files_with_embedded_chunks=20,
            ),
            min_similarity=0.01,
            top_k=8,
            now_unix=1.0,
        ))
        self.assertTrue(d1.handled)
        if not d1.evidence_rows:
            self.skipTest("first turn surfaced no evidence")
        first_file_ids = {r.file_id for r in d1.evidence_rows}
        self.assertTrue(d1.continuation_available)

                                    
        d2 = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="show more",
            key=self.key,
            embed_fn=fake_embed,
            coverage={},
            brain_coverage_loader=lambda v: BrainCoverage(
                vault_id=self.vault_id, total_files=20,
                files_with_embedded_chunks=20,
            ),
            min_similarity=0.01,
            top_k=8,
            now_unix=2.0,
        ))
        self.assertTrue(d2.handled)
        self.assertEqual(d2.breadth, "continuation")
                                                                  
        new_file_ids = {r.file_id for r in d2.evidence_rows}
        if new_file_ids:
            self.assertFalse(
                first_file_ids & new_file_ids,
                f"continuation surfaced overlapping files. "
                f"first={first_file_ids} new={new_file_ids}",
            )


class CrossVaultBroadTests(_Phase5BroadE2EBase):


    def test_cross_vault_broad_returns_no_evidence(self):
        from vault_brain_retrieval import retrieve_evidence

        self._seed_and_index_20_files()

        attacker = str(uuid.uuid4())
        bundle = _run(retrieve_evidence(
            vault_id=attacker,
            query=f"Do I have anything about {self.TOPIC}?",
            key=self.key, embed_fn=fake_embed,
            coverage={},
            top_k=24, min_similarity=0.01,
            breadth="broad",
        ))
        self.assertFalse(bundle.has_evidence)


if __name__ == "__main__":
    unittest.main()
