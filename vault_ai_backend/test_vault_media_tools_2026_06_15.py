

from __future__ import annotations

import json
import unittest
from unittest import mock

import vault_inspection_tools as vit


_KEY = b"\x77" * 32


def _row(
    file_id="f1", vault_id="v1",
    file_name="report.pdf", saved_name="report.pdf",
    relative_path="/Files/",
    content_type="application/pdf",
    asset_type="document", file_size=1024,
    extracted_text="ENC", extracted_text_encrypted=True,
    extracted_text_source="worker",
    extracted_text_status="available",
    encrypted_file_data=None,
    analysis_status="ready",
):
    return {
        "id":                       file_id,
        "vault_id":                 vault_id,
        "file_name":                file_name,
        "saved_name":               saved_name,
        "relative_path":            relative_path,
        "content_type":             content_type,
        "asset_type":               asset_type,
        "file_size":                file_size,
        "created_at":               None,
        "detected_type":            None,
        "detected_service":         None,
        "upload_status":            "complete",
        "analysis_status":          analysis_status,
        "encrypted_file_data":      encrypted_file_data,
        "extracted_text":           extracted_text,
        "extracted_text_encrypted": extracted_text_encrypted,
        "extracted_text_source":   extracted_text_source,
        "extracted_text_status":   extracted_text_status,
    }


class ReadMediaTranscriptHappyPaths(unittest.TestCase):
    def test_audio_transcript_returned_with_source(self):
        row = _row(
            asset_type="audio",
            content_type="audio/mpeg",
            extracted_text_source="transcript",
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value="The meeting started at 9 AM.",
        ):
            out = vit.read_media_transcript(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload["asset_type"], "audio")
        self.assertIn("9 AM", payload["transcript"])
        self.assertEqual(payload["transcript_source"], "transcript")

    def test_video_transcript_returned_with_source(self):
        row = _row(
            asset_type="video",
            content_type="video/mp4",
            extracted_text_source="transcript",
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value="Welcome to my walkthrough.",
        ):
            out = vit.read_media_transcript(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload["asset_type"], "video")
        self.assertIn("walkthrough", payload["transcript"])


class ReadMediaTranscriptRouting(unittest.TestCase):
    def test_rejects_document_with_hint_to_read_file_text(self):
        row = _row(asset_type="document",
                   content_type="application/pdf")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_media_transcript(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "not_media")
        self.assertIn("read_file_text", payload.get("hint", ""))

    def test_rejects_image_with_hint_to_use_vision(self):
        row = _row(asset_type="image",
                   content_type="image/png")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_media_transcript(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "not_media")
        self.assertIn(
            "read_image_with_vision",
            payload.get("hint", ""),
        )

    def test_requires_unlocked_vault(self):
        out = vit.read_media_transcript(
            vault_id="v1", key=b"short", file_id="f1",
        )
        self.assertEqual(
            json.loads(out).get("error"), "vault_locked",
        )


class TranscriptNotReady(unittest.TestCase):
    def test_returns_transcript_not_ready_error(self):
        row = _row(
            asset_type="video",
            content_type="video/mp4",
            extracted_text=None,
            extracted_text_encrypted=False,
            extracted_text_status="not_available",
            analysis_status="processing",
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_media_transcript(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(
            payload.get("error"), "transcript_not_ready",
        )
                                                           
        self.assertEqual(payload["analysis_status"], "processing")
        self.assertEqual(
            payload["extracted_text_status"], "not_available",
        )


class ReadFileTextExposesProvenance(unittest.TestCase):
    def test_response_includes_extracted_text_source_and_status(self):
        row = _row(
            extracted_text_source="ocr",
            extracted_text_status="available",
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value="OCR'd receipt text.",
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(
            payload["extracted_text_source"], "ocr",
        )
        self.assertEqual(
            payload["extracted_text_status"], "available",
        )

    def test_image_no_text_hint_routes_to_vision(self):
        row = _row(
            asset_type="image",
            content_type="image/png",
            extracted_text=None,
            extracted_text_encrypted=False,
            extracted_text_status="not_available",
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "no_text")
        self.assertIn(
            "read_image_with_vision", payload.get("hint", ""),
        )

    def test_video_no_text_hint_mentions_transcription(self):
        row = _row(
            asset_type="video",
            content_type="video/mp4",
            extracted_text=None,
            extracted_text_encrypted=False,
            extracted_text_status="not_available",
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "no_text")
        self.assertIn(
            "transcrib", payload.get("hint", "").lower(),
        )


class ListFileChunksTests(unittest.TestCase):
    def test_lists_chunks_for_file(self):
        row = _row(asset_type="video")
        fake_cur = mock.MagicMock()
        fake_cur.fetchall.return_value = [
            {
                "chunk_index": 0,
                "extraction_source": "video_transcript",
                "char_start": 0, "char_end": 240,
                "char_length": 240,
            },
            {
                "chunk_index": 1,
                "extraction_source": "video_transcript",
                "char_start": 240, "char_end": 480,
                "char_length": 240,
            },
        ]
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch("main.get_db", return_value=fake_conn):
            out = vit.list_file_chunks(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload["chunk_count"], 2)
        self.assertEqual(payload["asset_type"], "video")
                                 
        self.assertEqual(
            payload["chunks"][0]["extraction_source"],
            "video_transcript",
        )

    def test_extraction_source_filter_threads_into_sql(self):
        row = _row(asset_type="video")
        fake_cur = mock.MagicMock()
        fake_cur.fetchall.return_value = []
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch("main.get_db", return_value=fake_conn):
            out = vit.list_file_chunks(
                vault_id="v1", key=_KEY, file_id="f1",
                extraction_source="VIDEO_TRANSCRIPT",
            )
        payload = json.loads(out)
                                          
        self.assertEqual(
            payload["filter"]["extraction_source"],
            "video_transcript",
        )

    def test_unknown_file_returns_not_found(self):
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=None,
        ):
            out = vit.list_file_chunks(
                vault_id="v1", key=_KEY, file_id="f-missing",
            )
        self.assertEqual(json.loads(out).get("error"), "not_found")


class ReadFileChunkTests(unittest.TestCase):
    def test_happy_path_decrypts_and_redacts(self):
        row = _row(asset_type="video")
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {
            "chunk_index": 1,
            "encrypted_chunk_text": "ENC_BLOB",
            "extraction_source": "video_transcript",
            "char_start": 240, "char_end": 480,
            "char_length": 240,
        }
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "main.get_db", return_value=fake_conn,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value="Segment 2 text. password: hunter2",
        ):
            out = vit.read_file_chunk(
                vault_id="v1", key=_KEY,
                file_id="f1", chunk_index=1,
            )
        payload = json.loads(out)
        self.assertEqual(payload["chunk_index"], 1)
        self.assertEqual(
            payload["extraction_source"], "video_transcript",
        )
                                         
        self.assertNotIn("hunter2", payload["text"])

    def test_chunk_not_found_returns_error(self):
        row = _row()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = None
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch("main.get_db", return_value=fake_conn):
            out = vit.read_file_chunk(
                vault_id="v1", key=_KEY,
                file_id="f1", chunk_index=99,
            )
        self.assertEqual(
            json.loads(out).get("error"), "chunk_not_found",
        )

    def test_short_key_refused(self):
        out = vit.read_file_chunk(
            vault_id="v1", key=b"short",
            file_id="f1", chunk_index=0,
        )
        self.assertEqual(
            json.loads(out).get("error"), "vault_locked",
        )

    def test_decrypt_failure_returns_decrypt_failed(self):
        row = _row()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {
            "chunk_index": 0,
            "encrypted_chunk_text": "ENC",
            "extraction_source": "pdf_text",
            "char_start": 0, "char_end": 100,
            "char_length": 100,
        }
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "main.get_db", return_value=fake_conn,
        ), mock.patch(
            "vault_core.decrypt_message",
            side_effect=RuntimeError("bad key"),
        ):
            out = vit.read_file_chunk(
                vault_id="v1", key=_KEY,
                file_id="f1", chunk_index=0,
            )
        self.assertEqual(
            json.loads(out).get("error"), "decrypt_failed",
        )


class DispatchWiringTests(unittest.TestCase):
    _NEW_TOOLS = (
        "read_media_transcript",
        "list_file_chunks",
        "read_file_chunk",
    )

    def test_inspection_dispatch_has_new_tools(self):
        for name in self._NEW_TOOLS:
            self.assertIn(name, vit.INSPECTION_DISPATCH)

    def test_inspection_functions_schema_has_new_tools(self):
        names = [
            f["function"]["name"] for f in vit.INSPECTION_FUNCTIONS
        ]
        for n in self._NEW_TOOLS:
            self.assertIn(n, names)

    def test_vault_knowledge_dispatch_merges_new_tools(self):
        from vault_knowledge_tools import VAULT_KNOWLEDGE_DISPATCH
        for n in self._NEW_TOOLS:
            self.assertIn(n, VAULT_KNOWLEDGE_DISPATCH)


class SystemPromptDirectsByFileKind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("tools.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_prompt_documents_picture_routing(self):
        self.assertIn("PICTURE", self._src)
        self.assertIn("read_image_with_vision", self._src)

    def test_prompt_documents_video_audio_routing(self):
        self.assertIn("VIDEO / AUDIO", self._src)
        self.assertIn("read_media_transcript", self._src)

    def test_prompt_documents_pdf_routing(self):
        self.assertIn("PDF", self._src)
                                                               
        self.assertIn("list_file_chunks", self._src)
        self.assertIn("read_file_chunk", self._src)

    def test_prompt_warns_about_video_frame_limitation(self):
                                                                 
                                         
        self.assertIn("Video frame extraction", self._src)
        self.assertIn("NOT available", self._src)

    def test_prompt_documents_provenance_field(self):
                                                             
                                    
        self.assertIn("extracted_text_source", self._src)
        for value in ("upload", "worker", "ocr", "transcript"):
            with self.subTest(value=value):
                self.assertIn(value, self._src)


if __name__ == "__main__":
    unittest.main()
