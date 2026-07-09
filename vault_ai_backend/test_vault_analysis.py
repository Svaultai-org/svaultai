

from __future__ import annotations

import inspect
import json
import os
import unittest

import vault_analysis as va


def _migration_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0005_vault_analysis_foundation.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _all_migration_sources() -> list[str]:


    versions_dir = os.path.join(
        os.path.dirname(__file__), "migrations", "versions",
    )
    out: list[str] = []
    for fname in sorted(os.listdir(versions_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        with open(
            os.path.join(versions_dir, fname), "r", encoding="utf-8",
        ) as f:
            out.append(f.read())
    return out


class MigrationSchemaGuardTests(unittest.TestCase):


    def setUp(self):
        self.src = _migration_source()

    def test_uploaded_files_gains_analysis_columns(self):
        for col in (
            "analysis_status",
            "analysis_pipeline_state",
            "analysis_last_error",
            "analysis_started_at",
            "analysis_completed_at",
            "analysis_updated_at",
        ):
            self.assertIn(
                f"ADD COLUMN IF NOT EXISTS {col}",
                self.src,
                f"migration must add uploaded_files.{col}",
            )

    def test_analysis_status_default_is_not_started(self):
                                                                   
                                                         
        self.assertIn("DEFAULT 'not_started'", self.src)

    def test_status_check_constraint_lists_every_python_constant(self):
                                                               
                                                                   
        for status in va.ANALYSIS_STATUSES:
            self.assertTrue(
                f'"{status}"' in self.src or f"'{status}'" in self.src,
                f"migration must declare status {status!r}",
            )

    def test_jobs_table_columns_present(self):
        for col in (
            "job_id", "vault_id", "file_id", "stage", "status",
            "attempts", "max_attempts", "last_error",
            "locked_at", "locked_by",
            "scheduled_at", "started_at", "completed_at",
            "created_at", "updated_at", "metadata_jsonb",
        ):
            self.assertIn(
                col, self.src,
                f"vault_analysis_jobs must declare {col}",
            )

    def test_stages_match_python_constants(self):
                                                                 
                                                               
        sources_all = _all_migration_sources()
        for stage in va.STAGES:
            self.assertTrue(
                any(
                    f'"{stage}"' in src or f"'{stage}'" in src
                    for src in sources_all
                ),
                f"some migration must declare stage {stage!r}",
            )

    def test_job_statuses_match_python_constants(self):
        for status in va.JOB_STATUSES:
            self.assertTrue(
                f'"{status}"' in self.src or f"'{status}'" in self.src,
                f"migration must declare job status {status!r}",
            )

    def test_required_indexes_present(self):
                                                              
        self.assertIn(
            "uploaded_files_analysis_status_idx", self.src,
        )
                                                           
        self.assertIn("vault_analysis_jobs_ready_idx", self.src)
                                                                 
        self.assertIn("vault_analysis_jobs_file_stage_idx", self.src)

    def test_migration_revises_0004(self):
        self.assertIn(
            'down_revision: Union[str, None] = "0004_uploaded_files_content_hash"',
            self.src,
        )

    def test_migration_is_reversible(self):
                                                                    
                                                                 
        for needle in (
            "DROP TABLE IF EXISTS vault_analysis_jobs",
            "DROP COLUMN IF EXISTS analysis_status",
            "DROP COLUMN IF EXISTS analysis_pipeline_state",
            "DROP COLUMN IF EXISTS analysis_last_error",
            "DROP COLUMN IF EXISTS analysis_started_at",
            "DROP COLUMN IF EXISTS analysis_completed_at",
            "DROP COLUMN IF EXISTS analysis_updated_at",
        ):
            self.assertIn(needle, self.src)


class NormalizeAnalysisStatusTests(unittest.TestCase):
    def test_known_status_passthrough(self):
        for status in va.ANALYSIS_STATUSES:
            self.assertEqual(va.normalize_analysis_status(status), status)

    def test_none_defaults_to_not_started(self):
        self.assertEqual(
            va.normalize_analysis_status(None),
            va.ANALYSIS_STATUS_NOT_STARTED,
        )

    def test_unknown_string_falls_back_to_not_started(self):
        self.assertEqual(
            va.normalize_analysis_status("garbage_status_xyz"),
            va.ANALYSIS_STATUS_NOT_STARTED,
        )

    def test_whitespace_is_stripped(self):
        self.assertEqual(
            va.normalize_analysis_status("  analyzed  "),
            va.ANALYSIS_STATUS_ANALYZED,
        )


class IsTerminalAnalysisStatusTests(unittest.TestCase):
    def test_analyzed_is_terminal(self):
        self.assertTrue(
            va.is_terminal_analysis_status(va.ANALYSIS_STATUS_ANALYZED),
            "analyzed status MUST be terminal "
            "(spec: 'analyzed status is terminal')",
        )

    def test_failed_is_terminal(self):
        self.assertTrue(va.is_terminal_analysis_status(va.ANALYSIS_STATUS_FAILED))

    def test_skipped_is_terminal(self):
        self.assertTrue(va.is_terminal_analysis_status(va.ANALYSIS_STATUS_SKIPPED))

    def test_unsupported_is_terminal(self):
        self.assertTrue(va.is_terminal_analysis_status(va.ANALYSIS_STATUS_UNSUPPORTED))

    def test_pending_is_NOT_terminal(self):
        self.assertFalse(va.is_terminal_analysis_status(va.ANALYSIS_STATUS_PENDING))

    def test_processing_is_NOT_terminal(self):
        self.assertFalse(
            va.is_terminal_analysis_status(va.ANALYSIS_STATUS_PROCESSING)
        )

    def test_not_started_is_NOT_terminal(self):
        self.assertFalse(
            va.is_terminal_analysis_status(va.ANALYSIS_STATUS_NOT_STARTED)
        )

    def test_needs_reanalysis_is_NOT_terminal(self):
        self.assertFalse(
            va.is_terminal_analysis_status(va.ANALYSIS_STATUS_NEEDS_REANALYSIS)
        )


class NormalizeStageTests(unittest.TestCase):
    def test_known_stage_passthrough(self):
        for stage in va.STAGES:
            self.assertEqual(va.normalize_stage(stage), stage)

    def test_unknown_stage_yields_none(self):
                                                                 
                    
        self.assertIsNone(va.normalize_stage("ocre"))
        self.assertIsNone(va.normalize_stage(""))
        self.assertIsNone(va.normalize_stage(None))


class ShouldEnqueueAnalysisForFileTests(unittest.TestCase):
    def test_pdf_is_supported(self):
        self.assertTrue(va.should_enqueue_analysis_for_file(
            file_name="statement.pdf",
        ))

    def test_jpg_image_is_supported(self):
        self.assertTrue(va.should_enqueue_analysis_for_file(
            file_name="passport.jpg",
        ))

    def test_audio_is_supported(self):
        self.assertTrue(va.should_enqueue_analysis_for_file(
            file_name="note.m4a",
        ))

    def test_video_is_supported(self):
        self.assertTrue(va.should_enqueue_analysis_for_file(
            file_name="trip.mp4",
        ))

    def test_zip_is_unsupported(self):
                                                                  
                                                             
        self.assertFalse(va.should_enqueue_analysis_for_file(
            file_name="backup.zip",
        ))

    def test_executable_is_unsupported(self):
                                                                
                                                        
        self.assertFalse(va.should_enqueue_analysis_for_file(
            file_name="installer.dmg",
        ))

    def test_mime_image_is_supported_even_without_extension(self):
        self.assertTrue(va.should_enqueue_analysis_for_file(
            file_name="UNKNOWN",
            content_type="image/png",
        ))

    def test_octet_stream_text_extensions_are_supported(self):
        for name in ("login.js", "Yahoopass.html", "credentials.env"):
            with self.subTest(name=name):
                self.assertTrue(va.should_enqueue_analysis_for_file(
                    file_name=name,
                    content_type="application/octet-stream",
                ))

    def test_empty_inputs_are_unsupported(self):
        self.assertFalse(va.should_enqueue_analysis_for_file(
            file_name=None, content_type=None,
        ))


class DefaultStagesForFileTests(unittest.TestCase):
    def test_supported_file_yields_at_least_one_stage(self):
        stages = va.default_stages_for_file(file_name="statement.pdf")
        self.assertGreater(len(stages), 0)
        for stage in stages:
            self.assertIn(stage, va.STAGES)

    def test_octet_stream_html_and_js_route_to_text_extraction(self):
        for name in ("login.js", "Loginatt.html"):
            with self.subTest(name=name):
                self.assertEqual(
                    va.default_stages_for_file(
                        file_name=name,
                        content_type="application/octet-stream",
                    ),
                    [va.STAGE_TEXT_EXTRACTION],
                )

    def test_unsupported_file_yields_empty_list(self):
                                                               
                                                               
        self.assertEqual(va.default_stages_for_file(file_name="x.dmg"), [])
        self.assertEqual(va.default_stages_for_file(file_name="x.iso"), [])

    def test_slice1_only_enqueues_text_extraction_today(self):
                                                                 
                                                                  
        self.assertEqual(
            va.default_stages_for_file(file_name="statement.pdf"),
            [va.STAGE_TEXT_EXTRACTION],
        )


class TruncateErrorTests(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(va._truncate_error(None))

    def test_long_error_is_capped(self):
        msg = va._truncate_error("x" * 5000)
        self.assertLessEqual(len(msg), 500)

    def test_password_value_is_scrubbed(self):
                                                                    
                                                      
        scrubbed = va._truncate_error(
            "ValueError processing line 'password: hunter2'"
        )
        self.assertNotIn("hunter2", scrubbed)
        self.assertIn("<redacted>", scrubbed)

    def test_token_value_is_scrubbed(self):
        scrubbed = va._truncate_error("token: bearer_abcdef")
        self.assertNotIn("bearer_abcdef", scrubbed)


class CoverageHelpersTests(unittest.TestCase):
    def test_summary_buckets_correctly(self):
        out = va.summarise_coverage_for_chat({
            "total": 10,
            "analyzed": 4,
            "pending": 2,
            "processing": 1,
            "failed": 1,
            "unsupported": 1,
            "not_started": 1,
            "needs_reanalysis": 0,
            "skipped": 0,
        })
        self.assertEqual(out["total"], 10)
        self.assertEqual(out["content_scanned"], 4)
                                                 
        self.assertEqual(out["still_analyzing"], 3)
                                            
        self.assertEqual(out["not_scanned"], 3)

    def test_chat_note_explains_pending_files(self):
        note = va.chat_coverage_note({
            "total": 5, "analyzed": 2, "pending": 3,
            "processing": 0, "failed": 0, "unsupported": 0,
            "not_started": 0, "needs_reanalysis": 0, "skipped": 0,
        })
                             
        self.assertIsNotNone(note)
        self.assertIn("still being analyzed", note)
        self.assertIn("3 files", note)
        self.assertIn("I found these results so far", note)

    def test_chat_note_explains_unsupported_files(self):
        note = va.chat_coverage_note({
            "total": 5, "analyzed": 2, "pending": 0,
            "processing": 0, "failed": 0, "unsupported": 3,
            "not_started": 0, "needs_reanalysis": 0, "skipped": 0,
        })
        self.assertIsNotNone(note)
        self.assertIn("could not be content-scanned", note)

    def test_no_note_when_everything_analyzed(self):
        note = va.chat_coverage_note({
            "total": 5, "analyzed": 5, "pending": 0,
            "processing": 0, "failed": 0, "unsupported": 0,
            "not_started": 0, "needs_reanalysis": 0, "skipped": 0,
        })
        self.assertIsNone(note)


class UploadKickoffWiringTests(unittest.TestCase):


    def test_main_exposes_kickoff_helper(self):
        import main
        self.assertTrue(
            hasattr(main, "kickoff_analysis_for_uploaded_file"),
            "main.py must expose the kickoff helper so chunked + "
            "single-shot uploads share one entry point",
        )

    def test_kickoff_helper_never_raises(self):
                                                               
                                                                  
        import main
        src = inspect.getsource(main.kickoff_analysis_for_uploaded_file)
        self.assertIn("try:", src)
        self.assertIn("except Exception", src)

    def test_single_shot_upload_calls_kickoff(self):
                                                                   
                                                                      
        import main
        src = inspect.getsource(main.save_uploaded_file)
        self.assertIn("kickoff_analysis_for_uploaded_file(", src)

    def test_chunked_finalize_calls_kickoff(self):
        from routes import chunked_upload_routes
        src = inspect.getsource(chunked_upload_routes)
        self.assertIn("kickoff_analysis_for_uploaded_file(", src)

    def test_kickoff_uses_unsupported_status_for_unsupported_types(self):
                                                                 
                                                            
        import main
        src = inspect.getsource(main.kickoff_analysis_for_uploaded_file)
        self.assertIn("mark_file_analysis_unsupported", src)

    def test_kickoff_marks_pending_for_supported_types(self):
        import main
        src = inspect.getsource(main.kickoff_analysis_for_uploaded_file)
        self.assertIn("mark_file_analysis_pending", src)


class InventoryEnvelopeCoverageTests(unittest.TestCase):
    def test_envelope_ships_analysis_coverage_when_provided(self):
        import main
        env = json.loads(main._build_vault_inventory_envelope(
            summary={
                "total_files": 5, "total_bytes": 0,
                "folder_count": 1, "top_folders": [],
                "type_counts": {}, "recent_files": [],
            },
            message="x",
            analysis_coverage={
                "total": 5,
                "content_scanned": 2,
                "still_analyzing": 3,
                "not_scanned": 0,
            },
        ))
        self.assertIn("analysis_coverage", env)
        self.assertEqual(env["analysis_coverage"]["still_analyzing"], 3)

    def test_envelope_omits_coverage_when_not_provided(self):
                                                             
        import main
        env = json.loads(main._build_vault_inventory_envelope(
            summary={
                "total_files": 0, "total_bytes": 0,
                "folder_count": 0, "top_folders": [],
                "type_counts": {}, "recent_files": [],
            },
            message="x",
        ))
        self.assertNotIn("analysis_coverage", env)

    def test_chat_handler_threads_coverage_into_envelope(self):
                                                                     
                                                                  
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn("analysis_coverage_for_vault", src)
        self.assertIn("summarise_coverage_for_chat", src)
        self.assertIn("chat_coverage_note", src)


class SafetyHardFloorsTests(unittest.TestCase):
    def test_analysis_layer_does_not_execute_files(self):


        src = inspect.getsource(va)
        for needle in (
            "subprocess", "os.system(", "eval(", "exec(",
            "pty.spawn", "shell=True",
        ):
            self.assertNotIn(
                needle, src,
                f"vault_analysis.py must NOT contain {needle!r} — "
                "uploaded files are NEVER executed",
            )

    def test_kickoff_does_not_create_login_items(self):
                                                              
                                                         
        import main
        src = inspect.getsource(main.kickoff_analysis_for_uploaded_file)
        self.assertNotIn("vault_items", src)
        self.assertNotIn("INSERT INTO vault_items", src)
        self.assertNotIn("save_login", src)


_TEST_DB_URL = os.getenv("VAULTAI_TEST_DATABASE_URL", "").strip()
requires_db = unittest.skipUnless(
    bool(_TEST_DB_URL),
    "VAULTAI_TEST_DATABASE_URL is not set; skipping DB-bound tests",
)


@requires_db
class JobLifecycleIntegrationTests(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
