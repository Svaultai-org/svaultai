

import unittest

from device_gate import resolve_response_status


class ResolveResponseStatusTests(unittest.TestCase):
    def test_row_missing_maps_to_missing(self):
                                                                       
                                                                   
        status, message = resolve_response_status(
            db_status=None, row_missing=True,
        )
        self.assertEqual(status, "missing")
        self.assertIn("not been registered", message)

    def test_pending_passes_through(self):
        status, message = resolve_response_status(
            db_status="pending", row_missing=False,
        )
        self.assertEqual(status, "pending")
        self.assertEqual(message, "This device is not trusted yet.")

    def test_revoked_passes_through(self):
        status, message = resolve_response_status(
            db_status="revoked", row_missing=False,
        )
        self.assertEqual(status, "revoked")
        self.assertEqual(message, "This device is not trusted yet.")

    def test_unrecognised_status_collapses_to_unknown(self):
                                                                        
                                                                       
        for bogus in ("frozen", "weird", ""):
            with self.subTest(db_status=bogus):
                status, _ = resolve_response_status(
                    db_status=bogus, row_missing=False,
                )
                self.assertEqual(status, "unknown")

    def test_row_missing_wins_over_db_status(self):
                                                                   
                                                                    
        status, _ = resolve_response_status(
            db_status="pending", row_missing=True,
        )
        self.assertEqual(status, "missing")

    def test_message_is_never_empty(self):
                                                                  
                                                                 
        for db_status in (None, "pending", "revoked", "something-else", ""):
            for row_missing in (True, False):
                with self.subTest(db_status=db_status, row_missing=row_missing):
                    _, message = resolve_response_status(
                        db_status=db_status, row_missing=row_missing,
                    )
                    self.assertTrue(message)


if __name__ == "__main__":
    unittest.main()
