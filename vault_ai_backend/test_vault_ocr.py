

from __future__ import annotations

import inspect
import os
import unittest

import vault_analysis as va
import vault_analysis_ocr as ocr_mod
import vault_document_purpose as vp
import vault_file_analysis as vfa
import vault_inventory as vi
import vault_understanding as vu
import vault_understanding_search as vus


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765",
)


class SupportGateTests(unittest.TestCase):
    def test_jpeg_supported_by_extension(self):
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.jpg"))
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.jpeg"))

    def test_png_supported_by_extension(self):
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.png"))

    def test_webp_and_tiff_supported(self):
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.webp"))
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.tiff"))
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.tif"))

    def test_bmp_supported(self):
        self.assertTrue(ocr_mod.supports_ocr(file_name="x.bmp"))

    def test_unsupported_image_types(self):
                                                                  
                                                                  
        self.assertFalse(
            ocr_mod.supports_ocr(file_name="x.svg"), "x.svg",
        )

    def test_supported_via_mime(self):
        for mt in (
            "image/jpeg", "image/png", "image/webp",
            "image/tiff", "image/bmp",
        ):
            self.assertTrue(
                ocr_mod.supports_ocr(
                    file_name=None, content_type=mt,
                ), mt,
            )

    def test_non_image_unsupported(self):
        for mt in ("application/pdf", "text/plain", "audio/mpeg"):
            self.assertFalse(
                ocr_mod.supports_ocr(file_name=None, content_type=mt),
                mt,
            )

    def test_null_inputs(self):
        self.assertFalse(ocr_mod.supports_ocr(
            file_name=None, content_type=None,
        ))


class ExtractOcrTextTests(unittest.TestCase):
    def setUp(self):
                                                                    
                                                               
        self._original = ocr_mod._OCR_ENGINE

    def tearDown(self):
        ocr_mod._OCR_ENGINE = self._original

    def test_unsupported_type_raises_OCRError(self):
        ocr_mod.set_ocr_engine(lambda b, m: "ignored")
        with self.assertRaises(ocr_mod.OCRError):
            ocr_mod.extract_ocr_text(
                file_name="doc.pdf",
                file_bytes=b"fake pdf bytes",
                content_type="application/pdf",
            )

    def test_empty_bytes_raises_OCRError(self):
        ocr_mod.set_ocr_engine(lambda b, m: "ignored")
        with self.assertRaises(ocr_mod.OCRError):
            ocr_mod.extract_ocr_text(
                file_name="x.png", file_bytes=b"",
                content_type="image/png",
            )

    def test_missing_engine_raises_OCRError(self):
        ocr_mod.set_ocr_engine(None)
        with self.assertRaises(ocr_mod.OCRError) as ctx:
            ocr_mod.extract_ocr_text(
                file_name="x.png",
                file_bytes=b"image bytes",
                content_type="image/png",
            )
                                                                 
                                                             
        self.assertIn("OCR engine unavailable", str(ctx.exception))

    def test_engine_runtime_error_wraps_OCRError(self):
        def boom(b, m):
            raise RuntimeError("tesseract child died")
        ocr_mod.set_ocr_engine(boom)
        with self.assertRaises(ocr_mod.OCRError) as ctx:
            ocr_mod.extract_ocr_text(
                file_name="x.png", file_bytes=b"bytes",
                content_type="image/png",
            )
        self.assertIn("tesseract child died", str(ctx.exception))

    def test_engine_returning_text_is_normalised(self):
                                                                    
                                                         
        ocr_mod.set_ocr_engine(
            lambda b, m: "Hello world\f\n\n\n\nSecond line\x00 trailing"
        )
        text, truncated = ocr_mod.extract_ocr_text(
            file_name="x.png", file_bytes=b"bytes",
            content_type="image/png",
        )
        self.assertIn("Hello world", text)
        self.assertIn("Second line", text)
        self.assertNotIn("\x00", text)
                                                          
        self.assertNotIn("\n\n\n", text)
        self.assertFalse(truncated)

    def test_truncation_sets_flag(self):
        long_text = "A" * (ocr_mod.MAX_OCR_CHARS + 100)
        ocr_mod.set_ocr_engine(lambda b, m: long_text)
        text, truncated = ocr_mod.extract_ocr_text(
            file_name="x.png", file_bytes=b"bytes",
            content_type="image/png",
            max_chars=ocr_mod.MAX_OCR_CHARS,
        )
        self.assertTrue(truncated)
        self.assertEqual(len(text), ocr_mod.MAX_OCR_CHARS)

    def test_engine_returning_None_is_empty(self):
        ocr_mod.set_ocr_engine(lambda b, m: None)
        text, truncated = ocr_mod.extract_ocr_text(
            file_name="x.png", file_bytes=b"bytes",
            content_type="image/png",
        )
        self.assertEqual(text, "")
        self.assertFalse(truncated)


class DefaultStagesForFileTests(unittest.TestCase):
    def test_image_routes_to_ocr_stage(self):
        for name in ("photo.jpg", "screenshot.png", "scan.tiff"):
            self.assertEqual(
                va.default_stages_for_file(file_name=name),
                [va.STAGE_OCR],
                name,
            )

    def test_image_via_mime_routes_to_ocr(self):
        for mt in ("image/jpeg", "image/png", "image/webp"):
            self.assertEqual(
                va.default_stages_for_file(
                    file_name="x.bin", content_type=mt,
                ),
                [va.STAGE_OCR],
                mt,
            )

    def test_pdf_still_routes_to_text_extraction(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="doc.pdf"),
            [va.STAGE_TEXT_EXTRACTION],
        )

    def test_docx_still_routes_to_text_extraction(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="report.docx"),
            [va.STAGE_TEXT_EXTRACTION],
        )

    def test_archive_routes_to_archive_indexing(self):
                                                           
                                                          
        self.assertEqual(
            va.default_stages_for_file(file_name="bundle.zip"),
            [va.STAGE_ARCHIVE_INDEXING],
        )

    def test_heic_now_routes_through_ocr(self):
                                                                   
                                                                    
        self.assertIn(
            va.STAGE_OCR,
            va.default_stages_for_file(file_name="photo.heic"),
        )


class WorkerSourceGuardTests(unittest.TestCase):
    def _src(self, func):
        return inspect.getsource(func)

    def test_drain_claims_only_ocr_jobs(self):
        import vault_ocr_worker as vow
        src = self._src(vow.drain_ocr)
                                                           
                                                             
        self.assertIn("_HANDLED_STAGE", src)
        self.assertIn("_release_unhandled_job", src)
        mod_src = inspect.getsource(vow)
        self.assertIn("STAGE_OCR", mod_src)

    def test_worker_encrypts_before_persist(self):
        import vault_ocr_worker as vow
        src = self._src(vow._process_one_ocr_job)
        encrypt_idx = src.find("encrypt_message")
        persist_idx = src.find("_persist_extracted_text")
        self.assertGreater(encrypt_idx, -1)
        self.assertGreater(persist_idx, -1)
        self.assertLess(
            encrypt_idx, persist_idx,
            "OCR text MUST be encrypted BEFORE the persist call — "
            "the CHECK constraint refuses plaintext, but defence-"
            "in-depth still requires this order in source",
        )

    def test_worker_drops_plaintext_after_use(self):
        import vault_ocr_worker as vow
        src = self._src(vow._process_one_ocr_job)
                                                                    
                                           
        self.assertIn("plaintext_bytes = None", src)
        self.assertIn('text = ""', src)

    def test_worker_persists_with_source_ocr(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow)
        self.assertIn('source="ocr"', src)

    def test_worker_enqueues_understanding_after_success(self):
        import vault_ocr_worker as vow
        src = self._src(vow._process_one_ocr_job)
                                                               
        complete_idx = src.find("complete_analysis_job")
        enqueue_idx = src.find("enqueue_understanding_after_text_extraction")
        self.assertGreater(complete_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(
            complete_idx, enqueue_idx,
            "OCR job must be completed BEFORE the understanding "
            "enqueue so a duplicate retry doesn't spawn a dangling "
            "understanding job",
        )

    def test_unsupported_storage_mode_does_not_retry(self):
        import vault_ocr_worker as vow
        src = self._src(vow._process_one_ocr_job)
                                                                
                                                                 
        self.assertIn(
            "mark_file_analysis_unsupported", src,
        )

    def test_chat_handler_runs_drain_ocr_after_text_extraction(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        text_idx = src.find("drain_text_extraction")
        ocr_idx = src.find("drain_ocr")
        understanding_idx = src.find("drain_file_understanding")
        self.assertGreater(text_idx, -1)
        self.assertGreater(ocr_idx, -1)
        self.assertGreater(understanding_idx, -1)
        self.assertLess(
            text_idx, ocr_idx,
            "text-extraction drain must come BEFORE the OCR drain "
            "so cheap text jobs drain first",
        )
        self.assertLess(
            ocr_idx, understanding_idx,
            "OCR drain must come BEFORE the understanding drain so "
            "freshly-OCR'd images land in the understanding index "
            "in the same chat turn",
        )


class SafetyTests(unittest.TestCase):
    def test_worker_never_executes_user_content(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(
                forbidden, src,
                f"OCR worker MUST NOT use {forbidden} on user "
                "content — uploaded image text is data, not code",
            )

    def test_ocr_module_never_executes_user_content(self):
        src = inspect.getsource(ocr_mod)
        for forbidden in ("eval(", "exec(",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_worker_does_not_touch_vault_items_table(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow)
                                                                  
                                              
        for forbidden in (
            "INSERT INTO vault_items",
            "vault_items",
        ):
            self.assertNotIn(forbidden, src, forbidden)

    def test_worker_logs_do_not_include_plaintext(self):
        import vault_ocr_worker as vow
        src = inspect.getsource(vow)
        for forbidden in ('logger.info("%s", text',
                          'logger.info("%s", plaintext',
                          'logger.warning("%s", text',
                          'logger.error("%s", text',
                          'print("%s" % text'):
            self.assertNotIn(forbidden, src)


def _understanding_row_for_image(
    *, file_id, extracted_text, file_name,
):


    metrics = vi._compute_credential_density_metrics(extracted_text)
    purpose = vp.classify_document_purpose(
        extracted_text, metrics=metrics,
    )
    record = vu.build_understanding(
        extracted_text,
        metrics=metrics,
        purpose_decision=purpose,
        file_name=file_name,
    )
    return {
        "file_id":                  file_id,
        "file_name":                file_name,
        "saved_name":               "",
        "relative_path":            "",
        "content_type":             "image/png",
        "asset_type":               "file",
        "extracted_text":           None,
        "extracted_text_encrypted": False,
        "understanding_status":     "ready",
        "document_purpose":         record["document_purpose"],
        "purpose_label":            record.get("purpose_label") or "",
        "summary_encrypted":        None,
        "safe_preview_encrypted":   None,
        "topics_jsonb":             record["topics"],
        "entities_jsonb":           record["entities"],
        "dates_jsonb":              record["dates"],
        "detected_categories_jsonb": record["detected_categories"],
        "searchable_terms_jsonb":   record["searchable_terms"],
    }


class OcrTextBecomesSearchableTests(unittest.TestCase):
    def test_image_with_wells_fargo_text_is_found(self):
                                                         
        ocr_text = (
            "Wells Fargo Bank\n"
            "Statement Period: 2024-01-01 to 2024-01-31\n"
            "Account ending 1234\n"
            "Beginning balance: $1,234.56\n"
        )
        row = _understanding_row_for_image(
            file_id="wf_image",
            extracted_text=ocr_text,
            file_name="screenshot.png",
        )
        m = vus._score_row(
            row=row, query_low="wells fargo",
            query_tokens=["wells", "fargo"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(
            m,
            "an OCR'd image whose text contains 'Wells Fargo' MUST "
            "be found via the understanding-index search (the "
            "filename is screenshot.png — no 'wells' token)",
        )
                                                               
                                        
        self.assertLessEqual(
            m["tier"], vus.TIER_TERM,
            "OCR'd Wells Fargo text should produce an "
            "entity / category / topic / term match, not a "
            "filename fallback",
        )

    def test_image_with_maureen_text_is_found_by_entity(self):
        ocr_text = (
            "Maureen Smith\n"
            "DOB 1990-05-15\n"
            "Photo ID — California\n"
        )
        row = _understanding_row_for_image(
            file_id="maureen_id",
            extracted_text=ocr_text,
            file_name="ph_id_scan.jpg",
        )
        m = vus._score_row(
            row=row, query_low="maureen",
            query_tokens=["maureen"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "entity")
        self.assertIn("Maureen", m["match_reason"])

    def test_image_with_receipt_text_finds_walmart_entity(self):
                                                                
                                                             
        ocr_text = (
            "Walmart Supercenter\n"
            "Store #1234 Receipt\n"
            "Total: $12.34\n"
        )
        row = _understanding_row_for_image(
            file_id="walmart_receipt",
            extracted_text=ocr_text,
            file_name="img_2024_07.png",
        )
                                                          
                                               
        m = vus._score_row(
            row=row, query_low="walmart",
            query_tokens=["walmart"],
            purpose_hints=[], category_hints=[], topic_hints=[],
            date_hint=None, key=None,
        )
        self.assertIsNotNone(m)
        self.assertNotEqual(
            m["match_type"], "filename",
            "Walmart text in the OCR should match above filename",
        )


class CredentialOcrTextIsSafeTests(unittest.TestCase):
    def test_credential_dump_screenshot_classified_correctly(self):
        ocr_text = "\n".join([
            "AOL", "alice@example.com", "Patrick62109",
            "Apple", "bob@example.com", "MKSherm81765",
            "American Express", "carol@example.com", "e&t082826",
            "Wells Fargo", "dan@example.com", "sunshine6856",
            "Gmail", "erin@example.com", "loul82!Bridge",
            "Netflix", "frank@example.com", "Sky88!morning",
        ])
        metrics = vi._compute_credential_density_metrics(ocr_text)
        verdict = vp.classify_document_purpose(
            ocr_text, metrics=metrics,
        )
        self.assertEqual(
            verdict["purpose"], vp.PURPOSE_SAVED_LOGIN_LIST,
            "an OCR'd screenshot of saved logins should fire the "
            "saved_login_list verdict — same vocabulary the "
            "text-extraction path uses",
        )

    def test_safe_summariser_does_not_leak_passwords_from_ocr(self):
        ocr_text = "\n".join([
            "AOL", "alice@example.com", "Patrick62109",
            "Apple", "bob@example.com", "MKSherm81765",
            "American Express", "carol@example.com", "e&t082826",
            "Wells Fargo", "dan@example.com", "sunshine6856",
            "Gmail", "erin@example.com", "loul82!Bridge",
            "Netflix", "frank@example.com", "Sky88!morning",
        ])
        metrics = vi._compute_credential_density_metrics(ocr_text)
        purpose = vp.classify_document_purpose(
            ocr_text, metrics=metrics,
        )
        reply = vfa.build_safe_file_analysis(
            ocr_text,
            file_name="logins-screenshot.png",
            metrics=metrics,
            purpose_decision=purpose,
        )
        for sentinel in SENTINELS:
            self.assertNotIn(
                sentinel, reply,
                f"OCR'd credential text leaked sentinel {sentinel!r}",
            )

    def test_understanding_built_from_ocr_does_not_leak_values(self):
        ocr_text = "\n".join([
            "AOL", "alice@example.com", "Patrick62109",
            "Apple", "bob@example.com", "MKSherm81765",
            "American Express", "carol@example.com", "e&t082826",
            "Wells Fargo", "dan@example.com", "sunshine6856",
            "Gmail", "erin@example.com", "loul82!Bridge",
            "Netflix", "frank@example.com", "Sky88!morning",
        ])
        record = vu.build_understanding(
            ocr_text, file_name="logins-screenshot.png",
        )
                                                            
                                               
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, record["summary"])
            self.assertNotIn(sentinel, record["safe_preview"])
            self.assertNotIn(
                sentinel.lower(), record["searchable_terms"],
            )


class CoverageWordingTests(unittest.TestCase):
    def test_coverage_formatter_mentions_OCR_when_pending(self):
        text = vu.format_coverage_for_chat({
            "total_files":                 5,
            "files_understood":            2,
            "files_pending":               0,
            "files_text_only":             0,
            "files_needing_ocr":           3,
            "files_needing_transcription": 0,
            "files_unsupported":           0,
        })
        self.assertIn("OCR", text)

    def test_coverage_formatter_drops_OCR_mention_when_done(self):
        text = vu.format_coverage_for_chat({
            "total_files":                 5,
            "files_understood":            5,
            "files_pending":               0,
            "files_text_only":             0,
            "files_needing_ocr":           0,
            "files_needing_transcription": 0,
            "files_unsupported":           0,
        })
        self.assertNotIn("OCR", text)


class OcrAvailabilityFlagTests(unittest.TestCase):
    def test_flag_is_boolean(self):
        self.assertIsInstance(ocr_mod.OCR_AVAILABLE, bool)

    def test_backend_string_is_known(self):
        self.assertIn(
            ocr_mod.OCR_BACKEND,
            ("pytesseract", "pytesseract-missing", "pillow-missing"),
        )


class FileExtensionHelperTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(ocr_mod.file_extension("photo.JPG"), "jpg")
        self.assertEqual(ocr_mod.file_extension("a.tar.gz"), "gz")
        self.assertIsNone(ocr_mod.file_extension(""))
        self.assertIsNone(ocr_mod.file_extension(None))
        self.assertIsNone(ocr_mod.file_extension("noext"))


if __name__ == "__main__":
    unittest.main()
