

from __future__ import annotations

import unittest

from vault_brain_answerer import (
    compose_brain_answer,
    BrainAnswer,
    EvidenceRow,
    COPY_NO_EVIDENCE,
    COPY_PENDING_HINT,
    COPY_FAILED_HINT,
    COPY_UNSUPPORTED_HINT,
)
from vault_brain_intent import (
    SEARCH_VAULT_CONTENT,
    ANSWER_FROM_VAULT_CONTENT,
    ANSWER_FROM_FILE_CONTENT,
    SUMMARIZE_FILE_CONTENT,
    SUMMARIZE_FOLDER_CONTENT,
    CREDENTIAL_LOOKUP,
    NOT_VAULT_CONTENT,
)
from vault_evidence_bundle import (
    EvidenceBundle, EvidenceChunk, empty_bundle,
)


def _chunk(*, file_id: str, idx: int = 0, text: str = "snippet",
           source: str = "pdf_text", score: float = 0.8) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=f"c-{file_id}-{idx}",
        file_id=file_id,
        chunk_index=idx,
        text=text,
        extraction_source=source,
        score=score,
        char_start=0,
        char_end=len(text),
    )


def _bundle(*, chunks, file_ids=None, coverage=None,
            mode="semantic",
            excluded_pending=0, excluded_failed=0,
            excluded_unsupported=0) -> EvidenceBundle:
    return EvidenceBundle(
        query="redacted",
        vault_id="v-1",
        chunks=tuple(chunks),
        matching_file_ids=tuple(file_ids or
                                list({c.file_id for c in chunks})),
        coverage_at_time=dict(coverage or {}),
        retrieval_mode=mode,
        excluded_pending=excluded_pending,
        excluded_failed=excluded_failed,
        excluded_unsupported=excluded_unsupported,
    )


def _names(name_map):


    def _lookup(file_ids):
        return {fid: name_map.get(fid, fid[:8]) for fid in file_ids}
    return _lookup


class NoEvidenceTests(unittest.TestCase):
    def test_empty_bundle_returns_no_evidence_copy(self):
        bundle = _bundle(chunks=[])
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({}),
        )
        self.assertTrue(answer.handled)
        self.assertTrue(answer.no_evidence)
        self.assertIn(COPY_NO_EVIDENCE, answer.reply_body)

    def test_pending_hint_appended_when_some_files_pending(self):
        bundle = _bundle(chunks=[], excluded_pending=3)
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({}),
        )
        self.assertIn(COPY_PENDING_HINT, answer.reply_body)
        self.assertIn(COPY_NO_EVIDENCE, answer.reply_body)

    def test_failed_hint_appended_when_some_files_failed(self):
        bundle = _bundle(chunks=[], excluded_failed=1)
        answer = compose_brain_answer(
            intent=ANSWER_FROM_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({}),
        )
        self.assertIn(COPY_FAILED_HINT, answer.reply_body)

    def test_unsupported_hint_appended_when_some_files_unsupported(self):
        bundle = _bundle(chunks=[], excluded_unsupported=2)
        answer = compose_brain_answer(
            intent=ANSWER_FROM_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({}),
        )
        self.assertIn(COPY_UNSUPPORTED_HINT, answer.reply_body)

    def test_pending_hint_wins_over_failed_and_unsupported(self):
        bundle = _bundle(
            chunks=[], excluded_pending=1,
            excluded_failed=1, excluded_unsupported=1,
        )
        answer = compose_brain_answer(
            intent=ANSWER_FROM_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({}),
        )
        self.assertIn(COPY_PENDING_HINT, answer.reply_body)
        self.assertNotIn(COPY_FAILED_HINT, answer.reply_body)


class SearchVaultContentTests(unittest.TestCase):
    def test_one_file_match_renders_yes_with_filename(self):
        ch = _chunk(
            file_id="f-1", text="The blue contract expires on 2027-08-19.",
        )
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "contract-2027.pdf"}),
        )
        self.assertIn("contract-2027.pdf", answer.reply_body)
        self.assertIn("blue contract", answer.reply_body)
        self.assertFalse(answer.no_evidence)

    def test_multiple_files_render_count_and_names(self):
        c1 = _chunk(file_id="f-1", text="ally bank statement, may 2024")
        c2 = _chunk(file_id="f-2", text="ally savings account terms")
        bundle = _bundle(chunks=[c1, c2])
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({
                "f-1": "ally-may-2024.pdf",
                "f-2": "ally-savings.pdf",
            }),
        )
        self.assertIn("2 files", answer.reply_body)
        self.assertIn("ally-may-2024.pdf", answer.reply_body)
        self.assertIn("ally-savings.pdf", answer.reply_body)


class AnswerFromVaultContentTests(unittest.TestCase):
    def test_renders_top_snippet_with_filename(self):
        ch = _chunk(
            file_id="f-1",
            text="Routing number: 124003116. Account: ****1234.",
            score=0.9,
        )
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=ANSWER_FROM_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "ally-routing.pdf"}),
        )
        self.assertIn("ally-routing.pdf", answer.reply_body)
        self.assertIn("Routing number", answer.reply_body)
        self.assertIn(">", answer.reply_body,
                      "snippet should be quoted with markdown blockquote")

    def test_intent_is_propagated(self):
        ch = _chunk(file_id="f-1")
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=ANSWER_FROM_FILE_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "x.pdf"}),
        )
        self.assertEqual(answer.intent, ANSWER_FROM_FILE_CONTENT)


class SummarizeTests(unittest.TestCase):
    def test_folder_summary_uses_folder_header(self):
        ch = _chunk(file_id="f-1", text="Lease term: 12 months.")
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=SUMMARIZE_FOLDER_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "lease.pdf"}),
        )
        self.assertIn("folder", answer.reply_body.lower())
        self.assertIn("Lease term", answer.reply_body)

    def test_file_summary_uses_file_header(self):
        ch = _chunk(file_id="f-1", text="Section 1: Tenant duties.")
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=SUMMARIZE_FILE_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "lease.pdf"}),
        )
        self.assertIn("file", answer.reply_body.lower())
        self.assertIn("Tenant duties", answer.reply_body)


class CredentialLookupTests(unittest.TestCase):


    def test_chunk_with_credentials_is_verified(self):
        ch = _chunk(
            file_id="f-1",
            text=(
                "Chase\nusername: alice@example.com\npassword: hunter22\n"
            ),
        )
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=CREDENTIAL_LOOKUP, bundle=bundle,
            file_name_lookup=_names({"f-1": "logins.txt"}),
        )
                                   
        self.assertIn("Chase", answer.reply_body)
                                                 
        self.assertNotIn("hunter22", answer.reply_body)
                                  
        self.assertIn("logins.txt", answer.reply_body)

    def test_chunk_without_credentials_returns_honest_no_credential(self):
        ch = _chunk(
            file_id="f-1",
            text="My favourite colour is blue.",
        )
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=CREDENTIAL_LOOKUP, bundle=bundle,
            file_name_lookup=_names({"f-1": "notes.txt"}),
        )
                                                                       
        self.assertIn("doesn't look like", answer.reply_body)
        self.assertIn("notes.txt", answer.reply_body)


class IntentRefusalTests(unittest.TestCase):


    def test_non_brain_intent_refused(self):
        bundle = _bundle(chunks=[_chunk(file_id="f-1")])
        answer = compose_brain_answer(
            intent=NOT_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "x.pdf"}),
        )
        self.assertFalse(answer.handled)
        self.assertEqual(answer.reply_body, "")


class EvidenceRowShapeTests(unittest.TestCase):
    def test_rows_carry_file_name_and_truncated_snippet(self):
        ch = _chunk(file_id="f-1", text="a" * 500)
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "long.pdf"}),
            snippet_chars=240,
        )
        self.assertEqual(len(answer.evidence_rows), 1)
        row = answer.evidence_rows[0]
        self.assertEqual(row.file_id, "f-1")
        self.assertEqual(row.file_name, "long.pdf")
                                                         
        self.assertLessEqual(len(row.snippet), 241)
        self.assertTrue(row.snippet.endswith("…"))

    def test_rows_are_capped_at_max_rows(self):
        chunks = [
            _chunk(file_id=f"f-{i}", text=f"snippet {i}")
            for i in range(10)
        ]
        bundle = _bundle(chunks=chunks)
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({f"f-{i}": f"n{i}" for i in range(10)}),
            max_rows=3,
        )
        self.assertEqual(len(answer.evidence_rows), 3)

    def test_unknown_file_id_falls_back_to_truncated_id(self):
        ch = _chunk(file_id="abcd1234ef", text="hi")
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({}),                            
        )
        self.assertTrue(answer.evidence_rows[0].file_name.startswith("abcd1234"))


class ToDictTests(unittest.TestCase):
    def test_to_dict_has_closed_set_keys(self):
        ch = _chunk(file_id="f-1", text="snippet")
        bundle = _bundle(chunks=[ch])
        answer = compose_brain_answer(
            intent=SEARCH_VAULT_CONTENT, bundle=bundle,
            file_name_lookup=_names({"f-1": "x.pdf"}),
        )
        d = answer.to_dict()
        expected = {
            "handled", "reply_body", "evidence_rows",
            "intent", "no_evidence", "coverage_note", "reason",
        }
        self.assertEqual(set(d.keys()), expected)
        self.assertIsInstance(d["evidence_rows"], list)
        self.assertIsInstance(d["evidence_rows"][0], dict)


if __name__ == "__main__":
    unittest.main()
