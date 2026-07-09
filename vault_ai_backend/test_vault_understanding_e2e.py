

from __future__ import annotations

import asyncio
import io
import os
import unittest
import uuid

from dotenv import load_dotenv
load_dotenv(".env")


_TEST_DB_ENV_VAR = "VAULTAI_TEST_DATABASE_URL"


def _test_db_url() -> str | None:
    return os.environ.get(_TEST_DB_ENV_VAR)


def _have_test_database_url() -> bool:
    return bool(_test_db_url())


@unittest.skipUnless(_have_test_database_url(),
    "E2E test requires VAULTAI_TEST_DATABASE_URL to be set "
    "(separate from DATABASE_URL — the app's primary DB must "
    "never be used as a test target)")
class _E2EBase(unittest.TestCase):


    SENTINEL = "The agreement is signed on 2026-05-15. PHASE1-SENTINEL-OK."

    def setUp(self) -> None:
                                                                     
                                                                  
        self.vault_id = str(uuid.uuid4())
        self.token_id = "e2e-" + uuid.uuid4().hex[:12]
        self.key = os.urandom(32)
        from vault_key_cache import reset_for_tests
        reset_for_tests(idle_ttl_seconds=300, hard_ttl_seconds=3600)
        self._inserted_file_ids: list[str] = []
        self._seed_throwaway_vault()

    def _seed_throwaway_vault(self) -> None:
        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
                                                                   
                                                                
            cur.execute(
                """
                INSERT INTO vaults (
                    vault_id, vault_name, pin_salt, pin_verifier
                ) VALUES (
                    %s, %s, %s, %s
                )
                """,
                (
                    self.vault_id,
                    "phase1-e2e-" + self.vault_id[:8],
                    "00000000",                                         
                    "00000000",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
                                                               
        try:
            import psycopg2
            conn = psycopg2.connect(_test_db_url())
            cur = conn.cursor()
                                                                    
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

                                                                        
    def _insert_uploaded_file(
        self, *, file_id: str, file_name: str, content_type: str,
        plaintext_bytes: bytes,
        analysis_status: str = "not_started",
        extracted_text_seed: str | None = None,
    ) -> None:


        from vault_core import encrypt_bytes
        import psycopg2
        encrypted = encrypt_bytes(plaintext_bytes, self.key)
                                                                   
                                                   
        if extracted_text_seed is not None:
            from vault_core import encrypt_message
            extracted_payload = encrypt_message(extracted_text_seed, self.key)
            extracted_status = "available"
            extracted_encrypted = True
            extracted_char_count = len(extracted_text_seed)
        else:
            extracted_payload = None
                                                                
                                                                    
            extracted_status = "not_available"
            extracted_encrypted = False
            extracted_char_count = 0

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
                    extracted_text_truncated, extracted_text_char_count,
                    extracted_text_version
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, FALSE,
                    FALSE, 'inline', 'complete',
                    NOW(), 1, %s,
                    '{}'::jsonb, %s,
                    FALSE, %s,
                    0
                )
                """,
                (
                    file_id, self.vault_id, file_name, content_type,
                    len(plaintext_bytes),
                    encrypted, extracted_payload,
                    extracted_encrypted,
                    analysis_status, extracted_status,
                    extracted_char_count,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._inserted_file_ids.append(file_id)

    def _insert_job(
        self, *, file_id: str, stage: str = "text_extraction",
        status: str = "pending",
    ) -> str:

        import psycopg2
        job_id = str(uuid.uuid4())
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vault_analysis_jobs (
                    job_id, vault_id, file_id, stage, status,
                    attempts, max_attempts, scheduled_at,
                    created_at, updated_at, metadata_jsonb
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    0, 3, NOW(), NOW(), NOW(), '{}'::jsonb
                )
                """,
                (job_id, self.vault_id, file_id, stage, status),
            )
            conn.commit()
        finally:
            conn.close()
        return job_id

    def _file_row(self, file_id: str) -> tuple | None:
        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT analysis_status, extracted_text,
                          extracted_text_char_count
                   FROM uploaded_files
                   WHERE id = %s AND vault_id = %s""",
                (file_id, self.vault_id),
            )
            return cur.fetchone()
        finally:
            conn.close()

    def _activate_key_for_vault(self) -> None:


        from vault_key_cache import get_cache
        get_cache().store(
            vault_id=self.vault_id, token_id=self.token_id, key=self.key,
        )

    def _run_daemon_iteration(self) -> dict:

        from vault_analysis_daemon import (
            run_one_iteration, reset_for_tests as reset_daemon,
        )
        reset_daemon()
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run_one_iteration())
        finally:
            loop.close()


class PlainTextE2ETests(_E2EBase):
    def test_text_file_uploaded_then_daemon_analyzes_then_read_returns_text(self) -> None:
        from vault_read_file import handle_read_file_text_intent

        file_id = "e2e-text-" + uuid.uuid4().hex[:8]
        file_name = "phase1-sentinel.txt"
        self._insert_uploaded_file(
            file_id=file_id, file_name=file_name, content_type="text/plain",
            plaintext_bytes=self.SENTINEL.encode("utf-8"),
        )
        self._insert_job(file_id=file_id, stage="text_extraction")
        self._activate_key_for_vault()

                                                                 
        stats = self._run_daemon_iteration()
        self.assertGreaterEqual(stats["drained"], 1,
            "daemon must claim and process the seeded job")

                                          
        row = self._file_row(file_id)
        self.assertIsNotNone(row)
        analysis_status, encrypted_text, char_count = row
        self.assertEqual(analysis_status, "analyzed",
            "daemon must move file from not_started → analyzed")
        self.assertIsNotNone(encrypted_text,
            "extracted_text must be written")
        self.assertGreater(char_count, 0,
            "char_count must reflect the extracted length")

                                             
        reply = handle_read_file_text_intent(
            vault_id=self.vault_id, query_name=file_name, key=self.key,
        )
        self.assertIn(self.SENTINEL, reply,
            "chat reply must contain the actual sentinel from the file")
        self.assertIn(file_name, reply,
            "reply must reference the file by name")

    def test_filename_contains_match_still_resolves(self) -> None:
        from vault_read_file import handle_read_file_text_intent
        file_id = "e2e-text2-" + uuid.uuid4().hex[:8]
        file_name = "very-specific-sentinel-doc.txt"
        self._insert_uploaded_file(
            file_id=file_id, file_name=file_name, content_type="text/plain",
            plaintext_bytes=self.SENTINEL.encode("utf-8"),
        )
        self._insert_job(file_id=file_id, stage="text_extraction")
        self._activate_key_for_vault()
        self._run_daemon_iteration()

                                          
        reply = handle_read_file_text_intent(
            vault_id=self.vault_id, query_name="sentinel-doc", key=self.key,
        )
        self.assertIn(self.SENTINEL, reply)

    def test_cross_vault_read_refused(self) -> None:


        from vault_read_file import handle_read_file_text_intent
        file_id = "e2e-cross-" + uuid.uuid4().hex[:8]
        file_name = "private-victim.txt"
        self._insert_uploaded_file(
            file_id=file_id, file_name=file_name, content_type="text/plain",
            plaintext_bytes=b"VICTIM-SECRET-MUST-NEVER-LEAK",
        )
        self._insert_job(file_id=file_id, stage="text_extraction")
        self._activate_key_for_vault()
        self._run_daemon_iteration()

                                                
        attacker_vault = str(uuid.uuid4())
        reply = handle_read_file_text_intent(
            vault_id=attacker_vault, query_name=file_name, key=self.key,
        )
        self.assertNotIn("VICTIM", reply,
            "cross-vault read must NEVER leak content")
                                                     
        self.assertIn("don't see", reply.lower())


def _build_test_pdf(sentence: str) -> bytes | None:


    try:
        from reportlab.pdfgen import canvas as _canvas
    except Exception:
        return None
    buf = io.BytesIO()
    c = _canvas.Canvas(buf)
    c.drawString(72, 720, sentence)
    c.save()
    return buf.getvalue()


@unittest.skipUnless(_have_test_database_url() and _build_test_pdf("probe") is not None,
    "PDF E2E test requires reportlab")
class PdfE2ETests(_E2EBase):
    def test_pdf_uploaded_then_analyzed_then_read_returns_text(self) -> None:
        from vault_read_file import handle_read_file_text_intent
        pdf_bytes = _build_test_pdf(self.SENTINEL)
        assert pdf_bytes is not None
        file_id = "e2e-pdf-" + uuid.uuid4().hex[:8]
        file_name = "phase1-sentinel.pdf"
        self._insert_uploaded_file(
            file_id=file_id, file_name=file_name,
            content_type="application/pdf",
            plaintext_bytes=pdf_bytes,
        )
        self._insert_job(file_id=file_id, stage="text_extraction")
        self._activate_key_for_vault()
        self._run_daemon_iteration()

        row = self._file_row(file_id)
        self.assertIsNotNone(row)
        analysis_status, encrypted_text, _ = row
        self.assertEqual(analysis_status, "analyzed")
        self.assertIsNotNone(encrypted_text)

        reply = handle_read_file_text_intent(
            vault_id=self.vault_id, query_name=file_name, key=self.key,
        )
                                                                      
                                                
        self.assertIn("PHASE1-SENTINEL-OK", reply,
            "PDF text extraction must surface the sentinel in the chat reply")


def _build_test_docx(sentence: str) -> bytes | None:
    try:
        from docx import Document
    except Exception:
        return None
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(sentence)
    doc.save(buf)
    return buf.getvalue()


@unittest.skipUnless(_have_test_database_url() and _build_test_docx("probe") is not None,
    "DOCX E2E test requires python-docx")
class DocxE2ETests(_E2EBase):
    def test_docx_uploaded_then_analyzed_then_read_returns_text(self) -> None:
        from vault_read_file import handle_read_file_text_intent
        docx_bytes = _build_test_docx(self.SENTINEL)
        assert docx_bytes is not None
        file_id = "e2e-docx-" + uuid.uuid4().hex[:8]
        file_name = "phase1-sentinel.docx"
        self._insert_uploaded_file(
            file_id=file_id, file_name=file_name,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            plaintext_bytes=docx_bytes,
        )
        self._insert_job(file_id=file_id, stage="text_extraction")
        self._activate_key_for_vault()
        self._run_daemon_iteration()

        row = self._file_row(file_id)
        self.assertIsNotNone(row)
        analysis_status, encrypted_text, _ = row
        self.assertEqual(analysis_status, "analyzed")
        self.assertIsNotNone(encrypted_text)

        reply = handle_read_file_text_intent(
            vault_id=self.vault_id, query_name=file_name, key=self.key,
        )
        self.assertIn(self.SENTINEL, reply,
            "DOCX extraction must surface the sentinel in the chat reply")


class ReconcilerDriftRealDbTests(_E2EBase):
    def test_drifted_status_is_repaired(self) -> None:


        from vault_reconciler import reconcile_vault
        file_id = "e2e-drift-" + uuid.uuid4().hex[:8]
                                                                    
                                                                        
        self._insert_uploaded_file(
            file_id=file_id, file_name="drift.txt", content_type="text/plain",
            plaintext_bytes=b"irrelevant",
            extracted_text_seed=self.SENTINEL,
            analysis_status="not_started",
        )
        report = reconcile_vault(self.vault_id)
        self.assertGreaterEqual(report.status_drift_repaired, 1)
        row = self._file_row(file_id)
        self.assertEqual(row[0], "analyzed",
            "drifted file must be bumped to 'analyzed' by reconciler")

    def test_orphan_queue_row_for_analyzed_file_is_deleted(self) -> None:


        from vault_reconciler import reconcile_vault
        import psycopg2
        file_id = "e2e-orphan-" + uuid.uuid4().hex[:8]
        self._insert_uploaded_file(
            file_id=file_id, file_name="orphan.txt", content_type="text/plain",
            plaintext_bytes=b"x",
            extracted_text_seed=self.SENTINEL,
            analysis_status="analyzed",
        )
                                                                
        self._insert_job(file_id=file_id, stage="text_extraction")
                                              
        conn = psycopg2.connect(_test_db_url())
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM vault_analysis_jobs "
            "WHERE vault_id=%s AND file_id=%s",
            (self.vault_id, file_id),
        )
        before = cur.fetchone()[0]
        conn.close()
        self.assertEqual(before, 1)

        report = reconcile_vault(self.vault_id)
        self.assertGreaterEqual(report.orphan_queue_rows_deleted, 1)

                                                                        
        conn = psycopg2.connect(_test_db_url())
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM vault_analysis_jobs "
            "WHERE vault_id=%s AND file_id=%s AND stage='text_extraction'",
            (self.vault_id, file_id),
        )
        after_text_extraction = cur.fetchone()[0]
        conn.close()
        self.assertEqual(after_text_extraction, 0,
            "reconciler must delete the superseded text_extraction "
            "queue row even when Phase 5 enqueues content_chunking "
            "for the same file.")

    def test_pending_orphan_file_is_enqueued(self) -> None:


        from vault_reconciler import reconcile_vault
        import psycopg2
        file_id = "e2e-porph-" + uuid.uuid4().hex[:8]
        self._insert_uploaded_file(
            file_id=file_id, file_name="pending-orphan.txt",
            content_type="text/plain",
            plaintext_bytes=b"x",
            analysis_status="pending",
        )
                                    
        report = reconcile_vault(self.vault_id)
        self.assertGreaterEqual(report.pending_or_not_started_enqueued, 1)
        conn = psycopg2.connect(_test_db_url())
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM vault_analysis_jobs "
            "WHERE vault_id=%s AND file_id=%s AND status='pending'",
            (self.vault_id, file_id),
        )
        after = cur.fetchone()[0]
        conn.close()
        self.assertGreaterEqual(after, 1,
            "reconciler must create a queue row for the pending-orphan")

    def test_stuck_processing_is_requeued(self) -> None:


        from vault_reconciler import reconcile_vault
        import psycopg2
        file_id = "e2e-stuck-" + uuid.uuid4().hex[:8]
        self._insert_uploaded_file(
            file_id=file_id, file_name="stuck.txt",
            content_type="text/plain",
            plaintext_bytes=b"x",
            analysis_status="pending",
        )
        job_id = self._insert_job(file_id=file_id, stage="text_extraction")
                                                                
        conn = psycopg2.connect(_test_db_url())
        cur = conn.cursor()
        cur.execute(
            """UPDATE vault_analysis_jobs
               SET status='processing',
                   locked_at = NOW() - INTERVAL '1 hour',
                   locked_by = 'crashed-worker',
                   started_at = NOW() - INTERVAL '1 hour'
               WHERE job_id = %s""",
            (job_id,),
        )
        conn.commit()
        conn.close()

        report = reconcile_vault(self.vault_id, stale_processing_seconds=60)
        self.assertGreaterEqual(report.stuck_processing_requeued, 1)
        conn = psycopg2.connect(_test_db_url())
        cur = conn.cursor()
        cur.execute(
            "SELECT status, locked_at FROM vault_analysis_jobs WHERE job_id=%s",
            (job_id,),
        )
        status_after, locked_after = cur.fetchone()
        conn.close()
        self.assertEqual(status_after, "pending")
        self.assertIsNone(locked_after)


class PartialCoverageHonestyTests(_E2EBase):
    def test_unanalyzed_file_returns_still_reading_message(self) -> None:


        from vault_read_file import handle_read_file_text_intent
        file_id = "e2e-partial-" + uuid.uuid4().hex[:8]
        file_name = "unanalyzed.txt"
        self._insert_uploaded_file(
            file_id=file_id, file_name=file_name,
            content_type="text/plain",
            plaintext_bytes=b"x",
            analysis_status="not_started",
        )
                                                             
                      
        reply = handle_read_file_text_intent(
            vault_id=self.vault_id, query_name=file_name, key=self.key,
        )
        self.assertIn("still reading", reply.lower())
        self.assertIn("not_started", reply)

    def test_no_match_returns_dont_see_message(self) -> None:
        from vault_read_file import handle_read_file_text_intent
        reply = handle_read_file_text_intent(
            vault_id=self.vault_id,
            query_name="this-file-doesnt-exist.txt",
            key=self.key,
        )
        self.assertIn("don't see", reply.lower())


class DaemonStatusSafetyTests(_E2EBase):
    def test_daemon_status_contains_no_credential_values(self) -> None:


        from vault_analysis_daemon import get_status, reset_for_tests as reset_daemon
        reset_daemon()
        file_id = "e2e-safety-" + uuid.uuid4().hex[:8]
        secret_payload = (
            self.SENTINEL + "\nALSO_CONTAINS_password=hunter2_test_sentinel"
        )
        self._insert_uploaded_file(
            file_id=file_id, file_name="safety-probe.txt",
            content_type="text/plain",
            plaintext_bytes=secret_payload.encode("utf-8"),
        )
        self._insert_job(file_id=file_id, stage="text_extraction")
        self._activate_key_for_vault()
        self._run_daemon_iteration()

        snap = get_status().to_dict()
        flat = repr(snap)
                                                                  
                                       
        self.assertNotIn("hunter2", flat)
        self.assertNotIn(self.vault_id, flat)
        self.assertNotIn("PHASE1-SENTINEL", flat)


if __name__ == "__main__":
    unittest.main()
