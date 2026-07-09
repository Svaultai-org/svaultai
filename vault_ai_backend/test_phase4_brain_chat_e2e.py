

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


@unittest.skipUnless(
    _have_test_database_url(),
    "Phase 4 E2E requires VAULTAI_TEST_DATABASE_URL "
    "(separate from DATABASE_URL)",
)
class _Phase4ChatBrainBase(unittest.TestCase):
    SENTINEL = "The blue contract expires on 2027-08-19."

    def setUp(self):
        if not _have_test_database_url():
            self.skipTest(f"{_TEST_DB_ENV_VAR} missing")
        self.vault_id = str(uuid.uuid4())
        self.key = os.urandom(32)
        try:
            self._seed_vault()
        except Exception as exc:
            if (
                "vault_content_chunks" in str(exc)
                or "does not exist" in str(exc)
                or "OperationalError" in type(exc).__name__
            ):
                self.skipTest(
                    f"phase 4 schema not present in test DB: {exc!s}"
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
                (self.vault_id, "phase4-e2e-" + self.vault_id[:8]),
            )
            cur.execute(
                "SELECT COUNT(*) FROM vault_content_chunks "
                "WHERE vault_id = %s",
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
        file_id = "p4-" + uuid.uuid4().hex[:10]
        encrypted_extracted = encrypt_message(sentinel_text, self.key)
        encrypted_blob = encrypt_bytes(
            sentinel_text.encode("utf-8"), self.key,
        )
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

    def _seed_and_index_sentinel(
        self, *, file_name: str, body_text: str,
    ) -> str:


        from vault_chunker import chunk_extracted_text
        from vault_chunk_store import write_chunks
        from vault_brain_indexer import index_chunks_for_file

        file_id = self._seed_file_with_extracted_text(
            file_name=file_name, sentinel_text=body_text,
        )
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
            batch_limit=len(chunks),
        ))
        return file_id


class FullChatBrainAcceptanceTests(_Phase4ChatBrainBase):


    def test_blue_contract_question_finds_sentinel_through_chat(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        prefix = "Generic legal preamble text. " * 30
        suffix = " Generic legal closing text. " * 30
        body = prefix + self.SENTINEL + suffix
        file_id = self._seed_and_index_sentinel(
            file_name="contract-2027.pdf", body_text=body,
        )

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="Do I have anything about a blue contract?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 1, "analyzed": 1, "scan_complete": True},
            top_k=5,
            min_similarity=0.01,
        ))
        self.assertTrue(
            decision.handled,
            f"brain pipeline did not handle the turn: {decision.to_dict()}",
        )
        self.assertEqual(decision.intent, "search_vault_content")
        self.assertFalse(decision.no_evidence)
                                                                   
                                                              
        self.assertIn(
            "contract-2027.pdf", decision.reply_body,
            "the filename must appear in the cited reply",
        )
        self.assertIn(
            self.SENTINEL, decision.reply_body,
            "the actual sentinel sentence must appear in the reply — "
            "that's the user-facing acceptance of 'answer from the "
            "actual text'",
        )
                                                       
        self.assertTrue(decision.evidence_rows)
                                                                    
        for row in decision.evidence_rows:
            self.assertEqual(row.file_id, file_id)
            self.assertEqual(row.file_name, "contract-2027.pdf")

    def test_files_that_mention_a_date_returns_the_file(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        body = (
            "Generic legal preamble text. "
            + self.SENTINEL + " "
            + "Generic legal closing text. " * 20
        )
        file_id = self._seed_and_index_sentinel(
            file_name="contract-2027.pdf", body_text=body,
        )

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="What files mention 2027-08-19?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 1, "analyzed": 1, "scan_complete": True},
            top_k=5,
            min_similarity=0.01,
        ))
        self.assertTrue(decision.handled)
                                                                     
                                           
        self.assertIn("contract-2027.pdf", decision.reply_body)
        self.assertTrue(any(
            row.file_id == file_id
            for row in decision.evidence_rows
        ))

    def test_unrelated_query_does_not_hallucinate(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

                                                                   
        self._seed_and_index_sentinel(
            file_name="contract-2027.pdf",
            body_text=self.SENTINEL,
        )

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="Do I have anything about quantum mechanics?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 1, "analyzed": 1, "scan_complete": True},
            top_k=5,
            min_similarity=0.01,
        ))
                                                                      
                                                                   
        self.assertTrue(decision.handled)
                                                                        
                                                                    
        self.assertTrue(decision.no_evidence)
        self.assertIn("couldn't find matching vault content",
                      decision.reply_body)

    def test_cross_vault_query_returns_honest_no_evidence(self):


        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        self._seed_and_index_sentinel(
            file_name="contract-2027.pdf",
            body_text=self.SENTINEL,
        )

        attacker_vault = str(uuid.uuid4())
        decision = _run(run_brain_chat_pipeline(
            vault_id=attacker_vault,
            message="Do I have anything about a blue contract?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 0, "scan_complete": True},
        ))
        self.assertTrue(decision.handled)
        self.assertTrue(decision.no_evidence)
        self.assertIn(
            "couldn't find matching vault content",
            decision.reply_body,
        )
        self.assertEqual(decision.evidence_rows, ())


class CredentialThroughBrainTests(_Phase4ChatBrainBase):


    CRED_BODY = (
        "Chase Bank\n"
        "username: alice@example.com\n"
        "password: hunter22-ZX9\n"
        "routing number: 124003116\n"
    )

    def test_credential_question_uses_chunk_evidence(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        file_id = self._seed_and_index_sentinel(
            file_name="logins.txt", body_text=self.CRED_BODY,
        )

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="What did I save about my Chase login?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 1, "analyzed": 1, "scan_complete": True},
            top_k=5,
            min_similarity=0.01,
        ))
        self.assertTrue(decision.handled)
        self.assertEqual(decision.intent, "credential_lookup")
                                        
        self.assertIn("Chase", decision.reply_body)
                                  
        self.assertIn("logins.txt", decision.reply_body)
                                                                       
        self.assertNotIn("hunter22-ZX9", decision.reply_body)
                                                
        self.assertTrue(any(
            row.file_id == file_id
            for row in decision.evidence_rows
        ))


class EmptyVaultHonestyTests(_Phase4ChatBrainBase):


    def test_blue_contract_question_on_empty_vault(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="Do I have anything about a blue contract?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 0, "scan_complete": True},
        ))
        self.assertTrue(decision.handled)
        self.assertTrue(decision.no_evidence)
        self.assertIn(
            "couldn't find matching vault content",
            decision.reply_body,
        )

    def test_pending_files_get_honest_hint(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="What files mention insurance?",
            key=self.key,
            embed_fn=fake_embed,
            coverage={
                "total": 5,
                "analyzed": 2,
                "pending": 3,
                "scan_complete": False,
            },
        ))
                                                                    
        self.assertTrue(decision.no_evidence)
                                          
        self.assertIn(
            "couldn't find matching vault content",
            decision.reply_body,
        )


class NonVaultContentSkipsRetrievalTests(_Phase4ChatBrainBase):


    def test_imperative_skips_retrieval(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        retrieved = {"called": False}

        async def _retrieve(**_kwargs):
            retrieved["called"] = True
            raise AssertionError("must not be called")

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="save my Gmail password as foo",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 0, "scan_complete": True},
            retrieve_fn=_retrieve,
        ))
        self.assertFalse(decision.handled)
        self.assertFalse(retrieved["called"])

    def test_list_logins_skips_retrieval(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline

        retrieved = {"called": False}

        async def _retrieve(**_kwargs):
            retrieved["called"] = True
            raise AssertionError("must not be called")

        decision = _run(run_brain_chat_pipeline(
            vault_id=self.vault_id,
            message="show me my saved logins",
            key=self.key,
            embed_fn=fake_embed,
            coverage={"total": 0, "scan_complete": True},
            retrieve_fn=_retrieve,
        ))
        self.assertFalse(decision.handled)
        self.assertFalse(retrieved["called"])


if __name__ == "__main__":
    unittest.main()
