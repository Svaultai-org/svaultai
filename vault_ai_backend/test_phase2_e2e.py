

from __future__ import annotations

import asyncio
import os
import time
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
    "Phase 2 E2E requires VAULTAI_TEST_DATABASE_URL "
    "(separate from DATABASE_URL)")
class _Phase2E2EBase(unittest.TestCase):


    def setUp(self):
                                                                    
                                                                    
        if not _have_test_database_url():
            load_dotenv(".env", override=False)
        if not _have_test_database_url():
            self.skipTest(
                f"{_TEST_DB_ENV_VAR} not in environ after .env reload"
            )
        from vault_chat_memory import CHAT_MEMORY
        CHAT_MEMORY._data.clear()
        from vault_followup_classifier import reset_anchor_cache_for_tests
        reset_anchor_cache_for_tests()
        self.vault_id = str(uuid.uuid4())
        self._seed_vault()

    def _seed_vault(self):
                                                                      
                                                                 
        import psycopg2
        try:
            conn = psycopg2.connect(_test_db_url())
        except psycopg2.OperationalError as exc:
                                                                   
                                                                     
            self.skipTest(f"DB unreachable for E2E: {exc.__class__.__name__}")
            return
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO vaults (vault_id, vault_name, pin_salt,
                                       pin_verifier)
                   VALUES (%s, %s, '00000000', '00000000')""",
                (self.vault_id, "phase2-e2e-" + self.vault_id[:8]),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
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

    def _insert_credential_file(self, file_name: str, *,
                                analysis_status: str = "analyzed") -> str:


        import psycopg2
        file_id = "p2-" + uuid.uuid4().hex[:10]
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
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, NULL,
                    FALSE, FALSE, FALSE,
                    'inline', 'complete',
                    NOW(), 1, %s,
                    '{}'::jsonb, %s,
                    FALSE, 0, 0
                )
                """,
                (
                    file_id, self.vault_id, file_name, "application/pdf",
                    1024, "PLACEHOLDER_BLOB",
                    analysis_status,
                    "available" if analysis_status == "analyzed" else "not_available",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return file_id


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


from test_vault_followup_classifier import fake_embed


CANNED_PHRASES = (
    "Bank Account", "ID Document", "Payment Card",
    "Saved Logins", "Saved Login",
    "Loyalty Card", "Insurance Card",
)


class PartialCoverageFollowupTests(_Phase2E2EBase):
    def test_partial_coverage_followup_returns_coverage_grounded_answer(self):
        from vault_result_context import (
            make_credential_search_result,
            set_last_assistant_result,
        )
        from vault_chat_planner_pipeline import run_pipeline

                                                                
        f1 = self._insert_credential_file("passwords.txt",
                                          analysis_status="analyzed")
        f2 = self._insert_credential_file("env.txt",
                                          analysis_status="pending")
        f3 = self._insert_credential_file("creds.csv",
                                          analysis_status="not_started")

                                                                     
        coverage = {
            "total": 3, "analyzed": 1, "pending": 1, "not_started": 1,
            "processing": 0, "failed": 0, "unsupported": 0, "skipped": 0,
        }
        from vault_deep_answer import build_coverage_report
        result = make_credential_search_result(
            query="find files with credentials",
            file_ids_returned=[f1],
            file_ids_excluded=[],
            total_matches_known=1,
            coverage=build_coverage_report(coverage),
            is_partial=True,
        )
        set_last_assistant_result(self.vault_id, result)

                                                                      
        decision = _run(run_pipeline(
            vault_id=self.vault_id,
            message="is that all of them?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: build_coverage_report(coverage),
            daemon_active_probe=lambda: False,
        ))
        self.assertTrue(decision.handled)
        body = decision.reply_body
                                                        
        self.assertIn("1", body)           
        self.assertIn("3", body)         
                                                       
        self.assertTrue(
            "can't confirm" in body.lower() or "still" in body.lower(),
            f"reply body must be coverage-honest, got: {body!r}",
        )
                                  
        for phrase in CANNED_PHRASES:
            self.assertNotIn(phrase, body)


class CompleteCoverageFollowupTests(_Phase2E2EBase):
    def test_complete_coverage_followup_returns_yes_answer(self):
        from vault_result_context import (
            make_credential_search_result,
            set_last_assistant_result,
        )
        from vault_chat_planner_pipeline import run_pipeline
        from vault_deep_answer import build_coverage_report

                                                   
        f1 = self._insert_credential_file("a.pdf", analysis_status="analyzed")
        f2 = self._insert_credential_file("b.pdf", analysis_status="analyzed")
        f3 = self._insert_credential_file("c.pdf", analysis_status="analyzed")
        coverage_raw = {
            "total": 3, "analyzed": 3, "pending": 0, "not_started": 0,
            "processing": 0, "failed": 0, "unsupported": 0, "skipped": 0,
        }
        coverage = build_coverage_report(coverage_raw)
        result = make_credential_search_result(
            query="find files with credentials",
            file_ids_returned=[f1, f2],
            file_ids_excluded=[f3],
            total_matches_known=2,
            coverage=coverage,
            is_partial=False,
        )
        set_last_assistant_result(self.vault_id, result)

        decision = _run(run_pipeline(
            vault_id=self.vault_id,
            message="is that all of them?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: coverage,
            daemon_active_probe=lambda: False,
        ))
        self.assertTrue(decision.handled)
        body = decision.reply_body
                                                                     
        self.assertIn("3", body)          
        self.assertIn("2", body)                
                                               
        for phrase in CANNED_PHRASES:
            self.assertNotIn(phrase, body)
                                                                  
                                                                
        self.assertNotIn("still", body.lower())
                                                                
                                                      
        from vault_result_context import (
            make_credential_search_result,
            set_last_assistant_result,
        )
        from vault_chat_planner_pipeline import run_pipeline as _run_again
                                                 
        from vault_chat_memory import CHAT_MEMORY
        CHAT_MEMORY._data.clear()
        result2 = make_credential_search_result(
            query="find credentials",
            file_ids_returned=[f1],
            file_ids_excluded=[f2, f3],
            total_matches_known=1,                         
            coverage=coverage,
            is_partial=False,
        )
        set_last_assistant_result(self.vault_id, result2)
        decision2 = _run(_run_again(
            vault_id=self.vault_id,
            message="is that all of them?",
            embed_fn=fake_embed,
            coverage_loader=lambda v: coverage,
            daemon_active_probe=lambda: False,
        ))
        self.assertNotEqual(
            decision.reply_body, decision2.reply_body,
            "different match_count facts must produce different bodies — "
            "no canned string slot-fill",
        )


class CoverageFollowupSemanticEquivalenceE2ETests(_Phase2E2EBase):


    PHRASINGS = [
        "is that all?",
        "is this everything?",
        "did you check the whole vault?",
        "have you scanned every file?",
        "are these the only matches?",
    ]

    def test_every_phrasing_grounded_in_coverage_no_canned_category(self):
        from vault_result_context import (
            make_credential_search_result,
            set_last_assistant_result,
        )
        from vault_chat_planner_pipeline import run_pipeline
        from vault_deep_answer import build_coverage_report

        f1 = self._insert_credential_file("only-one.pdf",
                                          analysis_status="analyzed")
        coverage = build_coverage_report({
            "total": 1, "analyzed": 1, "scan_complete": True,
        })
        result = make_credential_search_result(
            query="find credentials",
            file_ids_returned=[f1], file_ids_excluded=[],
            total_matches_known=1, coverage=coverage, is_partial=False,
        )
        set_last_assistant_result(self.vault_id, result)

        for phrasing in self.PHRASINGS:
            with self.subTest(phrasing=phrasing):
                decision = _run(run_pipeline(
                    vault_id=self.vault_id,
                    message=phrasing,
                    embed_fn=fake_embed,
                    coverage_loader=lambda v: coverage,
                    daemon_active_probe=lambda: False,
                ))
                self.assertTrue(
                    decision.handled,
                    f"pipeline did not handle phrasing {phrasing!r}",
                )
                for phrase in CANNED_PHRASES:
                    self.assertNotIn(
                        phrase, decision.reply_body,
                        f"phrasing {phrasing!r} leaked canned category "
                        f"{phrase!r}: {decision.reply_body!r}",
                    )


if __name__ == "__main__":
    unittest.main()
