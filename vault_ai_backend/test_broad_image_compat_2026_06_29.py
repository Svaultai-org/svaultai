

from __future__ import annotations

import io
import json
import logging
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

from PIL import Image

import vault_image_formats as vif
import vault_image_audit as via
import vault_image_reconciler as vir
import vault_complete_search as vcs
import vault_analysis_ocr as voa
import main


def _noisy_rgb(seed: int = 1, w: int = 64, h: int = 48) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    s = seed & 0xFFFFFFFF
    for y in range(h):
        for x in range(w):
            s = (1103515245 * s + 12345) & 0xFFFFFFFF
            px[x, y] = ((s >> 16) & 0xFF, (s >> 8) & 0xFF, s & 0xFF)
    return img


def _save(fmt: str, **kwargs) -> bytes:
    img = _noisy_rgb()
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _jpeg() -> bytes:   return _save("JPEG", quality=85)
def _png() -> bytes:    return _save("PNG")
def _gif() -> bytes:    return _save("GIF")
def _bmp() -> bytes:    return _save("BMP")
def _tiff() -> bytes:   return _save("TIFF")
def _webp() -> bytes:   return _save("WEBP")


def _heic() -> Optional[bytes]:
    try:
        import pillow_heif              
        pillow_heif.register_heif_opener()
    except Exception:
        return None
    return _save("HEIF", quality=85)


def _avif() -> Optional[bytes]:
    try:
        from PIL import features
        if not features.check("avif"):
            return None
    except Exception:
        return None
    try:
        return _save("AVIF", quality=85)
    except Exception:
        return None


def _svg() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<svg xmlns="http://www.w3.org/2000/svg" '
        b'viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
    )


class TestEveryFormatDetected(unittest.TestCase):


    _CASES = [
        ("image/jpeg", "id.jpg",  "jpeg"),
        ("image/jpeg", "id.jpeg", "jpeg"),
        ("image/jpeg", "id.jfif", "jpeg"),
        ("image/png",  "id.png",  "png"),
        ("image/heic", "id.heic", "heic"),
        ("image/heif", "id.heif", "heif"),
        ("image/webp", "id.webp", "webp"),
        ("image/tiff", "id.tif",  "tiff"),
        ("image/tiff", "id.tiff", "tiff"),
        ("image/bmp",  "id.bmp",  "bmp"),
        ("image/bmp",  "id.dib",  "bmp"),
        ("image/gif",  "id.gif",  "gif"),
        ("image/avif", "id.avif", "avif"),
        ("image/svg+xml", "art.svg", "svg"),
    ]

    def test_mime_detects_every_format(self):
        for mime, _name, label in self._CASES:
            with self.subTest(mime=mime):
                self.assertTrue(vif.is_supported_image_mime(mime))
                self.assertEqual(
                    vif.detect_image_format(mime=mime), label,
                )

    def test_extension_detects_every_format(self):
        for _mime, name, label in self._CASES:
            with self.subTest(name=name):
                self.assertTrue(
                    vif.is_supported_image_extension(name),
                )
                self.assertEqual(
                    vif.detect_image_format(file_name=name), label,
                )

    def test_magic_bytes_detect_raster_formats(self):
        for fixture, expected_mime in [
            (_jpeg(), "image/jpeg"),
            (_png(),  "image/png"),
            (_gif(),  "image/gif"),
            (_bmp(),  "image/bmp"),
            (_tiff(), "image/tiff"),
            (_webp(), "image/webp"),
            (_svg(),  "image/svg+xml"),
        ]:
            with self.subTest(mime=expected_mime):
                self.assertEqual(
                    vif.detect_mime_from_bytes(fixture),
                    expected_mime,
                )

    def test_magic_bytes_detect_heic_when_decoder_present(self):
        heic = _heic()
        if heic is None:
            self.skipTest("pillow-heif not installed in this venv")
                                                           
                                                                
        self.assertEqual(
            vif.detect_mime_from_bytes(heic),
            "image/heic",
        )

    def test_magic_bytes_detect_avif_when_decoder_present(self):
        avif = _avif()
        if avif is None:
            self.skipTest("AVIF decoder not present")
        self.assertEqual(
            vif.detect_mime_from_bytes(avif),
            "image/avif",
        )


class TestOctetStreamFallback(unittest.TestCase):


    def test_all_formats_classified_via_extension_fallback(self):
        for ext, label in [
            ("ID.HEIC", "heic"),
            ("scan.TIF", "tiff"),
            ("scan.tiff", "tiff"),
            ("logo.SVG", "svg"),
            ("photo.WebP", "webp"),
            ("doc.BMP", "bmp"),
            ("animated.GIF", "gif"),
            ("modern.avif", "avif"),
        ]:
            with self.subTest(name=ext):
                self.assertTrue(
                    vif.is_image_row(
                        mime="application/octet-stream",
                        file_name=ext,
                    )
                )
                self.assertEqual(
                    vif.detect_image_format(
                        mime="application/octet-stream",
                        file_name=ext,
                    ),
                    label,
                )


class TestDecodeBands(unittest.TestCase):


    def test_jpeg_round_trip_band_ok(self):
        _, _, band = vif.normalize_with_reason(
            _jpeg(), mime_hint="image/jpeg",
        )
        self.assertEqual(band, vif.DECODE_BAND_OK)

    def test_png_round_trip_band_ok(self):
        _, _, band = vif.normalize_with_reason(
            _png(), mime_hint="image/png",
        )
        self.assertEqual(band, vif.DECODE_BAND_OK)

    def test_tiff_normalises_band_ok(self):
        _, _, band = vif.normalize_with_reason(
            _tiff(), mime_hint="image/tiff",
        )
        self.assertEqual(band, vif.DECODE_BAND_OK)

    def test_svg_band_unsupported_format(self):
        out, _, band = vif.normalize_with_reason(
            _svg(), mime_hint="image/svg+xml",
        )
        self.assertIsNone(out)
        self.assertEqual(band, vif.DECODE_BAND_UNSUPPORTED_FORMAT)

    def test_empty_input_band(self):
        out, _, band = vif.normalize_with_reason(b"")
        self.assertIsNone(out)
        self.assertEqual(band, vif.DECODE_BAND_EMPTY_INPUT)

    def test_corrupt_jpeg_band(self):
                                                                 
                                      
        out, _, band = vif.normalize_with_reason(
            b"\xff\xd8\xff" + b"\x00" * 64,
            mime_hint="image/jpeg",
        )
        self.assertIsNone(out)
        self.assertEqual(band, vif.DECODE_BAND_CORRUPT)

    def test_random_bytes_band_unsupported(self):
                                                                    
        out, _, band = vif.normalize_with_reason(
            b"hello world this is not an image",
            mime_hint=None,
        )
        self.assertIsNone(out)
        self.assertEqual(band, vif.DECODE_BAND_UNSUPPORTED_FORMAT)

    def test_heic_band_when_decoder_missing(self):
                                                            
                                         
        with patch("vault_image_formats._HEIF_AVAILABLE", False), \
             patch("vault_image_formats._OPTIONAL_DECODERS_REGISTERED", True):
                                                                     
                                                             
            heic_header = (
                b"\x00\x00\x00\x18ftypheic"
                b"\x00\x00\x00\x00mif1heic"
            )
            out, _, band = vif.normalize_with_reason(
                heic_header, mime_hint="image/heic",
            )
        self.assertIsNone(out)
        self.assertEqual(band, vif.DECODE_BAND_DECODER_MISSING)


class TestVaultImageAudit(unittest.TestCase):
    def _rows(self) -> list[dict]:
        return [
                                                 
            {"id": "1", "vault_id": "v1",
             "content_type": "image/jpeg", "asset_type": "image",
             "saved_name": "a.jpg", "file_name": "a.jpg"},
                                                                      
            {"id": "2", "vault_id": "v1",
             "content_type": "application/octet-stream",
             "asset_type": "file",
             "saved_name": "iphone.heic", "file_name": "iphone.heic"},
                                                                     
            {"id": "3", "vault_id": "v1",
             "content_type": "image/webp", "asset_type": "document",
             "saved_name": "id.webp", "file_name": "id.webp"},
                  
            {"id": "4", "vault_id": "v1",
             "content_type": "image/svg+xml", "asset_type": "image",
             "saved_name": "art.svg", "file_name": "art.svg"},
                                                              
            {"id": "5", "vault_id": "v1",
             "content_type": "application/pdf", "asset_type": "file",
             "saved_name": "tax.pdf", "file_name": "tax.pdf"},
        ]

    def test_audit_counts_image_like(self):
        report = via.audit_vault_images(
            vault_id="v1", rows=self._rows(),
        )
        self.assertEqual(report["total_rows_inspected"], 5)
        self.assertEqual(report["total_image_like"], 4)
        self.assertEqual(
            report["by_detected_format"]["jpeg"], 1,
        )
        self.assertEqual(
            report["by_detected_format"]["heic"], 1,
        )
        self.assertEqual(
            report["by_detected_format"]["webp"], 1,
        )
        self.assertEqual(
            report["by_detected_format"]["svg"], 1,
        )
                                    
        self.assertEqual(
            report["by_detected_format"]["other"], 0,
        )

    def test_audit_reports_asset_type_mismatch(self):
        report = via.audit_vault_images(
            vault_id="v1", rows=self._rows(),
        )
                                                  
        self.assertEqual(
            report["asset_type_image_mismatched"], 2,
        )

    def test_audit_reports_octet_stream_but_image(self):
        report = via.audit_vault_images(
            vault_id="v1", rows=self._rows(),
        )
                                                        
        self.assertEqual(report["octet_stream_but_image"], 1)

    def test_audit_by_extension_and_mime(self):
        report = via.audit_vault_images(
            vault_id="v1", rows=self._rows(),
        )
        self.assertEqual(report["by_extension"]["jpg"], 1)
        self.assertEqual(report["by_extension"]["heic"], 1)
        self.assertEqual(report["by_extension"]["webp"], 1)
        self.assertEqual(report["by_extension"]["svg"], 1)
                                
        self.assertEqual(
            report["by_canonical_mime"]["image/jpeg"], 1,
        )
        self.assertEqual(
            report["by_canonical_mime"]["image/heic"], 1,
        )

    def test_audit_includes_decoder_availability(self):
        report = via.audit_vault_images(
            vault_id="v1", rows=self._rows(),
        )
        self.assertIn("decoder_availability", report)
        self.assertIsInstance(
            report["decoder_availability"], dict,
        )
        for k in ("pillow", "heif", "avif"):
            self.assertIn(k, report["decoder_availability"])

    def test_audit_never_leaks_filenames_or_content(self):
        rows = self._rows()
                                                      
        rows[0]["saved_name"] = "BOB_SMITH_SECRET_DRIVERS_LICENSE.jpg"
        rows[0]["file_name"] = "BOB_SMITH_SECRET_DRIVERS_LICENSE.jpg"
                              
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        rclogger = logging.getLogger("vault_image_audit")
        rclogger.addHandler(sink)
        try:
            report = via.audit_vault_images(
                vault_id="vault_xyz_secret", rows=rows,
            )
        finally:
            rclogger.removeHandler(sink)
                                                      
        joined = "\n".join(r.getMessage() for r in records)
        self.assertNotIn("BOB_SMITH_SECRET_DRIVERS_LICENSE", joined)
                                                 
        self.assertNotIn(
            "BOB_SMITH_SECRET_DRIVERS_LICENSE",
            json.dumps(report),
        )
                                     
        self.assertNotIn("vault_xyz_secret", json.dumps(report))

    def test_audit_db_failure_returns_safe_report(self):
        with patch(
            "vault_image_audit._fetch_rows",
            side_effect=RuntimeError("simulated db crash"),
        ):
            report = via.audit_vault_images(vault_id="v1")
        self.assertTrue(report["db_unavailable"])
        self.assertEqual(report["db_error_class"], "RuntimeError")
        self.assertEqual(report["total_image_like"], 0)
                                                
        self.assertNotIn("simulated db crash", json.dumps(report))


class TestVaultImageReconciler(unittest.TestCase):
    def _rows(self) -> list[dict]:
        return [
                                                              
            {"id": "h1", "vault_id": "v1",
             "content_type": "application/octet-stream",
             "asset_type": "file",
             "saved_name": "iphone.heic", "file_name": "iphone.heic"},
                                                                  
            {"id": "t1", "vault_id": "v1",
             "content_type": "image/tiff",
             "asset_type": "document",
             "saved_name": "scan.tif", "file_name": "scan.tif"},
                              
            {"id": "j1", "vault_id": "v1",
             "content_type": "image/jpeg",
             "asset_type": "image",
             "saved_name": "ok.jpg", "file_name": "ok.jpg"},
                                              
            {"id": "p1", "vault_id": "v1",
             "content_type": "application/pdf",
             "asset_type": "file",
             "saved_name": "x.pdf", "file_name": "x.pdf"},
        ]

    def test_dry_run_reports_would_update_without_writing(self):
                                                            
        executor = MagicMock()
        report = vir.reconcile_vault_images(
            vault_id="v1", dry_run=True,
            rows=self._rows(), db_executor=executor,
        )
        self.assertEqual(report["would_update"], 2)
        self.assertEqual(report["updated"], 0)
        executor.assert_not_called()

    def test_applied_run_invokes_executor_with_candidates(self):
        captured = {}

        def _exec(updates):
            captured["candidate_ids"] = [u["id"] for u in updates]
            return {"updated": len(updates), "failed": []}

        report = vir.reconcile_vault_images(
            vault_id="v1", dry_run=False,
            rows=self._rows(), db_executor=_exec,
        )
        self.assertEqual(report["updated"], 2)
        self.assertEqual(set(captured["candidate_ids"]),
                         {"h1", "t1"})
                                                             
        self.assertNotIn("p1", captured["candidate_ids"])
                                                                   
        self.assertNotIn("j1", captured["candidate_ids"])

    def test_reconciler_by_format_breakdown(self):
        executor = MagicMock(
            return_value={"updated": 2, "failed": []},
        )
        report = vir.reconcile_vault_images(
            vault_id="v1", dry_run=False,
            rows=self._rows(), db_executor=executor,
        )
        self.assertEqual(
            report["by_detected_format"]["heic"], 1,
        )
        self.assertEqual(
            report["by_detected_format"]["tiff"], 1,
        )

    def test_reconciler_executor_failure_classes_surfaced(self):
        def _failing_exec(updates):
            return {
                "updated": 0,
                "failed": [
                    {"id": u["id"], "exception_class": "OperationalError"}
                    for u in updates
                ],
            }

        report = vir.reconcile_vault_images(
            vault_id="v1", dry_run=False,
            rows=self._rows(), db_executor=_failing_exec,
        )
        self.assertEqual(report["updated"], 0)
        self.assertEqual(report["failed"], 2)
        self.assertEqual(
            report["failure_classes"], ["OperationalError"],
        )

    def test_reconciler_idempotent_on_second_pass(self):
        first_executor = MagicMock(
            return_value={"updated": 2, "failed": []},
        )
        vir.reconcile_vault_images(
            vault_id="v1", dry_run=False,
            rows=self._rows(), db_executor=first_executor,
        )
                                                      
                             
        rows_after = [dict(r) for r in self._rows()]
        for r in rows_after:
            if r["id"] in ("h1", "t1"):
                r["asset_type"] = "image"
        second_executor = MagicMock()
        report2 = vir.reconcile_vault_images(
            vault_id="v1", dry_run=False,
            rows=rows_after, db_executor=second_executor,
        )
        self.assertEqual(report2["would_update"], 0)
        self.assertEqual(report2["updated"], 0)
        second_executor.assert_not_called()

    def test_reconciler_db_failure_returns_safe_report(self):
        with patch(
            "vault_image_reconciler._fetch_rows",
            side_effect=RuntimeError("simulated db crash"),
        ):
            report = vir.reconcile_vault_images(
                vault_id="v1", dry_run=True,
            )
        self.assertTrue(report["db_unavailable"])
        self.assertEqual(report["db_error_class"], "RuntimeError")

    def test_reconciler_never_leaks_filenames(self):
        rows = self._rows()
        rows[0]["saved_name"] = "BOB_SMITH_SECRET_ID.heic"
        rows[0]["file_name"] = "BOB_SMITH_SECRET_ID.heic"
        report = vir.reconcile_vault_images(
            vault_id="v1", dry_run=True,
            rows=rows, db_executor=MagicMock(),
        )
        self.assertNotIn(
            "BOB_SMITH_SECRET_ID", json.dumps(report),
        )


class TestOCRSupportsCentralClassifier(unittest.TestCase):


    def test_jpeg_supported(self):
        self.assertTrue(
            voa.supports_ocr(
                file_name="id.jpg", content_type="image/jpeg",
            )
        )

    def test_heic_supported(self):
        self.assertTrue(
            voa.supports_ocr(
                file_name="iphone.heic", content_type="image/heic",
            )
        )

    def test_heif_supported(self):
        self.assertTrue(
            voa.supports_ocr(
                file_name="x.heif", content_type="image/heif",
            )
        )

    def test_avif_supported(self):
        self.assertTrue(
            voa.supports_ocr(
                file_name="x.avif", content_type="image/avif",
            )
        )

    def test_webp_tiff_bmp_gif_supported(self):
        for name, mime in [
            ("a.webp", "image/webp"),
            ("a.tiff", "image/tiff"),
            ("a.tif",  "image/tiff"),
            ("a.bmp",  "image/bmp"),
            ("a.gif",  "image/gif"),
        ]:
            with self.subTest(name=name):
                self.assertTrue(
                    voa.supports_ocr(file_name=name, content_type=mime),
                )

    def test_octet_stream_with_heic_extension_supported(self):
        self.assertTrue(
            voa.supports_ocr(
                file_name="iphone.heic",
                content_type="application/octet-stream",
            )
        )

    def test_svg_NOT_supported_for_ocr(self):
                                                                  
                                                     
        self.assertFalse(
            voa.supports_ocr(
                file_name="logo.svg", content_type="image/svg+xml",
            )
        )

    def test_pdf_NOT_supported(self):
                                                    
        self.assertFalse(
            voa.supports_ocr(
                file_name="x.pdf", content_type="application/pdf",
            )
        )

    def test_text_NOT_supported(self):
        self.assertFalse(
            voa.supports_ocr(
                file_name="x.txt", content_type="text/plain",
            )
        )


class TestFindInVaultBroadCandidates(unittest.TestCase):


    def test_all_formats_become_vision_candidates(self):
        rows = [
            {"id": "jpg1", "content_type": "image/jpeg",
             "saved_name": "a.jpg", "asset_type": "image",
             "extracted_text": None},
            {"id": "png1", "content_type": "image/png",
             "saved_name": "b.png", "asset_type": "image",
             "extracted_text": None},
            {"id": "heic1", "content_type": "application/octet-stream",
             "saved_name": "iphone.heic", "asset_type": "file",
             "extracted_text": None},
            {"id": "heif1", "content_type": "image/heif",
             "saved_name": "c.heif", "asset_type": "file",
             "extracted_text": None},
            {"id": "webp1", "content_type": "image/webp",
             "saved_name": "d.webp", "asset_type": "image",
             "extracted_text": None},
            {"id": "tiff1", "content_type": "image/tiff",
             "saved_name": "e.tiff", "asset_type": "document",
             "extracted_text": None},
            {"id": "bmp1", "content_type": "image/bmp",
             "saved_name": "f.bmp", "asset_type": "file",
             "extracted_text": None},
            {"id": "gif1", "content_type": "image/gif",
             "saved_name": "g.gif", "asset_type": "image",
             "extracted_text": None},
            {"id": "avif1", "content_type": "image/avif",
             "saved_name": "h.avif", "asset_type": "file",
             "extracted_text": None},
        ]

        seen_file_ids: list[str] = []

        def _stub_vision(*, vault_id, key, file_id, question):
            seen_file_ids.append(file_id)
            return json.dumps({
                "analysis": (
                    "This is a driver license for Bob Test."
                ),
            })

        with patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ), patch(
            "vault_inspection_tools.read_image_with_vision",
            side_effect=_stub_vision,
        ):
            raw = vcs.find_in_vault(
                vault_id="v1", key=b"\x00" * 32,
                query="show me all ID photos in my vault",
            )
        out = json.loads(raw)
                                            
        self.assertEqual(set(seen_file_ids), {
            "jpg1", "png1", "heic1", "heif1", "webp1",
            "tiff1", "bmp1", "gif1", "avif1",
        })
                                
        self.assertTrue(out["complete"])


class _CapturedClient:


    def __init__(self):
        self.captured_data_url: Optional[str] = None
        outer = self

        class _CC:
            def create(_self, **kwargs):
                for m in kwargs.get("messages") or []:
                    for part in m.get("content") or []:
                        if part.get("type") == "image_url":
                            outer.captured_data_url = (
                                part["image_url"]["url"]
                            )

                class _Resp:
                    pass

                resp = _Resp()
                resp.choices = [type("C", (), {
                    "message": type("M", (), {
                        "content": "Test driver license. Name: X.",
                    })(),
                })()]
                return resp

        class _Chat:
            completions = _CC()

        self.chat = _Chat()


class TestReadImageWithVisionFailureContainment(unittest.TestCase):
    def setUp(self):
        self._client = _CapturedClient()
        self._patches = [
            patch("openai.OpenAI", return_value=self._client),
            patch(
                "vault_inspection_tools._resolve_vision_model",
                return_value="gpt-fake",
            ),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _run(self, raw_bytes, content_type, saved):
        from vault_inspection_tools import read_image_with_vision
        row = {
            "id": "f1", "content_type": content_type,
            "asset_type": "image",
            "saved_name": saved, "file_name": saved,
        }
        with patch(
            "vault_inspection_tools._fetch_file_row", return_value=row,
        ), patch(
            "vault_inspection_tools._decrypt_file_bytes",
            return_value=raw_bytes,
        ):
            return read_image_with_vision(
                vault_id="v1", key=b"\x00" * 32,
                file_id="f1",
                question="Is this an ID?",
            )

    def test_svg_returns_decode_band_unsupported(self):
        out = self._run(_svg(), "image/svg+xml", "art.svg")
        parsed = json.loads(out)
        self.assertEqual(parsed["error"], "unsupported_image")
        self.assertEqual(
            parsed["decode_band"], "unsupported_image_format",
        )

    def test_corrupt_image_returns_decode_band_corrupt(self):
                                     
        out = self._run(
            b"\xff\xd8\xff" + b"\x00" * 64,
            "image/jpeg", "broken.jpg",
        )
        parsed = json.loads(out)
                                                                  
                                                                      
        if "error" in parsed:
            self.assertEqual(parsed["error"], "unsupported_image")
            self.assertIn(
                parsed["decode_band"],
                (
                    vif.DECODE_BAND_CORRUPT,
                    vif.DECODE_BAND_DECODE_FAILED,
                    vif.DECODE_BAND_UNSUPPORTED_FORMAT,
                ),
            )

    def test_empty_bytes_does_not_crash(self):
                                              
        from vault_inspection_tools import read_image_with_vision
        row = {
            "id": "f1", "content_type": "image/heic",
            "asset_type": "image",
            "saved_name": "x.heic", "file_name": "x.heic",
        }
        with patch(
            "vault_inspection_tools._fetch_file_row", return_value=row,
        ), patch(
            "vault_inspection_tools._decrypt_file_bytes",
            return_value=b"",
        ):
            out = read_image_with_vision(
                vault_id="v1", key=b"\x00" * 32,
                file_id="f1",
                question="Is this an ID?",
            )
        parsed = json.loads(out)
                                                             
                      
        self.assertIn(parsed["error"], (
            "decrypt_failed", "unsupported_image",
        ))


class TestCentralClassifierIsAuthoritative(unittest.TestCase):


    def test_main_is_image_content_type_recognises_every_format(self):
        for mime, name in (
            ("image/jpeg", "a.jpg"),
            ("image/png", "a.png"),
            ("image/heic", "a.heic"),
            ("image/heif", "a.heif"),
            ("image/webp", "a.webp"),
            ("image/tiff", "a.tiff"),
            ("image/bmp", "a.bmp"),
            ("image/gif", "a.gif"),
            ("image/avif", "a.avif"),
            ("image/svg+xml", "a.svg"),
        ):
            with self.subTest(mime=mime):
                self.assertTrue(
                    main._is_image_content_type(mime, name),
                )

    def test_vault_complete_search_row_subkind_classifies_all(self):
        for mime, name in (
            ("image/heic", "iphone.heic"),
            ("image/heif", "x.heif"),
            ("image/avif", "x.avif"),
            ("image/svg+xml", "logo.svg"),
            ("image/webp", "x.webp"),
        ):
            with self.subTest(mime=mime):
                row = {
                    "id": "r", "content_type": mime,
                    "saved_name": name, "asset_type": "file",
                }
                self.assertEqual(
                    vcs._row_subkind(row), "image",
                )

    def test_default_asset_type_for_upload_handles_octet_stream(self):
        for name in (
            "ID.HEIC", "scan.tiff", "license.webp",
            "old.bmp", "modern.avif", "photo.heif",
            "art.svg", "x.gif",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    main._default_asset_type_for_upload(
                        name, "application/octet-stream", None,
                    ),
                    "image",
                )


if __name__ == "__main__":                    
    unittest.main()
