from __future__ import annotations

import asyncio
import json
import logging
import unittest

from vault_memory_answer_composer import (
    build_vault_memory_facts,
    compose_vault_memory_answer,
)
from vault_brain_answerer import EvidenceRow
from vault_evidence_bundle import EvidenceBundle, EvidenceChunk


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _chunk(file_id: str, text: str, *, chunk_id: str = "c-1"):
    return EvidenceChunk(
        chunk_id=chunk_id,
        file_id=file_id,
        chunk_index=0,
        text=text,
        extraction_source="file_text",
        score=0.95,
        char_start=0,
        char_end=len(text),
    )


def _bundle(*, vault_id="v-1", chunks=(), coverage=None):
    return EvidenceBundle(
        query="are these the only files?",
        vault_id=vault_id,
        chunks=tuple(chunks),
        matching_file_ids=tuple(dict.fromkeys(c.file_id for c in chunks)),
        coverage_at_time=dict(coverage or {}),
        retrieval_mode="credential_memory_scan",
    )


def _row(file_id: str, file_name: str, snippet: str = "redacted"):
    return EvidenceRow(
        file_id=file_id,
        file_name=file_name,
        snippet=snippet,
        extraction_source="file_text",
        score=0.95,
        chunk_index=0,
    )


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, outer):
        self.outer = outer

    async def create(self, **kwargs):
        self.outer.calls.append(kwargs)
        facts = json.loads(kwargs["messages"][1]["content"])
        cov = facts["coverage"]
        if facts["verified_record_count"] and not cov["is_complete"]:
            return _Resp(
                "No, I can't confirm those are the only credential files "
                f"yet. I found {facts['matching_file_count']} verified "
                f"credential files from {cov['analyzed_files']} readable "
                f"files out of {cov['total_files']} total. "
                f"Pending: {cov['pending_files']}; unsupported: "
                f"{cov['unsupported_files']}. Files: "
                + ", ".join(f["file_name"] for f in facts["matching_files"])
            )
        if facts["verified_record_count"] and cov["is_complete"]:
            return _Resp(
                "Yes, these are the only verified credential files in the "
                "currently complete vault index: "
                + ", ".join(f["file_name"] for f in facts["matching_files"])
            )
        return _Resp("I found no verified credential files in the evidence.")


class _Chat:
    def __init__(self, outer):
        self.completions = _Completions(outer)


class _Client:
    def __init__(self):
        self.calls = []
        self.chat = _Chat(self)


class ComposerFactsTests(unittest.TestCase):
    def test_credential_facts_are_structured_and_secrets_redacted(self):
        ch = _chunk(
            "f-1",
            "Gmail\nusername: alice@example.com\npassword: super-secret\n",
        )
        bundle = _bundle(
            chunks=(ch,),
            coverage={
                "total": 425,
                "analyzed": 245,
                "pending": 51,
                "unsupported": 129,
                "failed": 0,
            },
        )
        facts = build_vault_memory_facts(
            user_question="are these the only files?",
            intent="credential_lookup",
            bundle=bundle,
            evidence_rows=(
                _row("f-1", "gmail.html", ch.text),
            ),
            authorized_unlocked=True,
        )

        self.assertTrue(facts["authorized_unlocked"])
        self.assertEqual(facts["vault_id"], "v-1")
        self.assertEqual(facts["verified_record_count"], 1)
        self.assertEqual(facts["matching_files"][0]["file_name"], "gmail.html")
        dumped = json.dumps(facts)
        self.assertNotIn("super-secret", dumped)
        self.assertIn("password", facts["verified_records"][0]["secret_fields_present"])

    def test_filename_only_credential_word_is_not_a_verified_record(self):
        ch = _chunk("f-1", "ordinary project notes without login fields")
        facts = build_vault_memory_facts(
            user_question="find credential files",
            intent="credential_lookup",
            bundle=_bundle(chunks=(ch,)),
            evidence_rows=(_row("f-1", "passwords.html", ch.text),),
            authorized_unlocked=True,
        )
        self.assertEqual(facts["verified_record_count"], 0)

    def test_user_question_is_redacted_in_composer_packet(self):
        facts = build_vault_memory_facts(
            user_question="is my password: question-secret in the vault?",
            intent="credential_lookup",
            bundle=_bundle(chunks=()),
            evidence_rows=(),
            authorized_unlocked=True,
        )
        self.assertNotIn("question-secret", json.dumps(facts))

    def test_incomplete_coverage_drives_not_only_answer(self):
        client = _Client()
        ch = _chunk("f-1", "Gmail\nusername: a@example.com\npassword: p1\n")
        reply = _run(compose_vault_memory_answer(
            openai_client=client,
            user_question="are these both the only files with credentials?",
            intent="credential_lookup",
            bundle=_bundle(
                chunks=(ch,),
                coverage={
                    "total": 425, "analyzed": 245,
                    "pending": 51, "unsupported": 129, "failed": 0,
                },
            ),
            evidence_rows=(_row("f-1", "gmail.html", ch.text),),
            authorized_unlocked=True,
        ))
        self.assertIn("can't confirm", reply)
        self.assertIn("425", reply)
        self.assertIn("51", reply)

    def test_empty_incomplete_facts_disallow_negative_claim(self):
        facts = build_vault_memory_facts(
            user_question="are there credential files?",
            intent="credential_lookup",
            bundle=_bundle(
                chunks=(),
                coverage={
                    "total": 425, "analyzed": 0,
                    "pending": 154, "unsupported": 40, "failed": 37,
                },
            ),
            evidence_rows=(),
            authorized_unlocked=True,
        )
        self.assertFalse(facts["negative_claim_allowed"])
        self.assertIn("does not prove", facts["empty_evidence_meaning"])

    def test_complete_coverage_can_confirm_only_files(self):
        client = _Client()
        ch = _chunk("f-1", "Gmail\nusername: a@example.com\npassword: p1\n")
        reply = _run(compose_vault_memory_answer(
            openai_client=client,
            user_question="are these both the only files with credentials?",
            intent="credential_lookup",
            bundle=_bundle(
                chunks=(ch,),
                coverage={
                    "total": 1, "analyzed": 1,
                    "pending": 0, "unsupported": 0, "failed": 0,
                },
            ),
            evidence_rows=(_row("f-1", "gmail.html", ch.text),),
            authorized_unlocked=True,
        ))
        self.assertIn("only verified credential files", reply)

    def test_unauthorized_content_is_rejected_before_llm(self):
        client = _Client()
        with self.assertRaises(PermissionError):
            _run(compose_vault_memory_answer(
                openai_client=client,
                user_question="what is in vault?",
                intent="credential_lookup",
                bundle=_bundle(chunks=()),
                evidence_rows=(),
                authorized_unlocked=False,
            ))
        self.assertEqual(client.calls, [])

    def test_no_plaintext_passwords_in_logs_on_llm_failure(self):
        class _BadCompletions:
            async def create(self, **_kwargs):
                raise RuntimeError("boom")

        class _BadClient:
            class chat:
                completions = _BadCompletions()

        captured = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        cap = _Cap()
        logging.getLogger("vault_memory_answer_composer").addHandler(cap)
        try:
            ch = _chunk("f-1", "Gmail\npassword: never-log-this\n")
            with self.assertRaises(RuntimeError):
                _run(compose_vault_memory_answer(
                    openai_client=_BadClient(),
                    user_question="find credentials",
                    intent="credential_lookup",
                    bundle=_bundle(chunks=(ch,)),
                    evidence_rows=(_row("f-1", "gmail.html", ch.text),),
                    authorized_unlocked=True,
                ))
        finally:
            logging.getLogger("vault_memory_answer_composer").removeHandler(cap)

        self.assertNotIn("never-log-this", "\n".join(captured))


if __name__ == "__main__":
    unittest.main()
