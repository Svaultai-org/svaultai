

from __future__ import annotations

import inspect
import json
import unittest
from datetime import datetime, timedelta, timezone

from vault_inventory import (
    DEFAULT_RECENT_FILES_LIMIT,
    format_credential_files_reply,
    format_folder_list_reply,
    format_recent_uploads_reply,
    format_travel_readiness_reply,
    format_vault_summary_reply,
    list_recent_files,
    list_top_folders,
    search_files_for_credentials,
    summarize_vault_contents,
    travel_readiness_check,
)


def _file(
    *,
    id: str,
    file_name: str = "untitled.pdf",
    saved_name: str | None = None,
    relative_path: str | None = None,
    content_type: str = "application/pdf",
    file_size: int = 1024,
    asset_type: str = "file",
    detected_service: str | None = None,
    created_at=None,
    extracted_text: str | None = None,
) -> dict:
    return {
        "id": id,
        "file_name": file_name,
        "saved_name": saved_name,
        "relative_path": relative_path,
        "content_type": content_type,
        "file_size": file_size,
        "asset_type": asset_type,
        "detected_service": detected_service,
        "created_at": created_at,
        "extracted_text": extracted_text,
    }


class SummarizeVaultContentsTests(unittest.TestCase):
    def test_empty_vault_returns_zero_total(self):
        s = summarize_vault_contents([])
        self.assertEqual(s["total_files"], 0)
        self.assertEqual(s["folder_count"], 0)
        self.assertEqual(s["top_folders"], [])
        self.assertEqual(s["recent_files"], [])

    def test_counts_files_and_folders(self):
        rows = [
            _file(id="1", file_name="a.pdf",
                  relative_path="Bank/a.pdf"),
            _file(id="2", file_name="b.pdf",
                  relative_path="Bank/b.pdf"),
            _file(id="3", file_name="c.jpg",
                  relative_path="Family/c.jpg",
                  content_type="image/jpeg"),
        ]
        s = summarize_vault_contents(rows)
        self.assertEqual(s["total_files"], 3)
        self.assertEqual(s["folder_count"], 2)
                                           
        names = [f["name"] for f in s["top_folders"]]
        self.assertEqual(names[0], "Bank")
        self.assertEqual(names[1], "Family")

    def test_type_buckets(self):
        rows = [
            _file(id="1", file_name="a.pdf"),
            _file(id="2", file_name="b.jpg"),
            _file(id="3", file_name="c.png"),
            _file(id="4", file_name="d.py"),
            _file(id="5", file_name="e.zip"),
        ]
        s = summarize_vault_contents(rows)
        self.assertEqual(s["type_counts"]["PDFs"], 1)
        self.assertEqual(s["type_counts"]["Images"], 2)
        self.assertEqual(s["type_counts"]["Scripts"], 1)
        self.assertEqual(s["type_counts"]["Archives"], 1)


class ListRecentFilesTests(unittest.TestCase):
    def test_newest_first(self):
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            _file(id="a", created_at=t0),
            _file(id="b", created_at=t0 + timedelta(hours=1)),
            _file(id="c", created_at=t0 - timedelta(hours=1)),
        ]
        ids = [r["id"] for r in list_recent_files(rows, limit=3)]
        self.assertEqual(ids, ["b", "a", "c"])

    def test_respects_limit(self):
        t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [
            _file(id=str(i), created_at=t0 + timedelta(minutes=i))
            for i in range(20)
        ]
        result = list_recent_files(rows, limit=5)
        self.assertEqual(len(result), 5)

    def test_rows_without_timestamp_are_pushed_to_end(self):
        t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        rows = [
            _file(id="legacy"),                 
            _file(id="new", created_at=t0),
        ]
        ids = [r["id"] for r in list_recent_files(rows, limit=2)]
        self.assertEqual(ids[0], "new")
        self.assertEqual(ids[-1], "legacy")


class ListTopFoldersTests(unittest.TestCase):
    def test_orders_by_count_desc(self):
        rows = [
            _file(id="1", relative_path="A/x.pdf"),
            _file(id="2", relative_path="B/y.pdf"),
            _file(id="3", relative_path="B/z.pdf"),
            _file(id="4", relative_path="B/q.pdf"),
        ]
        folders = list_top_folders(rows, limit=10)
        self.assertEqual(folders[0]["name"], "B")
        self.assertEqual(folders[0]["file_count"], 3)
        self.assertEqual(folders[1]["name"], "A")

    def test_un_foldered_files_not_counted(self):
        rows = [
            _file(id="1", relative_path=None),
            _file(id="2", relative_path="A/x.pdf"),
        ]
        folders = list_top_folders(rows)
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["name"], "A")


class SearchFilesForCredentialsTests(unittest.TestCase):
    def test_filename_hint_passwords(self):
        rows = [
            _file(id="1", file_name="passwords.txt"),
            _file(id="2", file_name="vacation.jpg"),
        ]
        out = search_files_for_credentials(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file_id"], "1")
                                                                  
                                                                 
        self.assertIn("password", out[0]["reasons"][0])

    def test_dotenv_files_caught(self):
        rows = [
            _file(id="1", file_name=".env"),
            _file(id="2", file_name=".env.local"),
        ]
        out = search_files_for_credentials(rows)
        self.assertEqual(len(out), 2)

    def test_folder_hint_credentials(self):
        rows = [
            _file(id="1", file_name="anything.txt",
                  relative_path="Credentials/anything.txt"),
        ]
        out = search_files_for_credentials(rows)
        self.assertEqual(len(out), 1)
                                                                      
                                         
        self.assertIn("credentials", out[0]["reasons"][0])

    def test_detected_service_login(self):
        rows = [
            _file(
                id="1", file_name="export.csv",
                detected_service="login",
            ),
        ]
        out = search_files_for_credentials(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(
            out[0]["reasons"][-1],
            "detected as a credential file",
        )

    def test_no_match_returns_empty(self):
        rows = [
            _file(id="1", file_name="vacation.jpg"),
            _file(id="2", file_name="taxes_2024.pdf"),
        ]
        out = search_files_for_credentials(rows)
        self.assertEqual(out, [])

    def test_does_NOT_return_vault_items_categories(self):
                                                                   
                                                                 
        rows = [
            _file(id="1", file_name="passwords.txt"),
        ]
        out = search_files_for_credentials(rows)
                                                              
                                                              
        self.assertIn("file_id", out[0])
        self.assertIn("file_name", out[0])
                                    
        self.assertNotIn("category", out[0])

    def test_no_password_value_in_response(self):
                                                                   
                                                
        rows = [
            _file(id="1", file_name="passwords.txt"),
        ]
        out = search_files_for_credentials(rows)
                                 
        for key in out[0].keys():
            self.assertNotIn(key.lower(), ("password", "secret", "token"))


class TravelReadinessTests(unittest.TestCase):
    NOW = datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)

    def test_empty_vault_blocked(self):
        report = travel_readiness_check(rows=[], now=self.NOW)
        self.assertEqual(report["confidence"], "blocked")
        self.assertEqual(report["found"], [])
                                                     
        self.assertIn("passport", report["missing"])
        self.assertIn("visa", report["missing"])

    def test_filename_detects_passport_and_visa(self):
        rows = [
            _file(id="1", file_name="passport.pdf"),
            _file(id="2", file_name="visa Qatar.pdf"),
        ]
        report = travel_readiness_check(rows=rows, now=self.NOW)
        self.assertIn("passport", report["found"])
        self.assertIn("visa", report["found"])

    def test_metadata_expiry_marks_expired(self):
        rows = [_file(id="1", file_name="passport.pdf")]
        metadata = [{
            "uploaded_file_id": "1",
            "doc_type": "passport",
            "metadata_json": {"expiry_date": "2025-09-15"},
        }]
        report = travel_readiness_check(
            rows=rows, metadata_rows=metadata, now=self.NOW,
        )
        self.assertEqual(report["confidence"], "blocked")
        self.assertEqual(len(report["expired"]), 1)
        self.assertEqual(report["expired"][0]["doc_type"], "passport")
        self.assertGreater(
            report["expired"][0]["days_overdue"], 0,
        )

    def test_expiring_soon_within_30_days(self):
        rows = [_file(id="1", file_name="visa.pdf")]
        expiry = (self.NOW + timedelta(days=18)).date().isoformat()
        metadata = [{
            "uploaded_file_id": "1",
            "doc_type": "visa",
            "metadata_json": {"expiry_date": expiry},
        }]
        report = travel_readiness_check(
            rows=rows, metadata_rows=metadata, now=self.NOW,
        )
        self.assertEqual(report["confidence"], "partial")
        self.assertEqual(len(report["expiring_soon"]), 1)
        self.assertEqual(
            report["expiring_soon"][0]["days_until"], 18,
        )

    def test_all_docs_present_no_expiry_concerns_ready(self):
                                                            
        future = (self.NOW + timedelta(days=365)).date().isoformat()
        rows = [
            _file(id="1", file_name="passport.pdf"),
            _file(id="2", file_name="visa.pdf"),
            _file(id="3", file_name="boarding pass.pdf"),
            _file(id="4", file_name="flight ticket.pdf"),
            _file(id="5", file_name="hotel booking.pdf"),
        ]
        metadata = [
            {
                "uploaded_file_id": str(i),
                "doc_type": dt,
                "metadata_json": {"expiry_date": future},
            }
            for i, dt in enumerate(
                ("passport", "visa", "boarding_pass",
                 "ticket", "hotel_itinerary"),
                start=1,
            )
        ]
        report = travel_readiness_check(
            rows=rows, metadata_rows=metadata, now=self.NOW,
        )
        self.assertEqual(report["confidence"], "ready")
        self.assertEqual(report["missing"], [])

    def test_partial_when_some_missing(self):
                                                           
        rows = [_file(id="1", file_name="passport.pdf")]
        report = travel_readiness_check(rows=rows, now=self.NOW)
        self.assertEqual(report["confidence"], "partial")
        self.assertIn("passport", report["found"])
        for dt in ("visa", "boarding_pass", "ticket", "hotel_itinerary"):
            self.assertIn(dt, report["missing"])


class FormatRepliesTests(unittest.TestCase):
    def test_summary_empty_uses_spec_copy(self):
        out = format_vault_summary_reply({
            "total_files": 0,
        })
        self.assertIn("don't see any uploaded files", out)

    def test_summary_with_files_lists_folders_and_recent(self):
        out = format_vault_summary_reply({
            "total_files": 5,
            "folder_count": 2,
            "top_folders": [
                {"name": "Bank", "file_count": 3},
                {"name": "Family", "file_count": 2},
            ],
            "type_counts": {"PDFs": 3, "Images": 2},
            "recent_files": [
                {"file_name": "statement.pdf"},
                {"file_name": "maureen.jpg"},
            ],
        })
        self.assertIn("5 uploaded files", out)
        self.assertIn("2 folders", out)
        self.assertIn("Bank", out)
        self.assertIn("statement.pdf", out)

    def test_folder_list_empty(self):
        self.assertIn(
            "don't have any folders",
            format_folder_list_reply([]),
        )

    def test_recent_uploads_empty(self):
        self.assertIn(
            "don't see any recent uploads",
            format_recent_uploads_reply([]),
        )

    def test_credential_files_empty_redirects_to_saved_logins(self):
                                                                  
                                                                   
        out = format_credential_files_reply([])
        self.assertIn("saved logins", out)

    def test_credential_files_lists_verified_match(self):
                                                                  
                                                                
        out = format_credential_files_reply([
            {
                "file_id": "1",
                "file_name": "passwords.txt",
                "record_count": 5,
                "evidence_source": "file_text",
                "evidence_source_label": "file text",
                "password_present": True,
            },
        ])
        self.assertIn("passwords.txt", out)
        self.assertIn("5 records", out)
        self.assertIn("file text", out)
                                                                           
        self.assertIn("Files with saved credentials", out)
                                        
        self.assertNotIn("hunter2", out)
                                       
        self.assertNotIn("[strong]", out)
        self.assertNotIn("[weak]", out)
        self.assertNotIn("may contain", out.lower())

    def test_travel_readiness_blocked_empty_friendly(self):
        out = format_travel_readiness_reply({
            "found": [],
            "missing": [],
            "expired": [],
            "expiring_soon": [],
            "confidence": "blocked",
        })
        self.assertIn(
            "don't see any travel documents",
            out,
        )

    def test_travel_readiness_partial_lists_missing(self):
                                                                    
                                                         
        out = format_travel_readiness_reply({
            "found": ["passport"],
            "missing": ["visa", "ticket", "hotel_itinerary"],
            "expired": [],
            "expiring_soon": [],
            "confidence": "partial",
        })
        self.assertIn("Passport", out)
        self.assertIn("Visa", out)
        self.assertIn("Hotel itinerary", out)

    def test_travel_readiness_expired_renders(self):
        out = format_travel_readiness_reply({
            "found": ["passport"],
            "missing": [],
            "expired": [
                {
                    "doc_type": "passport",
                    "file_id": "1",
                    "label": "Maureen passport",
                    "days_overdue": 257,
                },
            ],
            "expiring_soon": [],
            "confidence": "blocked",
        })
        self.assertIn("expired 257 days ago", out)


class ClassifierExposesNewIntentsTests(unittest.TestCase):


    def _prompt_src(self) -> str:
        import main
        return inspect.getsource(main.detect_vault_intent)

    def test_all_new_intents_listed(self):
        src = self._prompt_src()
        for intent in (
            "summarize_vault",
            "list_files",
            "list_folders",
            "list_recent_uploads",
            "search_files_for_credentials",
            "travel_readiness",
        ):
            self.assertIn(
                intent, src,
                f"intent {intent!r} must be in the LLM prompt list",
            )

    def test_credential_file_search_disambiguated_from_saved_logins(self):
                                                                
                                                               
        src = self._prompt_src()
        self.assertIn("Never ask the user for a service name", src)
        self.assertIn("vault_items", src)


class ChatDispatcherWiringTests(unittest.TestCase):


    def _src(self) -> str:
        import main
        return inspect.getsource(main.chat_endpoint)

    def test_handlers_present(self):
        src = self._src()
        for handler in (
            'intent in ("summarize_vault", "list_files")',
            'intent == "list_folders"',
            'intent == "list_recent_uploads"',
            'intent == "search_files_for_credentials"',
            'intent == "travel_readiness"',
        ):
            self.assertIn(handler, src, handler)

    def test_inventory_handlers_run_before_retrieve_file(self):
        src = self._src()
        inv_idx = src.find('intent in ("summarize_vault", "list_files")')
        rf_idx = src.find('if intent == "retrieve_file":')
        self.assertGreater(inv_idx, -1)
        self.assertGreater(rf_idx, -1)
        self.assertLess(
            inv_idx, rf_idx,
            "Phase 7 inventory handlers must dispatch BEFORE the "
            "retrieve_file branch.",
        )


class InventoryEnvelopeTests(unittest.TestCase):
    def test_envelope_wire_shape(self):
        import main
        summary = {
            "total_files":  5,
            "total_bytes":  1024 * 1024,
            "folder_count": 2,
            "top_folders":  [{"name": "Bank", "file_count": 3}],
            "type_counts":  {"PDFs": 3, "Images": 2},
            "recent_files": [{"file_id": "1", "file_name": "a.pdf"}],
        }
        env = json.loads(
            main._build_vault_inventory_envelope(
                summary=summary, message="hi",
            )
        )
        self.assertEqual(env["type"], "vault_inventory")
        self.assertEqual(env["message"], "hi")
        self.assertEqual(env["total_files"], 5)
        self.assertEqual(env["folder_count"], 2)
        self.assertEqual(
            env["top_folders"][0]["name"], "Bank",
        )
        self.assertEqual(env["type_counts"]["PDFs"], 3)
        self.assertEqual(
            env["recent_files"][0]["file_id"], "1",
        )


class TravelReadinessEnvelopeTests(unittest.TestCase):
    def test_envelope_wire_shape(self):
        import main
        report = {
            "found":         ["passport", "visa"],
            "missing":       ["boarding_pass", "hotel_itinerary"],
            "expired":       [{
                "doc_type": "passport",
                "file_id": "p1",
                "expiry_date": "2025-09-15",
                "label": "Maureen passport",
                "days_overdue": 257,
            }],
            "expiring_soon": [{
                "doc_type": "visa",
                "file_id": "v1",
                "expiry_date": "2026-06-25",
                "label": "Qatar visa",
                "days_until": 18,
            }],
            "confidence":    "blocked",
        }
        env = json.loads(
            main._build_travel_readiness_envelope(
                report=report, message="status",
            )
        )
        self.assertEqual(env["type"], "travel_readiness")
        self.assertEqual(env["message"], "status")
        self.assertEqual(env["confidence"], "blocked")
        self.assertEqual(env["found"], ["passport", "visa"])
        self.assertEqual(
            env["missing"], ["boarding_pass", "hotel_itinerary"],
        )
        self.assertEqual(env["expired"][0]["days_overdue"], 257)
        self.assertEqual(env["expiring_soon"][0]["days_until"], 18)

    def test_envelope_defaults_when_report_keys_missing(self):
        import main
        env = json.loads(
            main._build_travel_readiness_envelope(
                report={}, message="empty",
            )
        )
        self.assertEqual(env["type"], "travel_readiness")
        self.assertEqual(env["confidence"], "blocked")
        self.assertEqual(env["found"], [])
        self.assertEqual(env["missing"], [])
        self.assertEqual(env["expired"], [])
        self.assertEqual(env["expiring_soon"], [])


class CredentialFilesEnvelopeTests(unittest.TestCase):
    def test_envelope_wire_shape(self):
        import main
        matches = [
            {
                "file_id":    "f1",
                "file_name":  "passwords.txt",
                "saved_name": "Old passwords",
                "mime_type":  "text/plain",
                "asset_type": "file",
                "reasons":    ['filename mentions "passwords"'],
            },
        ]
        env = json.loads(
            main._build_credential_files_envelope(
                matches=matches, message="found",
            )
        )
        self.assertEqual(env["type"], "credential_files")
        self.assertEqual(env["message"], "found")
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["files"][0]["file_id"], "f1")
        self.assertEqual(
            env["files"][0]["reasons"],
            ['filename mentions "passwords"'],
        )

    def test_envelope_never_carries_credential_content(self):
                                                                 
                                                             
        import main
        matches = [{
            "file_id":   "f1",
            "file_name": "pwd.txt",
            "reasons":   ["filename mentions 'password'"],
        }]
        env = json.loads(
            main._build_credential_files_envelope(
                matches=matches, message="ok",
            )
        )
        wire = json.dumps(env)
                                                                
        self.assertNotIn("hunter2", wire)
                                                                
                                                       
        self.assertNotIn('"password"', wire)

    def test_empty_matches_yields_zero_count(self):
        import main
        env = json.loads(
            main._build_credential_files_envelope(
                matches=[], message="none",
            )
        )
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["files"], [])


class RelatedFilesEnvelopeTests(unittest.TestCase):
    def test_envelope_wire_shape_with_results(self):
        import main
        anchor = {
            "file_id":       "a1",
            "file_name":     "maureen id back.jpg",
            "saved_name":    "Maureen ID back",
            "relative_path": "Identity/maureen id back.jpg",
        }
        results = [
            {
                "file_id":       "r1",
                "file_name":     "maureen id front.jpg",
                "saved_name":    "Maureen ID front",
                "relative_path": "Identity/maureen id front.jpg",
                "confidence":    "strong",
                "reasons": [
                    {
                        "code": "filename_front_back_pair",
                        "label": "matching front/back filename pair",
                        "weight": 2.0,
                    },
                ],
            },
        ]
        env = json.loads(
            main._build_related_files_envelope(
                anchor=anchor, results=results, message="paired",
            )
        )
        self.assertEqual(env["type"], "related_files")
        self.assertEqual(env["message"], "paired")
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["anchor"]["file_id"], "a1")
        self.assertEqual(env["results"][0]["confidence"], "strong")
        self.assertEqual(
            env["results"][0]["reasons"][0]["code"],
            "filename_front_back_pair",
        )

    def test_build_payload_helper_caps_results(self):
                                                            
                                                               
        from related_files import (
            RelatedResult,
            RelatedReason,
            RELATED_RENDER_HARD_CAP,
            build_related_files_payload,
        )
        anchor = {
            "id":         "a1",
            "file_name":  "anchor.jpg",
            "saved_name": "Anchor",
        }
                                      
        many = [
            RelatedResult(
                file_id=f"r{i}",
                file_name=f"r{i}.jpg",
                saved_name=None,
                relative_path=None,
                reasons=[RelatedReason(
                    code="shared_filename_token",
                    label="shared filename token",
                    weight=0.5,
                )],
            )
            for i in range(50)
        ]
        payload = build_related_files_payload(anchor, many)
        self.assertEqual(payload["anchor"]["file_id"], "a1")
        self.assertLessEqual(
            len(payload["results"]),
            RELATED_RENDER_HARD_CAP,
            "envelope must respect the renderer hard cap",
        )

    def test_envelope_empty_results_still_includes_anchor(self):
        import main
        anchor = {
            "file_id":   "a1",
            "file_name": "anchor.jpg",
        }
        env = json.loads(
            main._build_related_files_envelope(
                anchor=anchor, results=[], message="none",
            )
        )
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["anchor"]["file_id"], "a1")
        self.assertEqual(env["results"], [])


class ContentCredentialSignalsTests(unittest.TestCase):
    def test_unrelated_filename_with_username_password_is_strong(self):
                                                                        
                                               
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="doculetter.html",
                extracted_text=(
                    "username: alice@example.com\n"
                    "password: hunter2\n"
                ),
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["scanned_count"], 1)
        self.assertEqual(report["not_scanned_count"], 0)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(report["matches"][0]["confidence"], "strong")
                                                                      
                    
        reason_text = " · ".join(report["matches"][0]["reasons"])
        self.assertIn("username", reason_text.lower())
        self.assertIn("password", reason_text.lower())

    def test_email_near_password_is_strong(self):
                                                                    
                                                
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="notes.txt",
                extracted_text=(
                    "Login note for portal:\n"
                    "alice@example.com\n"
                    "password: hunter2\n"
                ),
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["confidence"], "strong")

    def test_dotenv_api_key_token_is_strong_or_medium(self):
                                                                       
                                                                      
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="config_dump.txt",
                extracted_text=(
                    "API_KEY: sk_live_redacted\n"
                    "TOKEN: bearer_abcdef\n"
                ),
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        self.assertIn(
            report["matches"][0]["confidence"],
            ("strong", "medium"),
        )
        reason_text = " · ".join(report["matches"][0]["reasons"])
                                                       
        self.assertTrue(
            any(s in reason_text.lower()
                for s in ("api key", "token", "secret")),
            f"reasons should name token / api key family, got: {reason_text}",
        )

    def test_login_html_filename_no_content_is_weak_only(self):
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="login.html",
                                                                  
                               
                extracted_text="<h1>Welcome to the login page</h1>",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(report["matches"][0]["confidence"], "weak")

    def test_filename_only_no_content_is_weak(self):
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="passwords.txt",
                                                                       
                                                                       
                extracted_text=None,
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["not_scanned_count"], 1)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(report["matches"][0]["confidence"], "weak")

    def test_files_without_extracted_text_increment_not_scanned(self):
                                                                       
                                                                 
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(id="f1", file_name="harmless.jpg", extracted_text=None),
            _file(
                id="f2", file_name="notes.txt",
                extracted_text="password: hunter2\nuser: alice",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["scanned_count"], 1)
        self.assertEqual(report["not_scanned_count"], 1)

    def test_strong_match_outranks_filename_match_sort_order(self):
                                                                 
                                                     
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="weak",
                file_name="passwords.txt",
                extracted_text=None,
            ),
            _file(
                id="strong",
                file_name="notes.txt",
                extracted_text="username: bob\npassword: hunter2",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["file_id"], "strong")
        self.assertEqual(report["matches"][0]["confidence"], "strong")
        self.assertEqual(report["matches"][1]["confidence"], "weak")

    def test_no_password_value_in_response(self):
                                                                      
                                                          
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="notes.txt",
                extracted_text="username: bob\npassword: SUPERSECRET-XYZ-123",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        wire = json.dumps(report)
        self.assertNotIn("SUPERSECRET-XYZ-123", wire,
            "credential value MUST NOT appear in the response")
        self.assertNotIn("hunter2", wire)

    def test_does_NOT_create_vault_items_login(self):
                                                                        
                                                                  
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="notes.txt",
                extracted_text="username: bob\npassword: hunter2",
            ),
        ]
        report = search_files_for_credentials_report(rows)
        m = report["matches"][0]
        for forbidden in (
            "encrypted_data", "category", "vault_item_id", "item_id",
        ):
            self.assertNotIn(forbidden, m)

    def test_private_key_pem_block_is_detected(self):
                                                                   
                                                          
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="export.txt",
                extracted_text=(
                    "Some preamble\n"
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    "MIIBOgIBAAJBAJq...\n"
                    "-----END RSA PRIVATE KEY-----\n"
                ),
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
                                              
        self.assertIn(
            report["matches"][0]["confidence"],
            ("strong", "medium"),
        )

    def test_mnemonic_phrase_is_detected(self):
        from vault_inventory import (
            search_files_for_credentials_report,
        )
        rows = [
            _file(
                id="f1",
                file_name="wallet_notes.txt",
                extracted_text=(
                    "mnemonic: cat dog tree apple bridge hammer ...\n"
                ),
            ),
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(len(report["matches"]), 1)
        self.assertIn(
            report["matches"][0]["confidence"],
            ("strong", "medium"),
        )

    def test_saved_login_lookup_is_separate_path(self):
                                                                
                                                                  
        from vault_inventory import (
            search_files_for_credentials_report,
        )
                                                               
                                                                    
        rows = [{
            "id": "vi1",
            "file_name": "",                   
            "saved_name": "",
            "relative_path": "",
            "content_type": "",
            "file_size": 0,
            "asset_type": "",
            "detected_service": "",
            "created_at": None,
            "extracted_text": None,
                                                            
            "password": "hunter2",
        }]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"], [],
            "no filename / folder / content signal → never surfaced")
                                                              
        self.assertNotIn("hunter2", json.dumps(report))


class CredentialFileFormatterTests(unittest.TestCase):
    def test_not_scanned_footer_in_text_reply(self):
                                                                     
                                                                      
        from vault_inventory import format_credential_files_reply
        text = format_credential_files_reply(
            matches=[
                {
                    "file_id": "f1",
                    "file_name": "notes.txt",
                    "saved_name": "",
                    "mime_type": "text/plain",
                    "asset_type": "file",
                    "record_count": 4,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                }
            ],
            not_scanned_count=3,
        )
        self.assertIn("3 still need extraction/OCR", text)
        self.assertIn("These results are incomplete", text)
                                                                     
                                                                 
        self.assertNotIn("Run vault analysis", text)

    def test_empty_matches_with_not_scanned_explains_the_gap(self):
                                                                   
                                                                  
        from vault_inventory import format_credential_files_reply
        text = format_credential_files_reply([], not_scanned_count=5)
        self.assertIn("5 file", text)
        self.assertIn("extraction/OCR before I can fully check them", text)
        self.assertNotIn("Run vault analysis", text)

    def test_strong_match_renders_no_legacy_confidence_tag(self):
                                                             
                                                                  
        from vault_inventory import format_credential_files_reply
        text = format_credential_files_reply(
            matches=[
                {
                    "file_id": "f1",
                    "file_name": "notes.txt",
                    "saved_name": "",
                    "mime_type": "text/plain",
                    "asset_type": "file",
                    "record_count": 4,
                    "evidence_source": "file_text",
                    "evidence_source_label": "file text",
                    "password_present": True,
                }
            ],
        )
        self.assertNotIn("[strong]", text)
        self.assertNotIn("[medium]", text)
        self.assertNotIn("[weak]", text)


class CredentialFilesEnvelopeWithScanCountsTests(unittest.TestCase):
    def test_envelope_carries_scanned_and_not_scanned_counts(self):
        import main
        env = json.loads(
            main._build_credential_files_envelope(
                matches=[{"file_id": "f1", "file_name": "n.txt",
                          "confidence": "strong", "reasons": ["r"]}],
                message="m",
                scanned_count=2,
                not_scanned_count=3,
            )
        )
        self.assertEqual(env["scanned_count"], 2)
        self.assertEqual(env["not_scanned_count"], 3)

    def test_dispatch_routes_through_strict_verifier_path(self):
                                                               
                                                         
        import inspect, main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn(
            "verified_credential_files_report", src,
            "dispatcher must call the strict verifier",
        )
        self.assertIn(
            "_list_uploaded_files_for_credential_search", src,
            "dispatcher must use the extracted-text-aware lister",
        )
                                                                   
                                                                   
        self.assertNotIn(
            "search_files_for_credentials_report", src,
            "chat dispatcher must NOT call the loose ranker; it is "
            "internal-only since the strict-verifier slice.",
        )


class Phase8DispatcherWiringTests(unittest.TestCase):


    def _chat_source(self) -> str:
        import inspect, main
        return inspect.getsource(main.chat_endpoint)

    def test_travel_readiness_ships_envelope(self):
        src = self._chat_source()
        self.assertIn(
            "_build_travel_readiness_envelope", src,
            "travel_readiness handler must build the structured envelope",
        )

    def test_credential_files_ships_envelope(self):
        src = self._chat_source()
        self.assertIn(
            "_build_credential_files_envelope", src,
            "search_files_for_credentials handler must build the "
            "structured envelope",
        )

    def test_related_files_ships_envelope(self):
        src = self._chat_source()
        self.assertIn(
            "_build_related_files_envelope", src,
            "related_items handler must build the structured envelope",
        )


if __name__ == "__main__":
    unittest.main()
