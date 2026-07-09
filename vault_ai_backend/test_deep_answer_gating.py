

from __future__ import annotations

import json
import unittest
from unittest import mock

from vault_deep_answer import reset_jobs_for_tests, get_job


class DeepAnswerGatingTests(unittest.TestCase):
    def setUp(self):
        reset_jobs_for_tests()

    def _stub_coverage(self, raw: dict):
        return mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value=raw,
        )

    def _stub_drains(self):
                                                                   
                                                               
        return mock.patch(
            "routes.deep_answer_routes._drain_fns",
            return_value={},
        )

    def _stub_final(self):
                                                                
                                                                
        return mock.patch(
            "routes.deep_answer_routes._final_results_fn",
            return_value={
                "envelope": {"type": "credential_files",
                             "files": [],
                             "sections": {"confirmed": [],
                                          "possible": [],
                                          "filename_only": []},
                             "has_content_matches": False},
                "intent": "search_files_for_credentials",
            },
        )

    def test_gate_returns_none_for_non_deep_intent(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage({"total": 10, "analyzed": 0,
                                  "pending": 10}):
            out = _maybe_build_deep_answer_envelope(
                vault_id="v1", intent="save_login", query="x",
                key=b"k" * 32,
            )
        self.assertIsNone(out)

    def test_gate_returns_none_when_vault_is_empty(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage({"total": 0}):
            out = _maybe_build_deep_answer_envelope(
                vault_id="v1",
                intent="search_files_for_credentials",
                query="x", key=b"k" * 32,
            )
        self.assertIsNone(out)

    def test_gate_returns_none_when_coverage_is_complete(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage(
            {"total": 10, "analyzed": 10},
        ):
            out = _maybe_build_deep_answer_envelope(
                vault_id="v1",
                intent="search_files_for_credentials",
                query="x", key=b"k" * 32,
            )
        self.assertIsNone(out)

    def test_gate_returns_none_when_key_is_missing(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage(
            {"total": 10, "analyzed": 5, "pending": 5},
        ):
            out = _maybe_build_deep_answer_envelope(
                vault_id="v1",
                intent="search_files_for_credentials",
                query="x", key=None,
            )
        self.assertIsNone(
            out,
            "missing key must NOT enqueue a deep job — the "
            "drains would just no-op",
        )

    def test_gate_returns_none_above_coverage_threshold(self):
        from main import _maybe_build_deep_answer_envelope
                                                           
        with self._stub_coverage(
            {"total": 100, "analyzed": 96, "pending": 4},
        ):
            out = _maybe_build_deep_answer_envelope(
                vault_id="v1",
                intent="search_files_for_credentials",
                query="x", key=b"k" * 32,
            )
        self.assertIsNone(out)

    def test_gate_fires_for_incomplete_credential_coverage(self):
        from main import _maybe_build_deep_answer_envelope
                                                      
        with self._stub_coverage(
            {"total": 256, "analyzed": 42,
             "pending": 200, "processing": 14},
        ), self._stub_drains(), self._stub_final():
            out = _maybe_build_deep_answer_envelope(
                vault_id="vault-deep",
                intent="search_files_for_credentials",
                query="show me files that have credentials saved in it",
                key=b"k" * 32,
            )
        self.assertIsNotNone(out)
        payload = json.loads(out)
        self.assertEqual(payload["type"], "deep_answer_progress")
        self.assertIn("job_id", payload)
        self.assertIn("progress", payload)
                                               
        self.assertEqual(
            set(payload.keys()),
            {"type", "message", "job_id", "intent", "status",
             "progress", "results"},
        )
                                                                 
                                  
        job = get_job("vault-deep", payload["job_id"])
        self.assertIsNotNone(job)

    def test_gate_envelope_never_carries_credential_values(self):
        from main import _maybe_build_deep_answer_envelope
        with self._stub_coverage(
            {"total": 256, "analyzed": 42,
             "pending": 200, "processing": 14},
        ), self._stub_drains(), self._stub_final():
            out = _maybe_build_deep_answer_envelope(
                vault_id="vault-leak-probe",
                intent="search_files_for_credentials",
                query="x", key=b"k" * 32,
            )
        self.assertIsNotNone(out)
                                                                   
        for leak in ("hunter2", "tok-secret", "password=",
                     "BEGIN PRIVATE KEY"):
            self.assertNotIn(leak, out,
                f"deep-answer envelope leaked sentinel: {leak!r}")

    def test_gate_fires_for_every_deep_intent_in_registry(self):
        from main import _maybe_build_deep_answer_envelope
        from vault_deep_answer import DEEP_REQUIRED_INTENTS
        for intent in DEEP_REQUIRED_INTENTS:
            with self.subTest(intent=intent):
                reset_jobs_for_tests()
                with self._stub_coverage(
                    {"total": 100, "analyzed": 10, "pending": 90},
                ), self._stub_drains(), self._stub_final():
                    out = _maybe_build_deep_answer_envelope(
                        vault_id="v-rotate",
                        intent=intent, query="", key=b"k" * 32,
                    )
                self.assertIsNotNone(
                    out,
                    f"gate must fire for deep intent {intent!r}",
                )

    def test_chat_handler_no_longer_auto_gates_credentials_to_deep_answer(self):


        import inspect
        import main
        src = inspect.getsource(main)
        branch_start = src.find('if intent == "search_files_for_credentials":')
        self.assertGreater(branch_start, -1)
        branch_end = src.find(
            'if intent == "extract_logins_from_file"', branch_start,
        )
        body = src[branch_start:branch_end]
        self.assertNotIn(
            "_maybe_build_deep_answer_envelope(", body,
            "credential search branch must NOT auto-gate to the "
            "deep-answer envelope in normal chat mode — that surfaced "
            "stale 'Scanning your vault... 194 of 425 files read so "
            "far' wording AND skipped storing LastAssistantResult.",
        )
        verifier_idx = body.find("verified_credential_files_report")
        self.assertGreater(
            verifier_idx, -1,
            "credential branch must still call the strict verifier.",
        )

    def test_chat_handler_stores_last_assistant_result_before_returning(self):


        import inspect, main
        src = inspect.getsource(main)
        branch_start = src.find('if intent == "search_files_for_credentials":')
        branch_end = src.find('if intent == "extract_logins_from_file"', branch_start)
        body = src[branch_start:branch_end]
        self.assertIn(
            "make_credential_search_result", body,
            "credential branch must build a credential_search "
            "LastAssistantResult shape.",
        )
        self.assertIn(
            "set_last_assistant_result", body,
            "credential branch must store the LastAssistantResult "
            "before returning so the Phase 2 follow-up classifier "
            "has context to ground on.",
        )


class ChatGateThreadsEnqueueMissingFnTests(unittest.TestCase):


    def setUp(self):
        reset_jobs_for_tests()

    def test_source_passes_enqueue_missing_fn_to_step(self):
        import inspect, main
        src = inspect.getsource(main._maybe_build_deep_answer_envelope)
        self.assertIn("_enqueue_missing_fn", src,
            "chat-side gate must import the enqueue helper")
        self.assertIn("enqueue_missing_fn=_da_enqueue_missing_fn", src,
            "chat-side gate must pass enqueue_missing_fn to "
            "step_deep_answer or the FIRST envelope ships with "
            "blocker_reason set and the frontend renders 'not moving'")

    def test_gate_actually_calls_enqueue_missing_fn(self):


        from main import _maybe_build_deep_answer_envelope
        seen = {"calls": 0, "vault_id": None}

        def fake_enq(vault_id):
            seen["calls"] += 1
            seen["vault_id"] = vault_id
            return {"enqueued": 7, "considered": 7,
                    "skipped_unsupported": 0, "by_stage": {},
                    "error": None}

        with mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={"total": 256, "analyzed": 0,
                          "pending": 0, "not_started": 256,
                          "processing": 0},
        ), mock.patch(
            "routes.deep_answer_routes._drain_fns",
            return_value={},
        ), mock.patch(
            "routes.deep_answer_routes._final_results_fn",
            return_value={"envelope": None, "intent": "search_files_for_credentials"},
        ), mock.patch(
            "routes.deep_answer_routes._enqueue_missing_fn",
            side_effect=fake_enq,
        ):
            out = _maybe_build_deep_answer_envelope(
                vault_id="vault-enqueue-trace",
                intent="search_files_for_credentials",
                query="show me my passwords",
                key=b"k" * 32,
            )
        self.assertIsNotNone(out)
        self.assertGreaterEqual(seen["calls"], 1,
            "chat-side gate must invoke the enqueue helper at "
            "least once — otherwise the queue stays empty on the "
            "first render and the envelope ships with blocker_reason")
        self.assertEqual(seen["vault_id"], "vault-enqueue-trace")

    def test_first_envelope_does_not_carry_queue_empty_blocker(self):


        from main import _maybe_build_deep_answer_envelope

        def working_enq(vault_id):
            return {"enqueued": 425, "considered": 425,
                    "skipped_unsupported": 0, "by_stage": {},
                    "error": None}

                                                              
        from vault_deep_answer import required_stages_for_intent
        required = required_stages_for_intent(
            "search_files_for_credentials",
        )
                                                                     
                                                                     
        def _stub_drain(*, vault_id, key, max_jobs):
            return {"processed": 1, "succeeded": 1, "failed": 0,
                    "drained_at": "x"}
        stub_drains = {s: _stub_drain for s in required}

        with mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            side_effect=[
                                                  
                {"total": 425, "analyzed": 0,
                 "pending": 0, "not_started": 425, "processing": 0},
                                                                   
                {"total": 425, "analyzed": 0,
                 "pending": 0, "not_started": 425, "processing": 0},
                                                                
                {"total": 425, "analyzed": 0,
                 "pending": 425, "not_started": 0, "processing": 0},
                                                                    
                                      
                {"total": 425, "analyzed": 1,
                 "pending": 424, "not_started": 0, "processing": 0},
            ],
        ), mock.patch(
            "routes.deep_answer_routes._drain_fns",
            return_value=stub_drains,
        ), mock.patch(
            "routes.deep_answer_routes._final_results_fn",
            return_value={"envelope": None,
                          "intent": "search_files_for_credentials"},
        ), mock.patch(
            "routes.deep_answer_routes._enqueue_missing_fn",
            side_effect=working_enq,
        ):
            out = _maybe_build_deep_answer_envelope(
                vault_id="vault-first-envelope",
                intent="search_files_for_credentials",
                query="find my credentials",
                key=b"k" * 32,
            )
        self.assertIsNotNone(out)
        payload = json.loads(out)
        progress = payload.get("progress") or {}
        self.assertIsNone(
            progress.get("blocker_reason"),
            "FIRST envelope must NOT ship with blocker_reason set "
            "— the chat-handler step ran enqueue (so the queue is no "
            "longer empty) and drains-return-zero is fine on this "
            "step because we just enqueued. Without the fix, the "
            "engine sets blocker_reason='queue_empty_but_coverage_"
            "pending' and the user sees 'I couldn't finish checking "
            "the vault because file analysis is not moving' on the "
            "very first render. Got blocker_reason=%r"
            % progress.get("blocker_reason"),
        )
                                                              
        self.assertGreater(
            int(progress.get("jobs_enqueued") or 0), 0,
            "chat-side gate must report jobs_enqueued > 0 so the "
            "debug surface tells the operator the engine moved",
        )


class DeepAnswerRouteSafetyTests(unittest.TestCase):


    def test_routes_module_returns_404_on_wrong_vault(self):
        import inspect
        from routes import deep_answer_routes
        src = inspect.getsource(deep_answer_routes)
                                                               
                                                                  
        self.assertIn("get_job(vault_id, job_id)", src)
        self.assertIn("status_code=404", src)
        self.assertIn("deep_answer_job_not_found", src)

    def test_routes_module_threads_pin_through_to_drain_key(self):
                                                             
                                                                
        import inspect
        from routes import deep_answer_routes
        src = inspect.getsource(deep_answer_routes)
        self.assertIn("get_verified_vault_key(vault_id, payload.pin)", src)
        self.assertIn("step_deep_answer(", src)

    def test_routes_register_under_vault_analysis_prefix(self):
                                                                
                                                                  
        import inspect
        from routes import deep_answer_routes
        src = inspect.getsource(deep_answer_routes)
        self.assertIn('"/vault-analysis/deep-answer"', src)
        self.assertIn(
            '"/vault-analysis/deep-answer/{job_id}/poll"',
            src,
        )


if __name__ == "__main__":
    unittest.main()
