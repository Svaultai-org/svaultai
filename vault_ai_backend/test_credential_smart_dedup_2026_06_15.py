

from __future__ import annotations

import json
import unittest

from vault_credential_files_composer import (
    SYSTEM_PROMPT,
    build_credential_files_facts,
    _classify_file,
)
from vault_inventory import _dedupe_verified_matches_by_file_id


class ContentShaDedupTests(unittest.TestCase):


    def _row(self, *, fid: str, name: str, sha: str, path: str,
             rc: int = 1, services=None):
        return {
            "file_id":            fid,
            "file_name":          name,
            "saved_name":         "",
            "relative_path":      path,
            "mime_type":          "application/pdf",
            "asset_type":         "document",
            "evidence_source":    "file_text",
            "evidence_source_label": "file text",
            "record_count":       rc,
            "safe_service_names": list(services or []),
            "password_present":   True,
            "duplicate_paths":    [],
            "content_sha256":     sha,
        }

    def test_same_sha_different_file_ids_collapse(self):
        rows = [
            self._row(
                fid="fid-A", name="passedwpordtex.pdf",
                sha="a" * 64, path="/Family/2024/",
                rc=7, services=["Ally Bank", "Amex"],
            ),
            self._row(
                fid="fid-B", name="passedwpordtex.pdf",
                sha="a" * 64, path="/Old/Imports/2023/",
                rc=7, services=["Ally Bank"],
            ),
        ]
        out = _dedupe_verified_matches_by_file_id(rows)
        self.assertEqual(len(out), 1, "byte-identical content must collapse")
                                                             
        survivor = out[0]
        self.assertIn(
            "/Old/Imports/2023/",
            survivor.get("duplicate_paths") or [],
        )
                                                                 
        self.assertEqual(survivor["record_count"], 7)
                         
        self.assertEqual(
            set(survivor["safe_service_names"]),
            {"Ally Bank", "Amex"},
        )

    def test_different_sha_does_not_collapse(self):
        rows = [
            self._row(
                fid="fid-A", name="login.js",
                sha="a" * 64, path="/Code/",
            ),
            self._row(
                fid="fid-B", name="login.js",
                sha="b" * 64, path="/OtherProject/",
            ),
        ]
        out = _dedupe_verified_matches_by_file_id(rows)
        self.assertEqual(len(out), 2)

    def test_missing_sha_does_not_collapse(self):
                                                                   
                                                           
        rows = [
            self._row(
                fid="fid-A", name="zimbra.html",
                sha="", path="/Saved/",
            ),
            self._row(
                fid="fid-B", name="zimbra.html",
                sha="", path="/Archive/",
            ),
        ]
        out = _dedupe_verified_matches_by_file_id(rows)
        self.assertEqual(len(out), 2)

    def test_screenshot_scenario_collapses_8_to_4(self):
                                                               
                                                               
        def _pair(name, sha, p1, p2, rc=1, services=None):
            return [
                self._row(
                    fid=f"fid-{name}-1", name=name,
                    sha=sha, path=p1, rc=rc, services=services,
                ),
                self._row(
                    fid=f"fid-{name}-2", name=name,
                    sha=sha, path=p2, rc=rc, services=services,
                ),
            ]
        rows = []
        rows.extend(_pair(
            "passedwpordtex.pdf", "1" * 64,
            "/Family/2024/", "/Backups/2023/", rc=7,
            services=["Ally Bank", "Amex"],
        ))
        rows.extend(_pair(
            "zimbra.html", "2" * 64,
            "/Saved/", "/Web/Saved/",
        ))
        rows.extend(_pair(
            "wellsfargologinhtml.html", "3" * 64,
            "/Saved/", "/Banking/",
            services=["Wells Fargo"],
        ))
        rows.extend(_pair(
            "login.js", "4" * 64,
            "/Code/", "/Old/Code/",
            rc=2,
        ))
        out = _dedupe_verified_matches_by_file_id(rows)
        self.assertEqual(
            len(out), 4,
            "4 distinct content hashes must collapse to 4 entries",
        )
        names = {row["file_name"] for row in out}
        self.assertEqual(names, {
            "passedwpordtex.pdf",
            "zimbra.html",
            "wellsfargologinhtml.html",
            "login.js",
        })


class FileCategoryClassifierTests(unittest.TestCase):
    def test_banking_brand_name_routes_to_banking(self):
        cat = _classify_file({
            "file_name":          "wellsfargologinhtml.html",
            "safe_service_names": ["Wells Fargo"],
        })
        self.assertEqual(cat, "banking_page")

    def test_ally_bank_service_name_alone_triggers_banking(self):
        cat = _classify_file({
            "file_name":          "statement_q3.pdf",
            "safe_service_names": ["Ally Bank"],
        })
        self.assertEqual(cat, "banking_page")

    def test_login_form_filename_routes_to_login(self):
        cat = _classify_file({
            "file_name":          "login.js",
            "safe_service_names": [],
        })
        self.assertEqual(cat, "login_form")

    def test_password_list_filename_routes_to_credentials_list(self):
        cat = _classify_file({
            "file_name":          "passwords-export.txt",
            "safe_service_names": [],
        })
        self.assertEqual(cat, "credentials_list")

    def test_env_extension_routes_to_config_secrets(self):
        cat = _classify_file({
            "file_name":          ".env.production",
            "safe_service_names": [],
        })
        self.assertEqual(cat, "config_secrets")

    def test_high_record_count_falls_back_to_credentials_list(self):
        cat = _classify_file({
            "file_name":          "notes.md",
            "safe_service_names": [],
            "record_count":       7,
        })
        self.assertEqual(cat, "credentials_list")

    def test_no_signal_routes_to_other(self):
        cat = _classify_file({
            "file_name":          "random.pdf",
            "safe_service_names": [],
            "record_count":       1,
        })
        self.assertEqual(cat, "other")


class CredentialFilesFactsShapeTests(unittest.TestCase):
    def _packet(self, matches):
        return build_credential_files_facts(
            user_question="list me files that has credentials in it",
            vault_id="vault-abc",
            verified_matches=matches,
            scanned_count=425,
            not_scanned_count=0,
            is_partial=False,
            coverage_extra=None,
            authorized_unlocked=True,
        )

    def test_packet_has_categories_block(self):
        matches = [{
            "file_id":            "f1",
            "file_name":          "wellsfargologinhtml.html",
            "safe_service_names": ["Wells Fargo"],
            "record_count":       1,
            "password_present":   True,
        }]
        p = self._packet(matches)
        self.assertIn("categories", p)
                                                                 
                 
        self.assertEqual(list(p["categories"].keys()), ["banking_page"])
        bp = p["categories"]["banking_page"]
        self.assertEqual(bp["label"], "Banking pages")
        self.assertEqual(len(bp["files"]), 1)
        self.assertEqual(bp["files"][0]["file_name"], "wellsfargologinhtml.html")

    def test_packet_collects_services_seen(self):
        matches = [
            {
                "file_id":            "f1",
                "file_name":          "wellsfargologinhtml.html",
                "safe_service_names": ["Wells Fargo"],
                "record_count":       1,
                "password_present":   True,
            },
            {
                "file_id":            "f2",
                "file_name":          "passedwpordtex.pdf",
                "safe_service_names": ["Ally Bank", "Amex"],
                "record_count":       7,
                "password_present":   True,
            },
        ]
        p = self._packet(matches)
        self.assertEqual(
            set(p["services_seen"]),
            {"Wells Fargo", "Ally Bank", "Amex"},
        )

    def test_packet_counts_duplicate_copies(self):
        matches = [{
            "file_id":            "f1",
            "file_name":          "passedwpordtex.pdf",
            "safe_service_names": [],
            "record_count":       7,
            "password_present":   True,
            "duplicate_paths":    ["/Family/2024/", "/Backups/"],
        }]
        p = self._packet(matches)
        self.assertEqual(p["duplicate_copies_seen"], 2)

    def test_packet_never_contains_password_or_token_values(self):
                                                               
                                                              
        matches = [{
            "file_id":            "f1",
            "file_name":          "leak.txt",
            "safe_service_names": [],
            "record_count":       1,
            "password_present":   True,
            "password":           "hunter2-DO-NOT-LEAK",
            "token":              "DO-NOT-LEAK-EITHER",
        }]
        blob = json.dumps(self._packet(matches))
        self.assertNotIn("hunter2", blob)
        self.assertNotIn("DO-NOT-LEAK", blob)


class ComposerPromptContractTests(unittest.TestCase):
    def test_prompt_demands_paragraphs_not_one_liner(self):
                                                            
                                             
        self.assertIn("2 to 4 short paragraphs", SYSTEM_PROMPT)

    def test_prompt_demands_category_walkthrough(self):
        self.assertIn("WALK THROUGH each category", SYSTEM_PROMPT)

    def test_prompt_demands_duplicate_callout(self):
        self.assertIn("duplicate_paths", SYSTEM_PROMPT)
        self.assertIn("byte-identical copies", SYSTEM_PROMPT)

    def test_prompt_demands_follow_up_offer(self):
        self.assertIn("CLOSE with one obvious follow-up", SYSTEM_PROMPT)

    def test_prompt_forbids_markdown(self):
                                                                   
        self.assertIn("no markdown bold", SYSTEM_PROMPT.lower())

    def test_prompt_demands_first_person_vault_identity(self):
                                                              
                      
        self.assertIn("You ARE the user's vault", SYSTEM_PROMPT)
        self.assertNotIn("you are an assistant", SYSTEM_PROMPT.lower())

    def test_prompt_grounds_in_packet_only(self):
        self.assertIn("Do not invent files", SYSTEM_PROMPT)
        self.assertIn("Stay grounded in the facts", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
