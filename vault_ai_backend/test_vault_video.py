

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
import vault_video_transcription as vt


class SupportsVideoTranscriptionTests(unittest.TestCase):
    def test_mp4_supported(self):
        self.assertTrue(
            vt.supports_video_transcription(file_name="trip.mp4")
        )

    def test_mov_supported(self):
        self.assertTrue(
            vt.supports_video_transcription(file_name="rec.mov")
        )

    def test_m4v_supported(self):
        self.assertTrue(
            vt.supports_video_transcription(file_name="clip.m4v")
        )

    def test_mkv_supported(self):
        self.assertTrue(
            vt.supports_video_transcription(file_name="movie.mkv")
        )

    def test_avi_supported(self):
        self.assertTrue(
            vt.supports_video_transcription(file_name="old.avi")
        )

    def test_video_webm_mime_supported(self):
        self.assertTrue(
            vt.supports_video_transcription(
                file_name="rec.webm",
                content_type="video/webm",
            )
        )

    def test_webm_without_mime_NOT_supported_here(self):
                                                                
                                                             
        self.assertFalse(
            vt.supports_video_transcription(file_name="rec.webm")
        )

    def test_any_video_mime_prefix_supported(self):
                                                                
                                                    
        for mime in ("video/mp4", "video/quicktime",
                     "video/x-matroska", "video/x-msvideo",
                     "video/3gpp"):
            self.assertTrue(
                vt.supports_video_transcription(
                    file_name="unknown",
                    content_type=mime,
                ),
                f"video MIME {mime} should be accepted",
            )

    def test_audio_mime_not_supported(self):
        self.assertFalse(
            vt.supports_video_transcription(
                file_name="rec.mp3",
                content_type="audio/mpeg",
            )
        )

    def test_pdf_not_supported(self):
        self.assertFalse(
            vt.supports_video_transcription(file_name="doc.pdf")
        )

    def test_image_not_supported(self):
        self.assertFalse(
            vt.supports_video_transcription(file_name="photo.png")
        )


class ExtractAudioFromVideoTests(unittest.TestCase):
    def tearDown(self):
        vt.reset_video_audio_extraction_engine()

    def test_engine_injection_returns_audio_bytes(self):
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: b"\xfaaudio-bytes\x00"
        )
        out = vt.extract_audio_from_video(b"video-bytes")
        self.assertEqual(out, b"\xfaaudio-bytes\x00")

    def test_empty_video_raises(self):
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: b"should-not-be-called"
        )
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.extract_audio_from_video(b"")

    def test_engine_error_wraps_in_video_error(self):
        def _boom(video_bytes):
            raise RuntimeError("ffmpeg failed")
        vt.set_video_audio_extraction_engine(_boom)
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.extract_audio_from_video(b"video-bytes")

    def test_engine_returning_empty_audio_raises(self):
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: b""
        )
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.extract_audio_from_video(b"video-bytes")

    def test_engine_returning_non_bytes_raises(self):
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: "this is a string not bytes"
        )
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.extract_audio_from_video(b"video-bytes")


class TranscribeVideoTests(unittest.TestCase):
    def tearDown(self):
        vt.reset_video_audio_extraction_engine()
        at.reset_audio_transcription_engine()

    def _wire(self, *, transcript: str):
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: b"fake-audio-bytes"
        )
        at.set_audio_transcription_engine(
            lambda audio_bytes, mime, file_name: transcript
        )

    def test_happy_path(self):
        self._wire(transcript="I talked about my graduation today.")
        text, truncated = vt.transcribe_video(
            file_name="grad.mp4", file_bytes=b"video-bytes",
        )
        self.assertIn("graduation", text)
        self.assertFalse(truncated)

    def test_unsupported_extension_raises(self):
        self._wire(transcript="should not be called")
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.transcribe_video(
                file_name="doc.pdf", file_bytes=b"video-bytes",
            )

    def test_empty_video_raises(self):
        self._wire(transcript="should not be called")
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.transcribe_video(
                file_name="trip.mp4", file_bytes=b"",
            )

    def test_oversize_video_raises_fail_no_retry(self):
        self._wire(transcript="should not be called")
        too_big = b"x" * (vt.MAX_VIDEO_BYTES + 1)
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.transcribe_video(
                file_name="trip.mp4", file_bytes=too_big,
            )

    def test_audio_engine_failure_propagates_as_video_error(self):
                                                            
                                                        
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: b"fake-audio"
        )

        def _boom(audio_bytes, mime, file_name):
            raise at.AudioTranscriptionError("provider down")
        at.set_audio_transcription_engine(_boom)
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.transcribe_video(
                file_name="trip.mp4", file_bytes=b"video-bytes",
            )

    def test_corrupt_video_no_audio_track_handled_safely(self):
                                                               
                                                        
        vt.set_video_audio_extraction_engine(
            lambda video_bytes: b""
        )
        with self.assertRaises(vt.VideoTranscriptionError):
            vt.transcribe_video(
                file_name="trip.mp4", file_bytes=b"video-bytes",
            )


class DefaultStagesRoutingTests(unittest.TestCase):
    def test_mp4_routes_to_video(self):
        stages = va.default_stages_for_file(file_name="trip.mp4")
        self.assertEqual(stages, [va.STAGE_VIDEO_TRANSCRIPTION])

    def test_mov_routes_to_video(self):
        stages = va.default_stages_for_file(file_name="clip.mov")
        self.assertEqual(stages, [va.STAGE_VIDEO_TRANSCRIPTION])

    def test_m4v_routes_to_video(self):
        stages = va.default_stages_for_file(file_name="movie.m4v")
        self.assertEqual(stages, [va.STAGE_VIDEO_TRANSCRIPTION])

    def test_mkv_routes_to_video(self):
        stages = va.default_stages_for_file(file_name="movie.mkv")
        self.assertEqual(stages, [va.STAGE_VIDEO_TRANSCRIPTION])

    def test_avi_routes_to_video(self):
        stages = va.default_stages_for_file(file_name="old.avi")
        self.assertEqual(stages, [va.STAGE_VIDEO_TRANSCRIPTION])

    def test_video_webm_routes_to_video(self):
        stages = va.default_stages_for_file(
            file_name="rec.webm",
            content_type="video/webm",
        )
        self.assertEqual(stages, [va.STAGE_VIDEO_TRANSCRIPTION])

    def test_audio_webm_default_routes_to_audio(self):
                                                            
        stages = va.default_stages_for_file(file_name="memo.webm")
        self.assertEqual(stages, [va.STAGE_AUDIO_TRANSCRIPTION])

    def test_audio_webm_explicit_mime_routes_to_audio(self):
        stages = va.default_stages_for_file(
            file_name="memo.webm",
            content_type="audio/webm",
        )
        self.assertEqual(stages, [va.STAGE_AUDIO_TRANSCRIPTION])

    def test_plain_audio_still_routes_to_audio(self):
        for name in ("memo.mp3", "note.m4a", "voice.wav"):
            self.assertEqual(
                va.default_stages_for_file(file_name=name),
                [va.STAGE_AUDIO_TRANSCRIPTION],
                f"{name} should still route to audio",
            )

    def test_pdf_still_routes_to_text_extraction(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="doc.pdf"),
            [va.STAGE_TEXT_EXTRACTION],
        )

    def test_image_still_routes_to_ocr(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="photo.png"),
            [va.STAGE_OCR],
        )


class WorkerSourceGuardTests(unittest.TestCase):
    def test_worker_exists_and_drains_via_claim(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw.drain_video_transcription)
        self.assertIn("claim_next_analysis_job", src)
        mod_src = inspect.getsource(vvw)
        self.assertIn("STAGE_VIDEO_TRANSCRIPTION", mod_src)
        self.assertIn("_HANDLED_STAGE", src)

    def test_worker_calls_transcribe_video(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw._process_one_video_job)
        self.assertIn("transcribe_video", src)

    def test_worker_encrypts_before_persist(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw._process_one_video_job)
        encrypt_idx = src.find("encrypt_message")
        persist_idx = src.find("_persist_extracted_text")
        self.assertGreater(encrypt_idx, -1)
        self.assertGreater(persist_idx, -1)
        self.assertLess(
            encrypt_idx, persist_idx,
            "transcript MUST be encrypted before being persisted",
        )

    def test_worker_persists_with_source_video_transcript(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw._process_one_video_job)
        self.assertIn('source="video_transcript"', src)

    def test_worker_drops_plaintext_bytes_after_use(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw._process_one_video_job)
        self.assertIn("plaintext_bytes = None", src)
        self.assertIn('text = ""', src)

    def test_worker_enqueues_understanding_after_success(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw._process_one_video_job)
        analyzed_idx = src.find("mark_file_analysis_analyzed")
        enqueue_idx = src.find(
            "enqueue_understanding_after_text_extraction"
        )
        self.assertGreater(analyzed_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(analyzed_idx, enqueue_idx)

    def test_worker_calls_stale_helpers_after_success(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw._process_one_video_job)
        self.assertIn(
            "mark_stale_understandings_for_changed_text", src,
        )
        self.assertIn(
            "mark_stale_embeddings_for_changed_text", src,
        )


class FfmpegSafetyTests(unittest.TestCase):
    def test_ffmpeg_invocation_uses_shell_false(self):
                                                               
                                                            
        src = inspect.getsource(vt._default_ffmpeg_engine)
        try:
            tree = ast.parse(src.lstrip())
            fn = tree.body[0]
            doc = ast.get_docstring(fn) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertIn('"ffmpeg"', code_only)
        self.assertIn("shell=False", code_only)
        self.assertNotIn("shell=True", code_only)

    def test_ffmpeg_uses_nostdin_to_block_stdin_injection(self):
        src = inspect.getsource(vt._default_ffmpeg_engine)
        self.assertIn("-nostdin", src)

    def test_ffmpeg_uses_vn_to_drop_video_stream(self):
                                                          
                                                               
        src = inspect.getsource(vt._default_ffmpeg_engine)
        self.assertIn("-vn", src)

    def test_ffmpeg_has_timeout(self):
        src = inspect.getsource(vt._default_ffmpeg_engine)
        self.assertIn("timeout=", src)

    def test_ffmpeg_does_not_log_stderr(self):
                                                                
                                                
        src = inspect.getsource(vt._default_ffmpeg_engine)
        for forbidden in (
            "logger.info(proc.stderr",
            "logger.warning(proc.stderr",
            'print(proc.stderr',
        ):
            self.assertNotIn(forbidden, src)


class SafetyFloorTests(unittest.TestCase):
    def test_video_module_never_executes_user_content(self):
        src = inspect.getsource(vt)
                                                         
                                                              
        for forbidden in ("eval(", "exec(", "os.system(", "popen("):
            self.assertNotIn(
                forbidden, src,
                f"video module MUST NOT use {forbidden} on user "
                "content",
            )

    def test_worker_never_executes_user_content(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_worker_does_not_touch_vault_items_table(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw)
        try:
            tree = ast.parse(src)
            doc = ast.get_docstring(tree) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertNotIn("INSERT INTO vault_items", code_only)
        self.assertNotIn("vault_items", code_only)

    def test_worker_logs_do_not_include_transcript(self):
        import vault_video_worker as vvw
        src = inspect.getsource(vvw)
        for forbidden in (
            'logger.info("%s", text',
            'logger.info("%s", plaintext',
            'logger.info("%s", transcript',
            'logger.exception("%s", text',
            'logger.exception("%s", transcript',
            'logger.info("%s", file_bytes',
        ):
            self.assertNotIn(forbidden, src)

    def test_video_module_logs_do_not_include_bytes(self):
        src = inspect.getsource(vt)
        for forbidden in (
            'logger.info("%s", file_bytes',
            'logger.info("%s", video_bytes',
            'logger.info("%s", audio_bytes',
            'logger.exception("%s", file_bytes',
            'logger.exception("%s", video_bytes',
            'logger.exception("%s", audio_bytes',
        ):
            self.assertNotIn(forbidden, src)


class ChatHandlerWiringTests(unittest.TestCase):
    def test_chat_handler_runs_video_drain_after_audio(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        audio_idx = src.find("drain_audio_transcription")
        video_idx = src.find("drain_video_transcription")
        self.assertGreater(audio_idx, -1)
        self.assertGreater(video_idx, -1)
        self.assertLess(
            audio_idx, video_idx,
            "video drain must run AFTER audio because it adds an "
            "extra ffmpeg extraction step on top of the Whisper "
            "round-trip",
        )

    def test_chat_handler_runs_video_drain_before_understanding(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        video_idx = src.find("drain_video_transcription")
        understanding_idx = src.find("drain_file_understanding")
        self.assertGreater(video_idx, -1)
        self.assertGreater(understanding_idx, -1)
        self.assertLess(
            video_idx, understanding_idx,
            "freshly transcribed video must feed the understanding "
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
            "content_type":         "video/mp4",
            "asset_type":           "video",
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

    def test_video_about_wells_fargo_findable_by_entity(self):
        rows = [self._make_row(
            file_id="video-1",
            file_name="IMG_0123.mp4",
            entities={"names": ["Wells Fargo"], "email_domains": []},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "find videos mentioning Wells Fargo",
            )
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["match_type"], "entity")

    def test_video_about_graduation_findable_by_entity(self):
                                                                 
                                                           
        rows = [self._make_row(
            file_id="video-2",
            file_name="IMG_0888.mp4",
            entities={"names": ["Graduation"]},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Graduation",
            )
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["match_type"], "entity")


class TranscriptCredentialSafetyTests(unittest.TestCase):
    def test_video_transcript_inline_password_phrase_does_not_leak(self):
                                                                
                                                                
        transcript = "\n".join([
            "Today's video log.",
            "Talked to the bank.",
            "My password is hunter2 by the way.",
            "Should also remember to renew the lease.",
        ])
        record = vu.build_understanding(
            transcript, file_name="vlog_2024_04_15.mp4",
        )
        self.assertNotIn("hunter2", record["safe_preview"] or "")


class AvailabilityFlagTests(unittest.TestCase):
    def test_video_available_is_bool(self):
        self.assertIsInstance(vt.VIDEO_AVAILABLE, bool)

    def test_video_backend_label_is_one_of_known(self):
        self.assertIn(
            vt.VIDEO_BACKEND,
            ("ffmpeg-openai", "ffmpeg-missing", "openai-missing"),
        )


class FileExtensionHelperTests(unittest.TestCase):
    def test_simple_extension(self):
        self.assertEqual(vt._file_extension("note.mp4"), "mp4")

    def test_uppercase_normalised(self):
        self.assertEqual(vt._file_extension("NOTE.MP4"), "mp4")

    def test_no_extension_returns_none(self):
        self.assertIsNone(vt._file_extension("nodot"))


if __name__ == "__main__":
    unittest.main()
