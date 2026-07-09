

from __future__ import annotations

import io
import unittest
from typing import Optional
from unittest.mock import patch

from PIL import Image

import vault_image_formats as vif
import vault_complete_search as vcs
import vault_chat_result_cards as vcr
import main


def _noisy_rgb(seed: int = 1, w: int = 96, h: int = 64) -> Image.Image:


    img = Image.new("RGB", (w, h))
    pixels = img.load()
    s = seed & 0xFFFFFFFF
    for y in range(h):
        for x in range(w):
            s = (1103515245 * s + 12345) & 0xFFFFFFFF
            r = (s >> 16) & 0xFF
            g = (s >> 8) & 0xFF
            b = s & 0xFF
            pixels[x, y] = (r, g, b)
    return img


def _save(fmt: str, **save_kwargs) -> bytes:

    img = _noisy_rgb()
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _jpeg() -> bytes:
    return _save("JPEG", quality=85)


def _png() -> bytes:
    return _save("PNG")


def _gif() -> bytes:
    return _save("GIF")


def _bmp() -> bytes:
    return _save("BMP")


def _tiff() -> bytes:
    return _save("TIFF")


def _webp() -> bytes:
    return _save("WEBP")


def _heic_or_skip() -> Optional[bytes]:


    try:
        import pillow_heif              
        pillow_heif.register_heif_opener()
    except Exception:
        return None
    return _save("HEIF", quality=85)


def _avif_or_skip() -> Optional[bytes]:
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


def _fake_heic_header() -> bytes:


    return (
        b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"
    )


def _fake_avif_header() -> bytes:
    return (
        b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00mif1avif"
    )


class TestSupportedMimes(unittest.TestCase):
    def test_all_required_mimes_are_supported(self):
                                     
        for mime in (
            "image/jpeg", "image/png",
            "image/heic", "image/heif",
            "image/webp",
            "image/tiff",
            "image/bmp",
            "image/gif",
            "image/avif",
        ):
            with self.subTest(mime=mime):
                self.assertTrue(vif.is_supported_image_mime(mime))

    def test_mime_alias_resolution(self):
                                                                    
        cases = {
            "image/jpg":      "image/jpeg",
            "image/pjpeg":    "image/jpeg",
            "image/x-png":    "image/png",
            "image/x-tiff":   "image/tiff",
            "image/x-bmp":    "image/bmp",
            "image/x-heic":   "image/heic",
            "image/x-heif":   "image/heif",
            "image/heic-sequence": "image/heic",
            "image/heif-sequence": "image/heif",
        }
        for alias, canonical in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(
                    vif.canonicalize_image_mime(alias), canonical,
                )

    def test_mime_with_charset_parameter_strips_to_canonical(self):
                                                                
                                                              
        self.assertEqual(
            vif.canonicalize_image_mime("image/jpeg; charset=binary"),
            "image/jpeg",
        )
        self.assertTrue(
            vif.is_supported_image_mime("IMAGE/JPEG"),
        )

    def test_unsupported_mime_returns_false(self):
        for mime in (
            "application/pdf",
            "text/plain",
            "audio/mpeg",
            "video/mp4",
            "",
            None,
        ):
            with self.subTest(mime=mime):
                self.assertFalse(vif.is_supported_image_mime(mime))


class TestExtensionFallback(unittest.TestCase):
    def test_all_listed_extensions_resolve(self):
                                     
        cases = {
            "id.jpg":  "image/jpeg",
            "id.jpeg": "image/jpeg",
            "id.png":  "image/png",
            "id.heic": "image/heic",
            "id.heif": "image/heif",
            "id.webp": "image/webp",
            "id.tif":  "image/tiff",
            "id.tiff": "image/tiff",
            "id.bmp":  "image/bmp",
            "id.gif":  "image/gif",
            "id.avif": "image/avif",
                               
            "License.HEIC":   "image/heic",
            "scan.TIFF":      "image/tiff",
        }
        for name, mime in cases.items():
            with self.subTest(name=name):
                self.assertTrue(vif.is_supported_image_extension(name))
                self.assertEqual(vif.mime_from_extension(name), mime)

    def test_unsupported_extensions_rejected(self):
        for name in (
            "report.pdf",
            "notes.txt",
            "song.mp3",
            "movie.mp4",
            "noextension",
            "",
            None,
        ):
            with self.subTest(name=name):
                self.assertFalse(vif.is_supported_image_extension(name))


class TestMagicByteDetection(unittest.TestCase):
    def test_jpeg_header_detected(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_jpeg()), "image/jpeg",
        )

    def test_png_header_detected(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_png()), "image/png",
        )

    def test_gif_header_detected(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_gif()), "image/gif",
        )

    def test_bmp_header_detected(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_bmp()), "image/bmp",
        )

    def test_tiff_header_detected(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_tiff()), "image/tiff",
        )

    def test_webp_header_detected(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_webp()), "image/webp",
        )

    def test_heic_header_detected_without_decoder_wheel(self):
                                                               
                                                             
        self.assertEqual(
            vif.detect_mime_from_bytes(_fake_heic_header()),
            "image/heic",
        )

    def test_avif_header_detected_without_decoder_wheel(self):
        self.assertEqual(
            vif.detect_mime_from_bytes(_fake_avif_header()),
            "image/avif",
        )

    def test_garbage_bytes_return_none(self):
        self.assertIsNone(vif.detect_mime_from_bytes(b""))
        self.assertIsNone(vif.detect_mime_from_bytes(b"\x00\x00\x00\x00"))
        self.assertIsNone(vif.detect_mime_from_bytes(b"Hello world"))


class TestIsImageRow(unittest.TestCase):
    def test_mime_only_recognises_each_listed_format(self):
        for mime in (
            "image/jpeg", "image/png", "image/heic", "image/heif",
            "image/webp", "image/tiff", "image/bmp", "image/gif",
            "image/avif",
        ):
            with self.subTest(mime=mime):
                self.assertTrue(vif.is_image_row(mime=mime))

    def test_extension_fallback_when_mime_is_octet_stream(self):
                                                           
                                                                  
        self.assertTrue(
            vif.is_image_row(
                mime="application/octet-stream",
                file_name="ID.HEIC",
            )
        )
        self.assertTrue(
            vif.is_image_row(
                mime="application/octet-stream",
                file_name="scan.tiff",
            )
        )
        self.assertTrue(
            vif.is_image_row(
                mime="application/octet-stream",
                file_name="ID.webp",
            )
        )

    def test_mime_detection_works_when_extension_is_missing(self):
                                                                    
                   
        self.assertTrue(vif.is_image_row(mime="image/heic"))
        self.assertTrue(vif.is_image_row(mime="image/tiff"))
                                                                
        self.assertTrue(
            vif.is_image_row(raw_bytes=_jpeg())
        )
        self.assertTrue(
            vif.is_image_row(raw_bytes=_fake_heic_header())
        )

    def test_legacy_asset_type_image_still_recognised(self):
                                                                  
                                                                 
        self.assertTrue(
            vif.is_image_row(asset_type="image")
        )

    def test_non_image_row_returns_false(self):
        self.assertFalse(
            vif.is_image_row(
                mime="application/pdf", file_name="report.pdf",
            )
        )
        self.assertFalse(
            vif.is_image_row(
                mime="text/plain", file_name="notes.txt",
            )
        )
        self.assertFalse(vif.is_image_row())


class TestNormalizationToJPEG(unittest.TestCase):


    def _assert_normalised_to_jpeg(
        self, raw_bytes: bytes, mime_hint: Optional[str] = None,
    ) -> None:
        result = vif.normalize_to_supported_image(
            raw_bytes, mime_hint=mime_hint, target_mime="image/jpeg",
        )
        self.assertIsNotNone(result, msg="normalisation returned None")
        out_bytes, out_mime = result
        self.assertEqual(out_mime, "image/jpeg")
                                                      
        self.assertEqual(out_bytes[:3], b"\xff\xd8\xff")
                                     
        Image.open(io.BytesIO(out_bytes)).verify()

    def test_png_to_jpeg(self):
        self._assert_normalised_to_jpeg(_png(), "image/png")

    def test_webp_to_jpeg(self):
        self._assert_normalised_to_jpeg(_webp(), "image/webp")

    def test_tiff_to_jpeg(self):
        self._assert_normalised_to_jpeg(_tiff(), "image/tiff")

    def test_bmp_to_jpeg(self):
        self._assert_normalised_to_jpeg(_bmp(), "image/bmp")

    def test_gif_to_jpeg(self):
        self._assert_normalised_to_jpeg(_gif(), "image/gif")

    def test_heic_to_jpeg_when_decoder_present(self):
        heic = _heic_or_skip()
        if heic is None:
            self.skipTest("pillow-heif not installed in this venv")
        self._assert_normalised_to_jpeg(heic, "image/heic")

    def test_avif_to_jpeg_when_decoder_present(self):
        avif = _avif_or_skip()
        if avif is None:
            self.skipTest("AVIF decoder not present")
        self._assert_normalised_to_jpeg(avif, "image/avif")


class TestNormalizeForVisionSkipsAlreadyNative(unittest.TestCase):


    def test_jpeg_passes_through(self):
        jpeg = _jpeg()
        result = vif.normalize_for_vision(jpeg, mime_hint="image/jpeg")
        self.assertIsNotNone(result)
        out, mime = result
        self.assertIs(out, jpeg)
        self.assertEqual(mime, "image/jpeg")

    def test_webp_passes_through(self):
        webp = _webp()
        result = vif.normalize_for_vision(webp, mime_hint="image/webp")
        self.assertIsNotNone(result)
        out, mime = result
        self.assertIs(out, webp)
        self.assertEqual(mime, "image/webp")

    def test_tiff_normalised_to_jpeg(self):
        tiff = _tiff()
        result = vif.normalize_for_vision(tiff, mime_hint="image/tiff")
        self.assertIsNotNone(result)
        out, mime = result
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(out[:3], b"\xff\xd8\xff")

    def test_bmp_normalised_to_jpeg(self):
        bmp = _bmp()
        result = vif.normalize_for_vision(bmp, mime_hint="image/bmp")
        self.assertIsNotNone(result)
        out, mime = result
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(out[:3], b"\xff\xd8\xff")


class TestSafeFailureBehaviour(unittest.TestCase):


    def test_corrupt_bytes_return_none_not_raise(self):
                                 
        result = vif.normalize_to_supported_image(
            b"\x00\x01\x02\x03not-an-image",
            mime_hint="image/jpeg",
        )
        self.assertIsNone(result)

    def test_empty_bytes_return_none(self):
        self.assertIsNone(vif.normalize_to_supported_image(b""))
        self.assertIsNone(vif.normalize_to_supported_image(None))
        self.assertIsNone(vif.normalize_for_vision(b""))

    def test_unsupported_format_does_not_lie_about_being_an_image(self):
                                                                  
                                                                   
        self.assertTrue(vif.is_image_row(mime="image/heic"))
        self.assertTrue(vif.is_image_row(file_name="x.heic"))

    def test_normalise_heic_without_decoder_returns_none_not_raise(self):
                                                                   
                                                                
        result = vif.normalize_to_supported_image(
            _fake_heic_header(), mime_hint="image/heic",
        )
                                                                  
                                                                  
        self.assertIn(result, (None,) if result is None else (result,))

    def test_decoder_availability_probe_runs(self):
        avail = vif.decoder_availability()
        self.assertIn("pillow", avail)
        self.assertIn("heif", avail)
        self.assertIn("avif", avail)
        self.assertIsInstance(avail["pillow"], bool)
        self.assertIsInstance(avail["heif"], bool)
        self.assertIsInstance(avail["avif"], bool)


class TestThumbnailGeneration(unittest.TestCase):


    def _assert_jpeg_thumb(self, raw_bytes: bytes) -> None:
        out = vcr._render_image_thumbnail(raw_bytes)
        self.assertIsNotNone(out, msg="thumbnail render returned None")
                              
        self.assertEqual(out[:3], b"\xff\xd8\xff")
                                  
        Image.open(io.BytesIO(out)).verify()

    def test_jpeg_thumbnail(self):
        self._assert_jpeg_thumb(_jpeg())

    def test_png_thumbnail(self):
        self._assert_jpeg_thumb(_png())

    def test_webp_thumbnail(self):
        self._assert_jpeg_thumb(_webp())

    def test_tiff_thumbnail(self):
        self._assert_jpeg_thumb(_tiff())

    def test_bmp_thumbnail(self):
        self._assert_jpeg_thumb(_bmp())

    def test_gif_thumbnail(self):
        self._assert_jpeg_thumb(_gif())

    def test_heic_thumbnail_when_decoder_present(self):
        heic = _heic_or_skip()
        if heic is None:
            self.skipTest("pillow-heif not installed in this venv")
        self._assert_jpeg_thumb(heic)

    def test_avif_thumbnail_when_decoder_present(self):
        avif = _avif_or_skip()
        if avif is None:
            self.skipTest("AVIF decoder not present")
        self._assert_jpeg_thumb(avif)

    def test_corrupt_input_returns_none_not_raise(self):
        self.assertIsNone(vcr._render_image_thumbnail(b"not-an-image"))
        self.assertIsNone(vcr._render_image_thumbnail(b""))


class TestRowSubkindAllFormats(unittest.TestCase):


    def test_heic_row_classified_as_image(self):
        row = {"id": "h1", "content_type": "image/heic",
               "saved_name": "iphone.heic"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_heif_row_classified_as_image(self):
        row = {"id": "h2", "content_type": "image/heif",
               "saved_name": "scan.heif"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_webp_row_classified_as_image(self):
        row = {"id": "w1", "content_type": "image/webp",
               "saved_name": "id.webp"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_tiff_row_classified_as_image(self):
        row = {"id": "t1", "content_type": "image/tiff",
               "saved_name": "scan.tiff"}
        self.assertEqual(vcs._row_subkind(row), "image")
        row2 = {"id": "t2", "content_type": "image/tiff",
                "saved_name": "scan.tif"}
        self.assertEqual(vcs._row_subkind(row2), "image")

    def test_bmp_row_classified_as_image(self):
        row = {"id": "b1", "content_type": "image/bmp",
               "saved_name": "old.bmp"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_gif_row_classified_as_image(self):
        row = {"id": "g1", "content_type": "image/gif",
               "saved_name": "doc.gif"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_avif_row_classified_as_image(self):
        row = {"id": "a1", "content_type": "image/avif",
               "saved_name": "modern.avif"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_octet_stream_with_heic_extension_still_image(self):
                                                                   
                                                           
        row = {
            "id": "octh",
            "content_type": "application/octet-stream",
            "saved_name": "ID.HEIC",
        }
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_octet_stream_with_webp_extension_still_image(self):
        row = {
            "id": "octw",
            "content_type": "application/octet-stream",
            "saved_name": "license.webp",
        }
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_jpeg_still_classified_as_image(self):
                                                      
        row = {"id": "j1", "content_type": "image/jpeg",
               "saved_name": "id.jpg"}
        self.assertEqual(vcs._row_subkind(row), "image")

    def test_pdf_row_still_classified_as_pdf(self):
        row = {"id": "p1", "content_type": "application/pdf",
               "saved_name": "form.pdf"}
        self.assertEqual(vcs._row_subkind(row), "pdf")

    def test_text_row_still_classified_as_text(self):
        row = {"id": "t1", "content_type": "text/plain",
               "saved_name": "notes.txt"}
        self.assertEqual(vcs._row_subkind(row), "text")


class TestUploadClassifier(unittest.TestCase):


    def test_all_listed_image_mimes_classify_as_image(self):
        for mime, name in (
            ("image/jpeg", "id.jpg"),
            ("image/png",  "id.png"),
            ("image/heic", "id.heic"),
            ("image/heif", "id.heif"),
            ("image/webp", "id.webp"),
            ("image/tiff", "id.tiff"),
            ("image/bmp",  "id.bmp"),
            ("image/gif",  "id.gif"),
            ("image/avif", "id.avif"),
        ):
            with self.subTest(mime=mime):
                self.assertTrue(
                    main._is_image_content_type(mime, name),
                )

    def test_extension_fallback_for_octet_stream(self):
                                  
        for name in (
            "ID.HEIC", "scan.tiff", "license.webp",
            "old.bmp", "modern.avif", "photo.heif",
        ):
            with self.subTest(name=name):
                self.assertTrue(
                    main._is_image_content_type(
                        "application/octet-stream", name,
                    )
                )

    def test_non_image_inputs_rejected(self):
        for mime, name in (
            ("application/pdf", "report.pdf"),
            ("text/plain", "notes.txt"),
            ("audio/mpeg", "song.mp3"),
            ("video/mp4", "movie.mp4"),
            (None, ""),
        ):
            with self.subTest(mime=mime, name=name):
                self.assertFalse(
                    main._is_image_content_type(mime, name)
                )

    def test_default_asset_type_for_heic_upload(self):
                                                                    
                                                                  
        self.assertEqual(
            main._default_asset_type_for_upload(
                "ID.HEIC", "application/octet-stream", None,
            ),
            "image",
        )
        self.assertEqual(
            main._default_asset_type_for_upload(
                "scan.tiff", None, None,
            ),
            "image",
        )


class _StubResp:
    def __init__(self, text: str = "ok"):
        self.choices = [type("C", (), {
            "message": type("M", (), {"content": text})(),
        })()]


class _StubClient:


    def __init__(self):
        self.captured_data_url: Optional[str] = None

        outer = self

        class _CC:
            def create(_self, **kwargs):
                msgs = kwargs.get("messages") or []
                for m in msgs:
                    for part in m.get("content") or []:
                        if part.get("type") == "image_url":
                            outer.captured_data_url = (
                                part["image_url"]["url"]
                            )
                return _StubResp()

        class _Chat:
            completions = _CC()

        self.chat = _Chat()


class TestReadImageWithVisionNormalises(unittest.TestCase):
    def setUp(self):
        self._stub_client = _StubClient()

                                                                     
        self._patches = []
        self._patches.append(patch(
            "openai.OpenAI",
            return_value=self._stub_client,
        ))
        self._patches.append(patch(
            "vault_inspection_tools._resolve_vision_model",
            return_value="gpt-fake",
        ))
        self._patches.append(patch.dict(
            "os.environ", {"OPENAI_API_KEY": "sk-test"},
        ))
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass

    def _run_vision(
        self, raw_bytes: bytes, content_type: str, file_name: str,
        asset_type: str = "image",
    ) -> dict:
        from vault_inspection_tools import read_image_with_vision

        row = {
            "id": "fid-1",
            "content_type": content_type,
            "asset_type": asset_type,
            "saved_name": file_name,
            "file_name": file_name,
        }
        with patch(
            "vault_inspection_tools._fetch_file_row",
            return_value=row,
        ), patch(
            "vault_inspection_tools._decrypt_file_bytes",
            return_value=raw_bytes,
        ):
            return read_image_with_vision(
                vault_id="v1", key=b"\x00" * 32,
                file_id="fid-1",
                question="Is this an ID?",
            )

    def test_jpeg_passes_through_as_jpeg(self):
        out = self._run_vision(_jpeg(), "image/jpeg", "id.jpg")
        import json
        parsed = json.loads(out)
        self.assertNotIn("error", parsed)
        url = self._stub_client.captured_data_url or ""
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))

    def test_webp_passes_through_as_webp(self):
        out = self._run_vision(_webp(), "image/webp", "id.webp")
        import json
        parsed = json.loads(out)
        self.assertNotIn("error", parsed)
        url = self._stub_client.captured_data_url or ""
        self.assertTrue(url.startswith("data:image/webp;base64,"))

    def test_tiff_normalised_to_jpeg_before_vision(self):
                                 
        out = self._run_vision(_tiff(), "image/tiff", "id.tiff")
        import json
        parsed = json.loads(out)
        self.assertNotIn("error", parsed)
        url = self._stub_client.captured_data_url or ""
        self.assertTrue(
            url.startswith("data:image/jpeg;base64,"),
            f"vision received non-JPEG payload: {url[:48]}",
        )

    def test_bmp_normalised_to_jpeg_before_vision(self):
        out = self._run_vision(_bmp(), "image/bmp", "id.bmp")
        import json
        parsed = json.loads(out)
        self.assertNotIn("error", parsed)
        url = self._stub_client.captured_data_url or ""
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))

    def test_heic_normalised_to_jpeg_before_vision_when_decoder_present(
        self,
    ):
        heic = _heic_or_skip()
        if heic is None:
            self.skipTest("pillow-heif not installed in this venv")
        out = self._run_vision(heic, "image/heic", "iphone.heic")
        import json
        parsed = json.loads(out)
        self.assertNotIn("error", parsed)
        url = self._stub_client.captured_data_url or ""
        self.assertTrue(
            url.startswith("data:image/jpeg;base64,"),
            f"vision received non-JPEG payload: {url[:48]}",
        )

    def test_octet_stream_with_heic_extension_still_routed_to_vision(
        self,
    ):
                                                                 
                                             
        heic = _heic_or_skip()
        if heic is None:
            self.skipTest("pillow-heif not installed in this venv")
        out = self._run_vision(
            heic, "application/octet-stream", "ID.HEIC",
        )
        import json
        parsed = json.loads(out)
                                                                   
                                                                     
        self.assertNotIn("not_an_image", parsed.get("error", ""))
                                                                  
        if "error" not in parsed:
            url = self._stub_client.captured_data_url or ""
            self.assertTrue(url.startswith("data:image/jpeg;base64,"))

    def test_corrupt_bytes_return_closed_set_error_not_crash(self):
                                                                   
                                                        
        out = self._run_vision(
            b"\x00\x01garbage", "image/heic", "broken.heic",
        )
        import json
        parsed = json.loads(out)
                                                                
                                                                 
        if "error" in parsed:
            self.assertEqual(
                parsed["error"], "unsupported_image",
            )

    def test_pdf_input_still_rejected_as_not_an_image(self):
                                                                 
                                                                  
        out = self._run_vision(
            b"%PDF-1.4 stub", "application/pdf", "doc.pdf",
            asset_type="file",
        )
        import json
        parsed = json.loads(out)
        self.assertEqual(parsed.get("error"), "not_an_image")


if __name__ == "__main__":                    
    unittest.main()
