

from __future__ import annotations

import inspect
import unittest
from unittest import mock

from fastapi import HTTPException

from routes import file_text_routes as ft


class _FakeCursor:
    def __init__(self, row=None) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, tuple(params)))

    def fetchone(self):
        return self.row

    def close(self):
        pass


class _FakeConn:
    def __init__(self, row=None) -> None:
        self._cur = _FakeCursor(row=row)

    def cursor(self, *a, **kw):
        return self._cur

    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


def _patch_db(row):
    conn = _FakeConn(row=row)
    return mock.patch("vault_core.get_db", return_value=conn), conn


class LoadExtractedTextTests(unittest.TestCase):
    def test_returns_analyzed_text_when_present(self) -> None:
        encrypted = "ENCRYPTED_BLOB"
        row = (
            "file-abc", "agreement.pdf", "application/pdf",
            "analyzed", encrypted, None,
        )
        p, _ = _patch_db(row)
        with p, mock.patch(
            "vault_core.decrypt_message",
            return_value="The agreement is signed on 2026-05-15.",
        ):
            out = ft.load_extracted_text(
                vault_id="v1", file_id="file-abc", key=b"K" * 32,
            )
        self.assertEqual(out["text"], "The agreement is signed on 2026-05-15.")
        self.assertEqual(out["analysis_status"], "analyzed")
        self.assertFalse(out["truncated"])
        self.assertIsNone(out["note"])
        self.assertEqual(out["file_name"], "agreement.pdf")
        self.assertEqual(out["content_type"], "application/pdf")

    def test_wrong_vault_or_missing_file_returns_404(self) -> None:
        p, _ = _patch_db(None)                          
        with p:
            with self.assertRaises(HTTPException) as cm:
                ft.load_extracted_text(
                    vault_id="vA", file_id="file-not-mine", key=b"K" * 32,
                )
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(
            cm.exception.detail,
            {"code": "file_not_found", "file_id": "file-not-mine"},
        )

    def test_sql_scopes_by_vault_id(self) -> None:
        row = (
            "file-x", "x.pdf", "application/pdf", "analyzed",
            "BLOB", None,
        )
        p, conn = _patch_db(row)
        with p, mock.patch(
            "vault_core.decrypt_message", return_value="hi",
        ):
            ft.load_extracted_text(
                vault_id="v-target", file_id="file-x", key=b"K" * 32,
            )
        sql, params = conn._cur.executed[0]
        self.assertIn("WHERE id = %s AND vault_id = %s", sql)
        self.assertEqual(params, ("file-x", "v-target"))

    def test_select_does_not_pull_encrypted_file_data(self) -> None:
                                                          
                                                                   
        src = inspect.getsource(ft.load_extracted_text)
        self.assertNotIn("encrypted_file_data", src)
        self.assertIn("extracted_text", src)

    def test_not_yet_analyzed_returns_null_text_and_note(self) -> None:
        row = (
            "file-x", "x.pdf", "application/pdf", "pending",
            None, None,
        )
        p, _ = _patch_db(row)
        with p:
            out = ft.load_extracted_text(
                vault_id="v1", file_id="file-x", key=b"K" * 32,
            )
        self.assertIsNone(out["text"])
        self.assertEqual(out["note"], "file_not_yet_analyzed")
        self.assertEqual(out["analysis_status"], "pending")

    def test_analyzed_but_no_text_returns_empty_string_and_note(self) -> None:
                                                        
        row = (
            "file-x", "scan.pdf", "application/pdf", "analyzed",
            "", None,
        )
        p, _ = _patch_db(row)
        with p:
            out = ft.load_extracted_text(
                vault_id="v1", file_id="file-x", key=b"K" * 32,
            )
        self.assertEqual(out["text"], "")
        self.assertEqual(out["note"], "analyzed_but_no_text")

    def test_decrypt_failure_raises_500_does_not_log_blob(self) -> None:
        row = (
            "file-x", "x.pdf", "application/pdf", "analyzed",
            "BLOB", None,
        )
        p, _ = _patch_db(row)
        with p, mock.patch(
            "vault_core.decrypt_message",
            side_effect=RuntimeError("AES tag verify failed"),
        ):
            with self.assertRaises(HTTPException) as cm:
                ft.load_extracted_text(
                    vault_id="v1", file_id="file-x", key=b"WRONG" * 8,
                )
        self.assertEqual(cm.exception.status_code, 500)
        self.assertEqual(cm.exception.detail["code"], "decrypt_failed")
                                                                   
                                                               
        self.assertEqual(
            set(cm.exception.detail.keys()),
            {"code", "file_id"},
        )

    def test_max_chars_truncates_and_reports(self) -> None:
        row = (
            "file-x", "x.pdf", "application/pdf", "analyzed",
            "BLOB", None,
        )
        p, _ = _patch_db(row)
        with p, mock.patch(
            "vault_core.decrypt_message",
            return_value="A" * 500,
        ):
            out = ft.load_extracted_text(
                vault_id="v1", file_id="file-x", key=b"K" * 32,
                max_chars=100,
            )
        self.assertEqual(len(out["text"]), 100)
        self.assertTrue(out["truncated"])

    def test_empty_vault_or_file_id_404_does_not_query_db(self) -> None:
        with mock.patch("vault_core.get_db") as gdb:
            with self.assertRaises(HTTPException):
                ft.load_extracted_text(
                    vault_id="", file_id="f", key=b"K" * 32,
                )
            with self.assertRaises(HTTPException):
                ft.load_extracted_text(
                    vault_id="v", file_id="", key=b"K" * 32,
                )
        gdb.assert_not_called()

    def test_response_keys_are_closed_set(self) -> None:
        row = (
            "file-x", "x.pdf", "application/pdf", "analyzed",
            "BLOB", None,
        )
        p, _ = _patch_db(row)
        with p, mock.patch(
            "vault_core.decrypt_message", return_value="ok",
        ):
            out = ft.load_extracted_text(
                vault_id="v1", file_id="file-x", key=b"K" * 32,
            )
        self.assertEqual(
            set(out.keys()),
            {
                "file_id", "file_name", "content_type",
                "analysis_status", "analysis_last_error",
                "text", "truncated", "note",
            },
        )


class RouteHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        from vault_key_cache import reset_for_tests
        reset_for_tests(idle_ttl_seconds=60, hard_ttl_seconds=3600)

    def test_route_populates_key_cache_as_side_effect(self) -> None:
        import asyncio
        from vault_key_cache import get_cache
        principal = {"vault_id": "v1", "token_id": "t1",
                     "vault_name": "n", "device_id": "d"}
        row = (
            "file-x", "x.pdf", "application/pdf", "analyzed",
            "BLOB", None,
        )
        p_db, _ = _patch_db(row)
        with mock.patch(
            "main.get_verified_vault_key",
            return_value=b"K" * 32,
        ), p_db, mock.patch(
            "vault_core.decrypt_message", return_value="text",
        ):
            req = ft._ReadTextRequest(pin="1234")
            out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                ft.read_file_text_route(
                    file_id="file-x", payload=req, principal=principal,
                )
            )
        self.assertEqual(out["text"], "text")
        self.assertEqual(
            get_cache().get(vault_id="v1", token_id="t1"),
            b"K" * 32,
            "successful PIN-verified call must populate the daemon's "
            "key cache — that's how background analysis keeps running",
        )

    def test_route_404_does_not_populate_cache(self) -> None:
                                                                     
                                                                   
        import asyncio
        from vault_key_cache import get_cache
        principal = {"vault_id": "v1", "token_id": "t1",
                     "vault_name": "n", "device_id": "d"}
        p_db, _ = _patch_db(None)               
        with mock.patch(
            "main.get_verified_vault_key",
            return_value=b"K" * 32,
        ), p_db:
            req = ft._ReadTextRequest(pin="1234")
            with self.assertRaises(HTTPException):
                asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                    ft.read_file_text_route(
                        file_id="not-mine", payload=req, principal=principal,
                    )
                )
        self.assertEqual(
            get_cache().get(vault_id="v1", token_id="t1"),
            b"K" * 32,
        )


class NeverLogsTextOrKeyTests(unittest.TestCase):


    def test_no_logger_call_includes_plaintext_or_key(self) -> None:
        src = inspect.getsource(ft)
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
            for forbidden in ("plaintext", "encrypted_text", " key,",
                              " key)", "key=", " text,", " text)"):
                self.assertNotIn(
                    forbidden, line,
                    f"logger call may leak sensitive value: {line!r}",
                )


if __name__ == "__main__":
    unittest.main()
