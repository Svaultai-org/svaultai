

from __future__ import annotations

import ast
import inspect
import unittest
from typing import Optional
from unittest.mock import patch

import vault_analysis as va
import vault_audio_transcription as at
import vault_document_purpose as vp
import vault_understanding as vu
import vault_understanding_search as vus


class SupportsAudioTranscriptionTests(unittest.TestCase):
    def test_mp3_supported(self):
        self.assertTrue(
            at.supports_audio_transcription(file_name="note.mp3")
        )

    def test_m4a_supported(self):
        self.assertTrue(
            at.supports_audio_transcription(file_name="memo.m4a")
        )

    def test_wav_supported(self):
        self.assertTrue(
            at.supports_audio_transcription(file_name="REC001.wav")
        )

    def test_aac_supported(self):
        self.assertTrue(
            at.supports_audio_transcription(file_name="clip.aac")
        )

    def test_ogg_supported(self):
        self.assertTrue(
            at.supports_audio_transcription(file_name="voice.ogg")
        )

    def test_webm_supported_as_audio_container(self):
        self.assertTrue(
            at.supports_audio_transcription(
                file_name="rec.webm",
                content_type="audio/webm",
            )
        )

    def test_mime_audio_mpeg_supported(self):
        self.assertTrue(
            at.supports_audio_transcription(
                file_name="unknown",
                content_type="audio/mpeg",
            )
        )

    def test_pdf_not_supported(self):
        self.assertFalse(
            at.supports_audio_transcription(file_name="doc.pdf")
        )

    def test_image_not_supported(self):
        self.assertFalse(
            at.supports_audio_transcription(file_name="photo.png")
        )

    def test_video_extension_not_supported_here(self):
                                                                
                                                            
        self.assertFalse(
            at.supports_audio_transcription(file_name="movie.mp4")
        )
        self.assertFalse(
            at.supports_audio_transcription(file_name="movie.mov")
        )


class TranscribeAudioTests(unittest.TestCase):
    def tearDown(self):
        at.reset_audio_transcription_engine()

    def test_engine_injection_works(self):
        at.set_audio_transcription_engine(
            lambda audio_bytes, mime, file_name: "hello world"
        )
        text, truncated = at.transcribe_audio(
            file_name="note.mp3", file_bytes=b"audio-bytes",
        )
        self.assertEqual(text, "hello world")
        self.assertFalse(truncated)

    def test_unsupported_extension_raises(self):
        at.set_audio_transcription_engine(
            lambda *a, **k: "should not be called"
        )
        with self.assertRaises(at.AudioTranscriptionError):
            at.transcribe_audio(
                file_name="doc.pdf", file_bytes=b"x",
            )

    def test_empty_bytes_raises(self):
        at.set_audio_transcription_engine(
            lambda *a, **k: "should not be called"
        )
        with self.assertRaises(at.AudioTranscriptionError):
            at.transcribe_audio(
                file_name="note.mp3", file_bytes=b"",
            )

    def test_oversize_bytes_raises_fail_no_retry(self):
        at.set_audio_transcription_engine(
            lambda *a, **k: "should not be called"
        )
        too_big = b"x" * (at.MAX_AUDIO_BYTES + 1)
        with self.assertRaises(at.AudioTranscriptionError):
            at.transcribe_audio(
                file_name="note.mp3", file_bytes=too_big,
            )

    def test_engine_error_wraps_in_audio_error(self):
        def _boom(audio_bytes, mime, file_name):
            raise RuntimeError("provider down")
        at.set_audio_transcription_engine(_boom)
        with self.assertRaises(at.AudioTranscriptionError):
            at.transcribe_audio(
                file_name="note.mp3", file_bytes=b"audio",
            )

    def test_truncate_long_output(self):
        at.set_audio_transcription_engine(
            lambda *a, **k: "z" * (at.MAX_TRANSCRIPT_CHARS + 10)
        )
        text, truncated = at.transcribe_audio(
            file_name="note.mp3", file_bytes=b"audio",
        )
        self.assertTrue(truncated)
        self.assertEqual(len(text), at.MAX_TRANSCRIPT_CHARS)

    def test_normalisation_strips_control_chars(self):
        at.set_audio_transcription_engine(
            lambda *a, **k: "hello\x00 world\f\nnew line"
        )
        text, _ = at.transcribe_audio(
            file_name="note.mp3", file_bytes=b"audio",
        )
        self.assertNotIn("\x00", text)
        self.assertNotIn("\f", text)

    def test_no_engine_configured_raises(self):
        at.reset_audio_transcription_engine()
        if at.AUDIO_AVAILABLE:
                                                                
                                                               
            self.skipTest("openai SDK present at import time")
        with self.assertRaises(at.AudioTranscriptionError):
            at.transcribe_audio(
                file_name="note.mp3", file_bytes=b"audio",
            )


class DefaultStagesRoutingTests(unittest.TestCase):
    def test_mp3_routes_to_audio_transcription(self):
        stages = va.default_stages_for_file(file_name="note.mp3")
        self.assertEqual(stages, [va.STAGE_AUDIO_TRANSCRIPTION])

    def test_m4a_routes_to_audio_transcription(self):
        stages = va.default_stages_for_file(file_name="memo.m4a")
        self.assertEqual(stages, [va.STAGE_AUDIO_TRANSCRIPTION])

    def test_wav_routes_to_audio_transcription(self):
        stages = va.default_stages_for_file(file_name="clip.wav")
        self.assertEqual(stages, [va.STAGE_AUDIO_TRANSCRIPTION])

    def test_audio_mime_routes_to_audio_transcription(self):
        stages = va.default_stages_for_file(
            file_name="unknown",
            content_type="audio/mpeg",
        )
        self.assertEqual(stages, [va.STAGE_AUDIO_TRANSCRIPTION])

    def test_pdf_still_routes_to_text_extraction(self):
        stages = va.default_stages_for_file(file_name="doc.pdf")
        self.assertEqual(stages, [va.STAGE_TEXT_EXTRACTION])

    def test_png_still_routes_to_ocr(self):
        stages = va.default_stages_for_file(file_name="photo.png")
        self.assertEqual(stages, [va.STAGE_OCR])

    def test_zip_routes_to_archive_indexing(self):
                                                                
                                                       
        stages = va.default_stages_for_file(file_name="bundle.zip")
        self.assertEqual(stages, [va.STAGE_ARCHIVE_INDEXING])

    def test_mp4_does_not_route_to_audio(self):
                                                                
                                                               
        stages = va.default_stages_for_file(file_name="movie.mp4")
        self.assertNotIn(va.STAGE_AUDIO_TRANSCRIPTION, stages)


class WorkerSourceGuardTests(unittest.TestCase):
    def test_worker_exists_and_drains_via_claim(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw.drain_audio_transcription)
        self.assertIn("claim_next_analysis_job", src)
        mod_src = inspect.getsource(vaw)
        self.assertIn("STAGE_AUDIO_TRANSCRIPTION", mod_src)
        self.assertIn("_HANDLED_STAGE", src)

    def test_worker_calls_transcribe(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw._process_one_audio_job)
        self.assertIn("transcribe_audio", src)

    def test_worker_encrypts_before_persist(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw._process_one_audio_job)
        encrypt_idx = src.find("encrypt_message")
        persist_idx = src.find("_persist_extracted_text")
        self.assertGreater(encrypt_idx, -1)
        self.assertGreater(persist_idx, -1)
        self.assertLess(
            encrypt_idx, persist_idx,
            "transcript MUST be encrypted before being persisted "
            "to extracted_text — the CHECK constraint refuses "
            "plaintext, but defence-in-depth requires the order "
            "in source",
        )

    def test_worker_persists_with_source_transcript(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw._process_one_audio_job)
                                                               
                                                
        self.assertIn('source="transcript"', src)

    def test_worker_drops_plaintext_bytes_after_use(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw._process_one_audio_job)
        self.assertIn("plaintext_bytes = None", src)
                                                            
        self.assertIn('text = ""', src)

    def test_worker_enqueues_understanding_after_success(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw._process_one_audio_job)
        analyzed_idx = src.find("mark_file_analysis_analyzed")
        enqueue_idx = src.find(
            "enqueue_understanding_after_text_extraction"
        )
        self.assertGreater(analyzed_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(
            analyzed_idx, enqueue_idx,
            "audio success must come BEFORE the understanding "
            "enqueue",
        )

    def test_worker_calls_stale_helpers_after_success(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw._process_one_audio_job)
                                                             
                                                             
        self.assertIn(
            "mark_stale_understandings_for_changed_text", src,
        )
        self.assertIn(
            "mark_stale_embeddings_for_changed_text", src,
        )


class SafetyFloorTests(unittest.TestCase):
    def test_audio_module_never_executes_user_content(self):
        src = inspect.getsource(at)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(
                forbidden, src,
                f"audio module MUST NOT use {forbidden} on user "
                "content — uploaded audio bytes are decoded as "
                "audio, never as code",
            )

    def test_worker_never_executes_user_content(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_worker_does_not_touch_vault_items_table(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw)
                                                               
                                                              
        try:
            tree = ast.parse(src)
            doc = ast.get_docstring(tree) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertNotIn("INSERT INTO vault_items", code_only)
        self.assertNotIn("vault_items", code_only)

    def test_worker_logs_do_not_include_transcript(self):
        import vault_audio_worker as vaw
        src = inspect.getsource(vaw)
                                                   
        for forbidden in (
            'logger.info("%s", text',
            'logger.info("%s", plaintext',
            'logger.info("%s", transcript',
            'logger.exception("%s", text',
            'logger.exception("%s", transcript',
        ):
            self.assertNotIn(forbidden, src)

    def test_audio_module_logs_do_not_include_audio_bytes(self):
        src = inspect.getsource(at)
        for forbidden in (
            'logger.info("%s", file_bytes',
            'logger.info("%s", audio_bytes',
            'logger.exception("%s", file_bytes',
        ):
            self.assertNotIn(forbidden, src)


class ChatHandlerWiringTests(unittest.TestCase):
    def test_chat_handler_runs_audio_drain_after_ocr(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        ocr_idx = src.find("drain_ocr")
        audio_idx = src.find("drain_audio_transcription")
        self.assertGreater(ocr_idx, -1)
        self.assertGreater(audio_idx, -1)
        self.assertLess(
            ocr_idx, audio_idx,
            "audio drain must run AFTER OCR — both feed the "
            "extracted_text lifecycle but transcription is "
            "slower so we drain it after the cheaper stage",
        )

    def test_chat_handler_runs_audio_drain_before_understanding(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        audio_idx = src.find("drain_audio_transcription")
        understanding_idx = src.find("drain_file_understanding")
        self.assertGreater(audio_idx, -1)
        self.assertGreater(understanding_idx, -1)
        self.assertLess(
            audio_idx, understanding_idx,
            "freshly transcribed audio must feed the understanding "
            "drain in the SAME chat turn",
        )


class TranscriptSearchIntegrationTests(unittest.TestCase):


    def _make_row(
        self,
        *,
        file_id: str,
        file_name: str,
        understanding_status: str = "ready",
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
            "content_type":         "audio/mpeg",
            "asset_type":           "audio",
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
            "embedding_status":     None,
            "embedding_model":      None,
            "embedding_dim":        0,
            "embedding_vector_text": None,
            "embedding_vector_decoded": None,
        }

    def test_voice_note_about_wells_fargo_findable_by_entity(self):


        rows = [self._make_row(
            file_id="audio-1",
            file_name="memo_2024_03_15.m4a",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "find voice notes about Wells Fargo",
            )
        self.assertEqual(len(report["results"]), 1)
        m = report["results"][0]
        self.assertEqual(m["match_type"], "entity")
        self.assertIn("Wells Fargo", m["match_reason"])

    def test_voice_note_about_work_findable_via_topic(self):


        rows = [self._make_row(
            file_id="audio-2",
            file_name="rec_april_5.mp3",
            categories=["finance"],
            topics=["finance"],
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "show voice notes about finance",
            )
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["match_type"], "category")

    def test_filename_alone_does_not_outrank_transcript(self):


        rows = [
            self._make_row(
                file_id="audio-filename",
                file_name="memo_rent.m4a",
                understanding_status="ready",
                                      
                topics=[], entities={"names": []},
            ),
            self._make_row(
                file_id="audio-entity",
                file_name="some_rec.m4a",
                                                  
                entities={"names": ["Landlord"], "email_domains": []},
            ),
        ]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Landlord",
            )
                                   
        first = report["results"][0]
        self.assertEqual(first["file_id"], "audio-entity")
        self.assertEqual(first["match_type"], "entity")


class TranscriptCredentialSafetyTests(unittest.TestCase):
    def test_transcript_with_password_phrase_does_not_leak(self):
        transcript = "\n".join([
            "Reminder for tomorrow.",
            "Pay the electricity bill and call the doctor.",
            "Note to self: my password is hunter2.",
            "Also remember to renew the parking permit.",
        ])
        record = vu.build_understanding(
            transcript, file_name="memo_2024_04.m4a",
        )
                                                                
                             
        for sentinel in ("hunter2",):
            self.assertNotIn(sentinel, record["summary"] or "")
            self.assertNotIn(sentinel, record["safe_preview"] or "")
            terms = " ".join(record["searchable_terms"] or [])
            self.assertNotIn(sentinel, terms)

    def test_credential_dump_transcript_classified_correctly(self):
                                                            
                                                          
        transcript = "\n".join([
            "AOL", "alice@example.com", "Patrick62109",
            "Apple", "bob@example.com", "MKSherm81765",
            "American Express", "carol@example.com", "e&t082826",
        ])
        record = vu.build_understanding(
            transcript, file_name="voice_export.mp3",
        )
        self.assertEqual(
            record["document_purpose"],
            vp.PURPOSE_SAVED_LOGIN_LIST,
        )
        for sentinel in ("Patrick62109", "MKSherm81765",
                         "e&t082826"):
            self.assertNotIn(sentinel, record["summary"] or "")


class CoverageRefinementTests(unittest.TestCase):
    def test_coverage_query_filters_audio_with_extracted_text(self):


        src = inspect.getsource(vu.coverage_for_vault)
                                                              
        self.assertIn(
            "extracted_text_status <> 'available'", src,
        )
                                                            
                                                         
        self.assertIn("mp3", src)


class AvailabilityFlagTests(unittest.TestCase):
    def test_audio_available_is_bool(self):
        self.assertIsInstance(at.AUDIO_AVAILABLE, bool)

    def test_audio_backend_label_is_one_of_known(self):
        self.assertIn(
            at.AUDIO_BACKEND,
            ("openai-whisper", "openai-missing"),
        )


class FileExtensionHelperTests(unittest.TestCase):
    def test_simple_extension(self):
        self.assertEqual(
            at._file_extension("note.mp3"), "mp3",
        )

    def test_uppercase_normalised(self):
        self.assertEqual(
            at._file_extension("NOTE.MP3"), "mp3",
        )

    def test_no_extension_returns_none(self):
        self.assertIsNone(at._file_extension("nodot"))

    def test_trailing_dot_returns_none(self):
        self.assertIsNone(at._file_extension("trailing."))

    def test_empty_returns_none(self):
        self.assertIsNone(at._file_extension(""))
        self.assertIsNone(at._file_extension(None))


if __name__ == "__main__":
    unittest.main()
