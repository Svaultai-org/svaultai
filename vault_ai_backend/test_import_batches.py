

from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import main
from main import (
    _IMPORT_BATCH_STATUSES,
    _TERMINAL_IMPORT_BATCH_STATUSES,
    _compute_complete_import_status,
    _is_terminal_import_status,
    _storage_limit_error_detail,
    _validate_import_id_for_upload,
    save_uploaded_file,
)


class ImportBatchStatusEnumTests(unittest.TestCase):


    EXPECTED = frozenset({
        "pending",
        "uploading",
        "completed",
        "completed_with_errors",
        "cancelled",
        "failed",
    })

    EXPECTED_TERMINAL = frozenset({
        "completed",
        "completed_with_errors",
        "cancelled",
        "failed",
    })

    def test_python_enum_matches_expected_six(self):
        self.assertEqual(_IMPORT_BATCH_STATUSES, self.EXPECTED)

    def test_terminal_subset_matches_expected_four(self):
        self.assertEqual(
            _TERMINAL_IMPORT_BATCH_STATUSES, self.EXPECTED_TERMINAL,
        )

    def test_terminal_is_subset_of_full(self):
                                                                    
        self.assertTrue(
            _TERMINAL_IMPORT_BATCH_STATUSES.issubset(_IMPORT_BATCH_STATUSES),
        )

    def test_non_terminal_statuses_are_pending_and_uploading(self):
        non_terminal = _IMPORT_BATCH_STATUSES - _TERMINAL_IMPORT_BATCH_STATUSES
        self.assertEqual(non_terminal, frozenset({"pending", "uploading"}))

    def test_migration_check_constraint_lists_the_same_six(self):
                                                                    
                                                                     
        mig_path = Path(__file__).parent / "migrations" / "versions" / "0003_import_batches.py"
        src = mig_path.read_text()
        for name in self.EXPECTED:
            self.assertIn(
                f"'{name}'", src,
                f"migration CHECK must include '{name}'",
            )

    def test_is_terminal_helper_matches_set(self):
        for status in _IMPORT_BATCH_STATUSES:
            expected = status in _TERMINAL_IMPORT_BATCH_STATUSES
            self.assertEqual(
                _is_terminal_import_status(status),
                expected,
                f"_is_terminal_import_status({status!r}) "
                f"expected {expected}",
            )

    def test_is_terminal_helper_handles_none_and_unknown(self):
                                                                        
        self.assertFalse(_is_terminal_import_status(None))
        self.assertFalse(_is_terminal_import_status("not-a-real-status"))
        self.assertFalse(_is_terminal_import_status(""))


class ComputeCompleteImportStatusTests(unittest.TestCase):


    def test_zero_failures_is_completed(self):
        self.assertEqual(
            _compute_complete_import_status(0), "completed",
        )

    def test_one_failure_is_completed_with_errors(self):
        self.assertEqual(
            _compute_complete_import_status(1),
            "completed_with_errors",
        )

    def test_many_failures_is_completed_with_errors(self):
        self.assertEqual(
            _compute_complete_import_status(245),
            "completed_with_errors",
        )

    def test_negative_failures_is_completed(self):
                                                                 
                                                    
        self.assertEqual(
            _compute_complete_import_status(-1), "completed",
        )
        self.assertEqual(
            _compute_complete_import_status(-100), "completed",
        )

    def test_result_is_always_in_the_terminal_set(self):
        for failed in (0, 1, 5, 100, -3):
            status = _compute_complete_import_status(failed)
            self.assertIn(status, _TERMINAL_IMPORT_BATCH_STATUSES)


class ValidateImportIdForUploadTests(unittest.TestCase):


    @staticmethod
    def _batch_row(status: str) -> dict:
        return {
            "import_id": "abc-123",
            "vault_id": "vault-1",
            "status": status,
            "uploaded_count": 0,
            "failed_count": 0,
        }

    def test_none_import_id_returns_none_without_db_lookup(self):
        with patch("main.get_import_batch") as fake_get:
            result = _validate_import_id_for_upload("vault-1", None)
        self.assertIsNone(result)
        fake_get.assert_not_called()

    def test_empty_string_import_id_returns_none_without_lookup(self):
        with patch("main.get_import_batch") as fake_get:
            result = _validate_import_id_for_upload("vault-1", "")
        self.assertIsNone(result)
        fake_get.assert_not_called()

    def test_missing_batch_raises_404(self):
        with patch("main.get_import_batch", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                _validate_import_id_for_upload("vault-1", "ghost-id")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(
            ctx.exception.detail["code"], "import_batch_not_found",
        )

    def test_pending_batch_is_accepted(self):
        with patch(
            "main.get_import_batch",
            return_value=self._batch_row("pending"),
        ):
            row = _validate_import_id_for_upload("vault-1", "abc-123")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "pending")

    def test_uploading_batch_is_accepted(self):
        with patch(
            "main.get_import_batch",
            return_value=self._batch_row("uploading"),
        ):
            row = _validate_import_id_for_upload("vault-1", "abc-123")
        self.assertEqual(row["status"], "uploading")

    def test_completed_batch_raises_409(self):
        with patch(
            "main.get_import_batch",
            return_value=self._batch_row("completed"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _validate_import_id_for_upload("vault-1", "abc-123")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(
            ctx.exception.detail["code"], "import_batch_terminal",
        )

    def test_cancelled_batch_raises_409(self):
        with patch(
            "main.get_import_batch",
            return_value=self._batch_row("cancelled"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _validate_import_id_for_upload("vault-1", "abc-123")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(
            "cancelled",
            ctx.exception.detail["message"],
        )

    def test_failed_batch_raises_409(self):
        with patch(
            "main.get_import_batch",
            return_value=self._batch_row("failed"),
        ):
            with self.assertRaises(HTTPException):
                _validate_import_id_for_upload("vault-1", "abc-123")

    def test_completed_with_errors_batch_raises_409(self):
        with patch(
            "main.get_import_batch",
            return_value=self._batch_row("completed_with_errors"),
        ):
            with self.assertRaises(HTTPException):
                _validate_import_id_for_upload("vault-1", "abc-123")


class StorageLimitErrorDetailTests(unittest.TestCase):


    def test_canonical_shape(self):
        detail = _storage_limit_error_detail(
            used=1024,
            limit=2048,
            requested=4096,
        )
        self.assertEqual(detail["code"], "vault_storage_limit_exceeded")
        self.assertEqual(detail["used_bytes"], 1024)
        self.assertEqual(detail["limit_bytes"], 2048)
        self.assertEqual(detail["projected_bytes"], 1024 + 4096)
        self.assertIn("Vault storage limit", detail["message"])

    def test_zero_requested_still_emits_a_message(self):
        detail = _storage_limit_error_detail(
            used=0, limit=1000, requested=0,
        )
                                                                  
        self.assertTrue(detail["message"])


class SaveUploadedFileImportIdWiringTests(unittest.TestCase):


    def test_signature_accepts_import_id_with_safe_default(self):
        sig = inspect.signature(save_uploaded_file)
        param = sig.parameters.get("import_id")
        self.assertIsNotNone(
            param, "save_uploaded_file must accept import_id",
        )
        self.assertIsNone(
            param.default,
            "default must be None — single-file legacy path stays "
            "un-batched",
        )

    def test_source_calls_validate_before_bump(self):
        src = inspect.getsource(save_uploaded_file)
        validate_idx = src.find("_validate_import_id_for_upload(")
        bump_idx = src.find("_bump_import_batch_on_upload_success(")
        self.assertGreater(
            validate_idx, -1,
            "validate gate must be wired into save_uploaded_file",
        )
        self.assertGreater(
            bump_idx, -1,
            "success bump must be wired into save_uploaded_file",
        )
        self.assertLess(
            validate_idx, bump_idx,
            "validate must run BEFORE the bump",
        )

    def test_insert_lists_import_id_column(self):
        src = inspect.getsource(save_uploaded_file)
                                                                  
                                                                    
        insert_match = re.search(
            r"INSERT INTO uploaded_files\s*\((?P<cols>[^)]+)\)",
            src,
        )
        self.assertIsNotNone(
            insert_match,
            "save_uploaded_file must contain an INSERT INTO uploaded_files",
        )
        cols = insert_match.group("cols")
        self.assertIn(
            "import_id", cols,
            "INSERT column list must include import_id",
        )


class ImportBatchRoutesShapeTests(unittest.TestCase):


    EXPECTED_ROUTES = {
        ("POST", "/imports/start"),
        ("GET",  "/imports/{import_id}"),
        ("POST", "/imports/{import_id}/cancel"),
        ("POST", "/imports/{import_id}/complete"),
    }

    def test_all_four_routes_registered(self):
        from routes.import_batch_routes import router
        actual: set[tuple[str, str]] = set()
        for route in router.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", None)
            for method in methods:
                actual.add((method, path))
        missing = self.EXPECTED_ROUTES - actual
        self.assertFalse(
            missing,
            f"missing import-batch routes: {missing!r}",
        )

    def test_start_request_model_carries_planned_metadata(self):
        from routes.import_batch_routes import ImportBatchStartRequest
        fields = set(ImportBatchStartRequest.model_fields.keys())
        for name in (
            "vault_name", "pin", "root_folder_name",
            "total_files", "total_bytes_planned",
        ):
            self.assertIn(
                name, fields,
                f"ImportBatchStartRequest must declare {name}",
            )

    def test_action_request_model_carries_deltas(self):
        from routes.import_batch_routes import ImportBatchActionRequest
        fields = set(ImportBatchActionRequest.model_fields.keys())
        for name in (
            "vault_name", "pin",
            "failed_count_delta", "skipped_duplicate_count_delta",
        ):
            self.assertIn(
                name, fields,
                f"ImportBatchActionRequest must declare {name}",
            )


class ChunkedUploadImportIdWiringTests(unittest.TestCase):


    @staticmethod
    def _chunked_src() -> str:
        path = (
            Path(__file__).parent
            / "routes"
            / "chunked_upload_routes.py"
        )
        return path.read_text()

    def test_init_request_model_has_import_id_field(self):
        from routes.chunked_upload_routes import ChunkInitRequest
        fields = set(ChunkInitRequest.model_fields.keys())
        self.assertIn(
            "import_id", fields,
            "ChunkInitRequest must declare import_id",
        )

    def test_init_calls_validate_before_insert(self):
        src = self._chunked_src()
        validate_idx = src.find("_validate_import_id_for_upload(")
                                                           
        insert_idx = src.find("INSERT INTO uploaded_files")
        self.assertGreater(validate_idx, -1)
        self.assertGreater(insert_idx, -1)
        self.assertLess(
            validate_idx, insert_idx,
            "validate must run BEFORE the chunked INSERT",
        )

    def test_finalize_calls_success_bump(self):
        src = self._chunked_src()
        self.assertIn(
            "_bump_import_batch_on_upload_success",
            src,
            "finalize must bump uploaded_count when import_id is set",
        )

    def test_abort_calls_failure_bump(self):
        src = self._chunked_src()
        self.assertIn(
            "_bump_import_batch_on_failure",
            src,
            "abort must bump failed_count when import_id is set",
        )

    def test_init_insert_lists_import_id_column(self):
        src = self._chunked_src()
        insert_match = re.search(
            r"INSERT INTO uploaded_files\s*\((?P<cols>[^)]+)\)",
            src,
        )
        self.assertIsNotNone(insert_match)
        cols = insert_match.group("cols")
        self.assertIn(
            "import_id", cols,
            "chunked INSERT column list must include import_id",
        )


class MainPyRouterRegistrationTests(unittest.TestCase):


    def test_app_includes_import_batch_router(self):
                                                              
        paths = {
            getattr(r, "path", None) for r in main.app.routes
        }
        self.assertIn(
            "/imports/start",
            paths,
            "/imports/start must be registered on the FastAPI app",
        )
        self.assertIn(
            "/imports/{import_id}",
            paths,
            "/imports/{import_id} must be registered on the FastAPI app",
        )


if __name__ == "__main__":
    unittest.main()
