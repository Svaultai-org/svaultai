

from __future__ import annotations

import inspect
import json
import time
import unittest

import vault_inventory as vi
import vault_chat_followup as fu
import vault_chat_memory as cm


def _password_dump_text() -> str:


    blocks = []
    for svc, email, pwd in [
        ("AOL",              "user1@example.com", "Patrick62109"),
        ("Apple",            "user2@example.com", "MKSherm81765"),
        ("American Express", "user3@example.com", "e&t082826"),
        ("Wells Fargo",      "user4@example.com", "sunshine6856"),
        ("Gmail",            "user5@example.com", "loul82!Bridge"),
        ("Netflix",          "user6@example.com", "Sky88!morning"),
    ]:
        blocks.append(f"{svc}\n{email}\n{pwd}")
    return "\n".join(blocks)


def _sparse_password_in_prose() -> str:


    prose = [
        "This is the project handover document for the Q4 review.",
        "We discussed the migration timeline, the API rewrite, the",
        "frontend split, the rollout plan, and the security review.",
        "Each work-stream has its own owner and timeline.",
        "",
        "The credentials for the legacy admin console (deprecated)",
        "password: ProjectHandoverLegacyOnly",
        "",
        "Please rotate this once the migration completes.",
    ]
                                               
    while len(prose) < 100:
        prose.append("Notes from the meeting, continued.")
    return "\n".join(prose)


def _dense_env_file_text() -> str:


    return "\n".join([
        "username: ops-rotate-me",
        "email: ops@example.com",
        "password: hunter2",
        "api_key: sk_live_abcdef",
        "api_secret: shhh-keep-this-secret",
        "token: bearer-token-here",
        "secret: app-rotate-this",
        "private_key: -----BEGIN PRIVATE KEY-----...-----END PRIVATE KEY-----",
        "mnemonic: word1 word2 word3 ... word12",
        "login: ops-prod-svc",
    ])


def _row(file_id: str, *, name: str, text: str, sha: str = "",
         relative_path: str = "") -> dict:
    return {
        "id":             file_id,
        "file_name":      name,
        "saved_name":     "",
        "relative_path":  relative_path,
        "content_type":   "application/pdf",
        "asset_type":     "file",
        "extracted_text": text,
        "content_sha256": sha,
    }


class DensityHelperTests(unittest.TestCase):
    def test_empty_text_returns_zero_metrics(self):
        m = vi._compute_credential_density_metrics(None)
        for key in (
            "credential_block_count",
            "service_count",
            "credential_like_lines",
            "meaningful_lines",
        ):
            self.assertEqual(m[key], 0, key)
        self.assertEqual(m["credential_density"], 0.0)
        self.assertFalse(m["mostly_credentials"])

    def test_password_dump_fires_mostly_credentials(self):
        m = vi._compute_credential_density_metrics(_password_dump_text())
        self.assertTrue(
            m["mostly_credentials"],
            "a file shaped like a password-manager export should be "
            "tagged as mostly_credentials so it ranks first",
        )
        self.assertGreaterEqual(m["credential_block_count"], 3)
        self.assertGreaterEqual(m["service_count"], 3)
        self.assertGreaterEqual(m["credential_density"], 0.5)

    def test_sparse_one_password_line_does_NOT_fire_mostly(self):
        m = vi._compute_credential_density_metrics(_sparse_password_in_prose())
        self.assertFalse(
            m["mostly_credentials"],
            "a single labelled password line buried in prose must "
            "NOT count as mostly-credentials — that's what made "
            "the previous ranker mis-prioritise random docx files",
        )
                                                  
        self.assertLess(m["credential_density"], 0.20)

    def test_dense_env_file_fires_mostly_via_label_lines_path(self):
        m = vi._compute_credential_density_metrics(_dense_env_file_text())
        self.assertTrue(
            m["mostly_credentials"],
            ".env-style file with many labelled credential fields "
            "should also count as mostly-credentials via the "
            "label-lines path (block_count may be 0).",
        )
        self.assertGreaterEqual(m["credential_like_lines"], 9)


class RankingTests(unittest.TestCase):
    def test_password_dump_ranks_above_sparse_password_line(self):
        rows = [
            _row("sparse", name="handover.docx.pdf",
                 text=_sparse_password_in_prose(), sha="aaaa"),
            _row("dump", name="passed words 7425.docx.pdf",
                 text=_password_dump_text(), sha="bbbb"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        ids = [m["file_id"] for m in report["matches"]]
        self.assertEqual(ids[0], "dump",
            "the password-manager export must rank #1 above a "
            "docx that merely contains one password line")

    def test_dense_env_ranks_above_sparse(self):
        rows = [
            _row("sparse", name="readme.txt",
                 text=_sparse_password_in_prose(), sha="cccc"),
            _row("env", name=".env.production",
                 text=_dense_env_file_text(), sha="dddd"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["file_id"], "env")

    def test_density_metrics_are_attached_to_each_match(self):
        rows = [
            _row("dump", name="dump.txt",
                 text=_password_dump_text(), sha="bbbb"),
        ]
        m = vi.search_files_for_credentials_report(rows)["matches"][0]
        for key in (
            "credential_block_count",
            "service_count",
            "credential_density",
            "mostly_credentials",
        ):
            self.assertIn(key, m, f"match must carry {key}")
        self.assertTrue(m["mostly_credentials"])


class BestMatchLabelTests(unittest.TestCase):
    def test_clear_winner_gets_best_match_True(self):
        rows = [
            _row("sparse", name="handover.docx.pdf",
                 text=_sparse_password_in_prose(), sha="aaaa"),
            _row("dump", name="passed words 7425.docx.pdf",
                 text=_password_dump_text(), sha="bbbb"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        top = report["matches"][0]
        self.assertEqual(top["file_id"], "dump")
        self.assertTrue(top.get("best_match"),
            "a single mostly_credentials file with no near-tie "
            "competitor should be flagged as best_match")

    def test_two_similar_dumps_have_no_best_match(self):
                                                                   
                                                                   
        rows = [
            _row("dump_a", name="passwords_a.txt",
                 text=_password_dump_text(), sha="aaaa"),
            _row("dump_b", name="passwords_b.txt",
                 text=_password_dump_text(), sha="bbbb"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        for m in report["matches"]:
                                                           
            self.assertNotEqual(
                m.get("best_match"), True,
                "near-tied mostly_credentials rows must NOT flag "
                "best_match — the user should pick instead",
            )


class DuplicateCollapseTests(unittest.TestCase):
    def test_identical_reuploads_collapse_to_one(self):
        rows = [
            _row("a", name="passwords.txt",
                 text=_password_dump_text(), sha="sha-X"),
            _row("b", name="passwords.txt",
                 text=_password_dump_text(), sha="sha-X"),
            _row("c", name="passwords.txt",
                 text=_password_dump_text(), sha="sha-X"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        self.assertEqual(
            len(report["matches"]), 1,
            "three uploads of the same byte-identical file should "
            "collapse to one row in the disambiguation surface",
        )

    def test_same_name_different_sha_both_stay_for_path_disambiguate(self):
        rows = [
            _row("a", name="credentials.txt",
                 text=_password_dump_text(), sha="sha-A",
                 relative_path="Work/Old/credentials.txt"),
            _row("b", name="credentials.txt",
                 text=_password_dump_text(), sha="sha-B",
                 relative_path="Personal/Vault/credentials.txt"),
        ]
        report = vi.search_files_for_credentials_report(rows)
        self.assertEqual(
            len(report["matches"]), 2,
            "two truly-different files that happen to share a name "
            "must both stay so the card can disambiguate by path",
        )
                                                                 
                                         
        self.assertEqual(
            {m["relative_path"] for m in report["matches"]},
            {"Work/Old/credentials.txt", "Personal/Vault/credentials.txt"},
        )


class EnvelopeCarriesBestMatchTests(unittest.TestCase):
    def test_envelope_carries_best_match_and_density(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=[
                {
                    "file_id":              "dump",
                    "file_name":            "passwords.txt",
                    "confidence":           "strong",
                    "mostly_credentials":   True,
                    "best_match":           True,
                    "credential_density":   0.83,
                    "credential_block_count": 5,
                    "service_count":        5,
                    "reasons":              ["file appears to be mostly a credential list"],
                },
            ],
            title="Best match for credentials",
            message="msg",
            context_kind="credential_files",
        ))
        row = env["files"][0]
        self.assertEqual(row["best_match"], True)
        self.assertEqual(row["mostly_credentials"], True)
        self.assertAlmostEqual(row["credential_density"], 0.83, places=4)
        self.assertEqual(row["credential_block_count"], 5)
        self.assertEqual(row["service_count"], 5)

    def test_envelope_omits_density_fields_when_absent(self):
                                                                  
                                                            
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=[
                {
                    "file_id":   "f1",
                    "file_name": "x.pdf",
                    "confidence": "strong",
                    "reasons":   ["content contains repeated records"],
                },
            ],
            title="t",
            message="m",
            context_kind="credential_files",
        ))
        row = env["files"][0]
        self.assertNotIn("best_match", row)
        self.assertNotIn("mostly_credentials", row)
        self.assertNotIn("credential_density", row)


class SnapshotDensityTests(unittest.TestCase):
    def setUp(self):
        self.vault_id = f"vault-{time.time_ns()}"

    def tearDown(self):
        cm.clear_last_file_search_results(self.vault_id)

    def test_snapshot_carries_density_and_best_match(self):
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=[{
                "file_id":              "dump",
                "file_name":            "p.txt",
                "saved_name":           "",
                "relative_path":        "",
                "mime_type":            "text/plain",
                "confidence":           "strong",
                "reasons":              ["mostly credentials"],
                "credential_density":   0.83,
                "credential_block_count": 5,
                "service_count":        5,
                "mostly_credentials":   True,
                "best_match":           True,
            }],
        )
        out = cm.get_last_file_search_results(self.vault_id)
        row = out["results"][0]
        self.assertEqual(row["mostly_credentials"], True)
        self.assertEqual(row["best_match"], True)
        self.assertAlmostEqual(row["credential_density"], 0.83, places=4)
        self.assertEqual(row["credential_block_count"], 5)


class ResolverHonorsBestMatchTests(unittest.TestCase):
    def _ranked_results(self) -> list[dict]:
        return [
            {
                "file_id":            "dump",
                "file_name":          "passwords.txt",
                "saved_name":         "",
                "relative_path":      "",
                "mime_type":          "text/plain",
                "confidence":         "strong",
                "mostly_credentials": True,
                "best_match":         True,
                "credential_density": 0.83,
            },
            {
                "file_id":            "sparse",
                "file_name":          "handover.docx.pdf",
                "saved_name":         "",
                "relative_path":      "",
                "mime_type":          "application/pdf",
                "confidence":         "strong",
                "mostly_credentials": False,
                "credential_density": 0.02,
            },
        ]

    def test_the_one_with_everything_picks_best_match(self):
        action = fu.resolve_followup(
            "show me the one with everything in it",
            {"kind": "credential_files", "results": self._ranked_results()},
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["file_id"], "dump",
            "the resolver must honour best_match=True from the "
            "ranker — that's the user's intuition for 'the one "
            "with everything'")

    def test_bare_the_one_picks_best_match(self):
        action = fu.resolve_followup(
            "show me the one",
            {"kind": "credential_files", "results": self._ranked_results()},
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["file_id"], "dump")

    def test_two_mostly_credentials_no_winner_disambiguates(self):
                                                               
                                                             
        results = [
            {
                "file_id":            "a",
                "file_name":          "passwords_a.txt",
                "confidence":         "strong",
                "mostly_credentials": True,
                "credential_density": 0.80,
            },
            {
                "file_id":            "b",
                "file_name":          "passwords_b.txt",
                "confidence":         "strong",
                "mostly_credentials": True,
                "credential_density": 0.78,
            },
            {
                "file_id":            "sparse",
                "file_name":          "x.pdf",
                "confidence":         "strong",
                "mostly_credentials": False,
                "credential_density": 0.01,
            },
        ]
        action = fu.resolve_followup(
            "the one with everything",
            {"kind": "credential_files", "results": results},
        )
        self.assertEqual(action["action"], "disambiguate")
        ids = {f["file_id"] for f in action["files"]}
        self.assertEqual(ids, {"a", "b"},
            "disambiguation must be limited to the mostly_credentials "
            "shortlist — the sparse file shouldn't appear as a "
            "co-equal pick")

    def test_legacy_results_without_density_keep_existing_behavior(self):
                                                                 
                                                          
        results = [
            {"file_id": "a", "confidence": "strong"},
            {"file_id": "b", "confidence": "strong"},
        ]
        action = fu.resolve_followup(
            "the one with everything",
            {"kind": "credential_files", "results": results},
        )
                                                               
        self.assertEqual(action["action"], "disambiguate")
        self.assertEqual(len(action["files"]), 2)


class HandlerSelectsContentShaTests(unittest.TestCase):
    def test_credential_search_query_selects_content_sha256(self):
        import main
        src = inspect.getsource(
            main._list_uploaded_files_for_credential_search,
        )
        self.assertIn(
            "content_sha256", src,
            "the credential-search row reader must SELECT "
            "content_sha256 so the duplicate collapser can spot "
            "byte-identical re-uploads",
        )


if __name__ == "__main__":
    unittest.main()
