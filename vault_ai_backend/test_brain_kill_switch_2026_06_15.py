

from __future__ import annotations

import asyncio
import os
import re
import unittest
from unittest import mock


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_MAIN_PY = os.path.join(_BACKEND_DIR, "main.py")
_VAULT_CONFIG_PY = os.path.join(_BACKEND_DIR, "vault_config.py")


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_lines(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().splitlines()


def _run(coro):

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ChatPathDefaultDisabled(unittest.TestCase):


    def test_chat_endpoint_source_does_not_enter_brain_when_flag_false(self):
        text = _read_text(_MAIN_PY)
        lines = text.splitlines()

                                                  
        call_sites: list[int] = [
            idx for idx, line in enumerate(lines)
            if "from vault_brain_chat_pipeline import" in line
            or "run_brain_chat_pipeline" in line
        ]
                                                                      
                                                                     
        executable_sites = [
            idx for idx, line in enumerate(lines)
            if "from vault_brain_chat_pipeline import" in line
        ]
        self.assertGreater(
            len(executable_sites), 0,
            "expected at least one brain-chat-pipeline call site in main.py",
        )

                                                                      
        gate_pattern = re.compile(
            r"if\s+not\s+vault_brain_chat_enabled\(\)\s*:"
        )
        enabled_pattern = re.compile(
            r"vault_brain_chat_enabled\(\)"
        )
        for site in executable_sites:
            window = lines[max(0, site - 25):site + 1]
            window_text = "\n".join(window)
            self.assertRegex(
                window_text, enabled_pattern,
                (
                    "brain pipeline call at line %d is NOT wrapped in "
                    "a vault_brain_chat_enabled() gate" % (site + 1)
                ),
            )
                                                                  
                                                                   
            self.assertRegex(
                window_text, gate_pattern,
                (
                    "brain pipeline call at line %d lacks the "
                    "'if not vault_brain_chat_enabled():' kill switch"
                    % (site + 1)
                ),
            )

                                                                    
        self.assertIn(
            "from vault_config import vault_brain_chat_enabled", text,
            "main.py must import the vault_brain_chat_enabled flag",
        )


class ClassifyBrainIntentRejectsCreateCredentials(unittest.TestCase):


    def test_create_username_and_password_for_chase_bank_is_not_vault_content(self):
        from vault_brain_intent import (
            classify_brain_intent, NOT_VAULT_CONTENT,
        )
        decision = classify_brain_intent(
            "create username and password for my chase bank",
        )
        self.assertEqual(
            decision.intent, NOT_VAULT_CONTENT,
            "create/make/give-me phrasing must NOT enter the brain",
        )
        self.assertTrue(
            decision.reason.startswith("imperative_action"),
            (
                "expected reason to start with 'imperative_action', "
                "got %r" % decision.reason
            ),
        )


class CreateUsernamePasswordRoutesToGenerateLogin(unittest.TestCase):


    def test_intent_classifier_prompt_routes_create_username_password_to_generate_login(self):
        text = _read_text(_MAIN_PY)

                                                                   
        self.assertIn(
            '"create me a login for X"', text,
            "intent prompt must list 'create me a login for X'",
        )
        self.assertIn(
            '"make a username and password for X"', text,
            (
                "intent prompt must list "
                "'make a username and password for X'"
            ),
        )

                                                                    
        for needle in (
            '"create me a login for X"',
            '"make a username and password for X"',
        ):
            idx = text.find(needle)
            self.assertNotEqual(
                idx, -1, "needle %r not present in main.py" % needle,
            )
            line_end = text.find("\n", idx)
            line = text[idx:line_end if line_end != -1 else len(text)]
            self.assertIn(
                "generate_login", line,
                (
                    "prompt example %r must route to generate_login; "
                    "got: %r" % (needle, line)
                ),
            )
            self.assertIn(
                "parts_wanted", line,
                (
                    "prompt example %r must set parts_wanted; "
                    "got: %r" % (needle, line)
                ),
            )


class BrainIndexedZeroReturnsNoEvidence(unittest.TestCase):


    def test_run_brain_chat_pipeline_returns_handled_false_when_indexed_zero(self):
        from vault_brain_chat_pipeline import run_brain_chat_pipeline
        from vault_brain_coverage import BrainCoverage

                                                             
        zero_coverage = BrainCoverage(
            vault_id="v-zero",
            total_files=4,
            files_with_all_chunks_embedded=0,
            files_with_embedded_chunks=0,
        )

        async def _embed_should_not_be_called(text):
            raise AssertionError(
                "embed_fn must not run when brain indexed==0",
            )

        async def _retrieve_should_not_be_called(**kwargs):
            raise AssertionError(
                "retrieve_fn must not run when brain indexed==0",
            )

        decision = _run(run_brain_chat_pipeline(
            vault_id="v-zero",
            message="what does the contract say about termination?",
            key=b"\x00" * 32,
            embed_fn=_embed_should_not_be_called,
            coverage={"total": 4, "analyzed": 0, "scan_complete": False},
            brain_coverage_loader=lambda vid: zero_coverage,
            retrieve_fn=_retrieve_should_not_be_called,
        ))

        self.assertFalse(
            decision.handled,
            "indexed==0 MUST short-circuit to handled=False",
        )
                                                
        self.assertEqual(decision.reason, "brain_not_indexed_yet")


class EvidenceCardsDedupedByFileId(unittest.TestCase):


    def test_build_evidence_rows_collapses_multiple_chunks_to_one_row_per_file(self):
        import vault_brain_answerer as answerer
        from vault_evidence_bundle import EvidenceBundle, EvidenceChunk

        file_id = "file-AAA"
        chunks = tuple(
            EvidenceChunk(
                chunk_id="c-%d" % i,
                file_id=file_id,
                chunk_index=i,
                text="snippet text from chunk %d" % i,
                extraction_source="pdf_text",
                score=0.9 - 0.1 * i,
                char_start=0,
                char_end=24,
            )
            for i in range(3)
        )
        bundle = EvidenceBundle(
            query="contract",
            vault_id="v-1",
            chunks=chunks,
            matching_file_ids=(file_id,),
            coverage_at_time={},
        )

                                                                   
        with mock.patch(
            "vault_brain_answerer._lookup_file_content_hashes",
            return_value={},
        ):
            rows = answerer._build_evidence_rows(
                bundle,
                file_names={file_id: "contract.pdf"},
                max_rows=10,
                snippet_chars=120,
            )

        self.assertEqual(
            len(rows), 1,
            "three chunks of one file_id must collapse to ONE row",
        )
        self.assertEqual(rows[0].file_id, file_id)
                                     
        self.assertAlmostEqual(rows[0].score, 0.9, places=6)


class HermesResidentDispatcherNotCalled(unittest.TestCase):


    def test_no_hermes_resident_dispatcher_import_in_main(self):
        main_text = _read_text(_MAIN_PY)
        self.assertNotIn(
            "hermes_resident_chat_dispatcher", main_text,
            (
                "main.py still references hermes_resident_chat_dispatcher "
                "— the rollback was supposed to remove every call site."
            ),
        )

        config_text = _read_text(_VAULT_CONFIG_PY)
        self.assertNotIn(
            "hermes_resident_enabled", config_text,
            (
                "vault_config still exposes hermes_resident_enabled — "
                "it was removed in the cleanup turn."
            ),
        )


class NoVaultBrainCardInOpenAIOnlyMode(unittest.TestCase):


    def test_vault_brain_envelope_not_built_when_flag_false(self):
        text = _read_text(_MAIN_PY)
        lines = text.splitlines()

                                                  
        call_sites: list[int] = []
        for idx, line in enumerate(lines):
            if "_build_vault_brain_answer_envelope(" not in line:
                continue
                                                  
            stripped = line.lstrip()
            if stripped.startswith("def _build_vault_brain_answer_envelope"):
                continue
            call_sites.append(idx)

        self.assertGreater(
            len(call_sites), 0,
            (
                "expected at least one _build_vault_brain_answer_envelope "
                "call in main.py — the source-guard test cannot run on "
                "an empty set."
            ),
        )

        gate_pattern = re.compile(
            r"if\s+not\s+vault_brain_chat_enabled\(\)\s*:"
        )
        for site in call_sites:
                                                                    
                                                                   
            window = lines[max(0, site - 80):site + 1]
            window_text = "\n".join(window)
            self.assertRegex(
                window_text, gate_pattern,
                (
                    "_build_vault_brain_answer_envelope call at line %d "
                    "is reachable WITHOUT passing the "
                    "'if not vault_brain_chat_enabled():' gate"
                    % (site + 1)
                ),
            )
                                                                   
                                                                    
            self.assertIn(
                "from vault_brain_chat_pipeline import", window_text,
                (
                    "_build_vault_brain_answer_envelope at line %d is "
                    "not co-located with a vault_brain_chat_pipeline "
                    "import — the gate may not be guarding it." % (site + 1)
                ),
            )


if __name__ == "__main__":
    unittest.main()
