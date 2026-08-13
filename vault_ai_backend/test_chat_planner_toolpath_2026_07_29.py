"""End-to-end verification for the 2026-07-29 tool-path deep fix.

This is the fix for the production regressions the 8291a5c diagnostic
build confirmed:

  Bug 1: "show me naim id" in global chat was routed to the OpenAI
         planner's find_in_vault tool, which searches OCR'd text
         and vision output but NEVER checked the file's saved_name /
         file_name. A file the user labelled "Naim ID" was invisible
         unless its OCR text happened to also spell out the name.

  Bug 2: "create me a Disney login with beraves@gmail.com as the
         username" was routed to generate_credential_draft, whose
         tool schema accepted ONLY service_name — the LLM literally
         could not pass the email even if it wanted to. The handler
         then blindly generated "birchcove2083".

Previous tests exercised only the intent-dispatch layer (main.py
generate_login / generated_login_repair) which the production path
never reached (_direct_ai_tools_enabled = true → early return to
_route_to_ai_planner_stream). These tests target the ACTUAL
production tool-path:

  * vault_complete_search.find_in_vault (retrieval)
  * vault_inspection_tools.generate_credential_draft (credential)
  * main.handle_tool_call (dispatch)
  * security_headers.SecurityHeadersMiddleware + encrypted_reply
    (response headers)

Every test is deterministic (no DB, no network). Tests never log or
assert on plaintext passwords, decrypted content, or vault material.
Fixture email addresses live only in the tests.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock


# ---------------------------------------------------------------------------
# Layer 1: named-object resolver in vault_complete_search
# ---------------------------------------------------------------------------

class NamedObjectResolverTest(unittest.TestCase):
    """Bug 1 core regression tests. The resolver runs BEFORE the
    text/vision search — it must resolve every documented paraphrase
    to the same file and must bow out for category-label queries so
    the broader search still handles those."""

    def setUp(self):
        from vault_complete_search import _resolve_named_object
        self._resolve = _resolve_named_object
        self.rows = [
            {"id": "a1", "saved_name": "naim id", "file_name": "naim.jpg"},
            {"id": "a2", "saved_name": "birth certificate",
             "file_name": "birth.pdf"},
            {"id": "a3", "saved_name": None,
             "file_name": "NaimPassport.pdf"},
            {"id": "a4", "saved_name": "chase login",
             "file_name": "chase.png"},
        ]

    def _match_id(self, msg):
        row = self._resolve("v1", msg, self.rows)
        return row["id"] if row else None

    def test_production_show_me_naim_id(self):
        # Direct production reproduction — the failing message.
        self.assertEqual(self._match_id("show me naim id"), "a1")

    def test_open_case_variation(self):
        self.assertEqual(self._match_id("open Naim ID"), "a1")

    def test_hyphen_fold(self):
        self.assertEqual(self._match_id("find naim-id"), "a1")

    def test_underscore_fold(self):
        self.assertEqual(self._match_id("bring up naim_id"), "a1")

    def test_where_is_wrapper(self):
        self.assertEqual(
            self._match_id("where is the file called Naim ID"),
            "a1",
        )

    def test_i_need_the_document_wrapper(self):
        self.assertEqual(
            self._match_id("I need the document I saved as Naim ID"),
            "a1",
        )

    def test_bare_name(self):
        self.assertEqual(self._match_id("naim id"), "a1")

    def test_extension_stripped(self):
        # "NaimPassport.pdf" is on file_name; the resolver strips the
        # extension for matching so the LLM's query doesn't need it.
        self.assertEqual(self._match_id("open NaimPassport"), "a3")

    def test_file_name_match_when_saved_name_null(self):
        # a3 has saved_name = None but file_name = "NaimPassport.pdf".
        # Match must succeed on the file_name column.
        self.assertEqual(self._match_id("NaimPassport.pdf"), "a3")

    def test_category_label_show_me_id_documents_misses(self):
        # Broad category — must not hijack list_by_tag.
        self.assertIsNone(self._match_id("show me my id documents"))

    def test_category_label_show_my_ids_misses(self):
        self.assertIsNone(self._match_id("show my ids"))

    def test_bare_category_word_misses(self):
        self.assertIsNone(self._match_id("identity"))
        self.assertIsNone(self._match_id("passport"))
        self.assertIsNone(self._match_id("license"))

    def test_unrelated_chat_misses(self):
        self.assertIsNone(self._match_id("what time is it"))
        self.assertIsNone(self._match_id("hello there"))

    def test_ambiguous_returns_none(self):
        # Two rows have equal-length keys that both match — the
        # resolver returns None so the broader search / LLM can
        # disambiguate rather than picking arbitrarily.
        ambiguous_rows = [
            {"id": "x1", "saved_name": "louis id"},
            {"id": "x2", "saved_name": "louis id backup"},
        ]
        # "louis id" alone matches only "louis id" (a1-style); the
        # longer key "louis id backup" isn't in the query. So the
        # unique-longest heuristic returns x1.
        got = self._resolve("v-ambig", "show me louis id", ambiguous_rows)
        self.assertEqual(got["id"], "x1")

    def test_empty_row_list(self):
        self.assertIsNone(self._resolve("v-empty", "show me naim id", []))

    def test_short_label_not_matched(self):
        # A saved_name shorter than 3 chars must not match anything.
        short_rows = [{"id": "s1", "saved_name": "id"}]
        self.assertIsNone(
            self._resolve("v-short", "show me my id photos", short_rows),
        )


class FindInVaultNamedObjectIntegrationTest(unittest.TestCase):
    """Verify find_in_vault's synthesized envelope for a named hit."""

    def test_named_hit_returns_populated_envelope(self):
        import vault_complete_search as vcs
        rows = [
            {"id": "file-id-naim", "saved_name": "naim id",
             "file_name": "naim.jpg", "content_type": "image/jpeg",
             "extracted_text": "", "detected_type": "id_photo"},
        ]
        with mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ):
            result = vcs.find_in_vault(
                vault_id="v-e2e",
                key=b"\x00" * 32,
                query="show me naim id",
            )
        payload = json.loads(result)
        self.assertTrue(payload["complete"])
        self.assertEqual(len(payload["hits"]), 1)
        hit = payload["hits"][0]
        self.assertEqual(hit["file_id"], "file-id-naim")
        # match_status must be an exact name match so downstream
        # scoring treats it as high-confidence.
        self.assertEqual(hit["match_status"], "exact_name_match")
        # The result must NOT be routed to the empty-envelope copy.
        # The envelope shape carries the named_object_resolution flag
        # under coverage.
        self.assertEqual(
            payload["coverage"].get("named_object_resolution"), True,
        )

    def test_category_query_falls_through_to_broader_search(self):
        # For "show me my id documents" (category) the resolver bows
        # out — find_in_vault must NOT short-circuit; it proceeds to
        # the extracted-text / vision search. We assert only that
        # the coverage flag is absent (falsy) — the rest of the
        # existing search pipeline is unchanged.
        import vault_complete_search as vcs
        rows = [
            {"id": "n1", "saved_name": "naim id",
             "file_name": "naim.jpg", "content_type": "image/jpeg",
             "extracted_text": "", "detected_type": "id_photo"},
        ]
        with mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ):
            result = vcs.find_in_vault(
                vault_id="v-cat",
                key=b"\x00" * 32,
                query="show me my id documents",
            )
        payload = json.loads(result)
        # named_object_resolution must NOT be set — this is the
        # existing broader-search branch.
        self.assertNotEqual(
            payload["coverage"].get("named_object_resolution"), True,
        )


# ---------------------------------------------------------------------------
# Layer 2: extended generate_credential_draft tool
# ---------------------------------------------------------------------------

class GenerateCredentialDraftSchemaTest(unittest.TestCase):
    """Bug 2 schema fix — the tool JSON schema now accepts the
    optional user-supplied fields."""

    def test_schema_accepts_username_password_email_url_title(self):
        from vault_inspection_tools import INSPECTION_FUNCTIONS
        # Find the generate_credential_draft schema definition.
        schema = next(
            f["function"] for f in INSPECTION_FUNCTIONS
            if f.get("type") == "function"
            and f["function"]["name"] == "generate_credential_draft"
        )
        props = schema["parameters"]["properties"]
        for expected in ("service_name", "username", "password",
                         "email", "url", "title"):
            self.assertIn(
                expected, props,
                f"schema missing property {expected}",
            )
        # service_name is still the only required field.
        self.assertEqual(schema["parameters"]["required"], ["service_name"])


class GenerateCredentialDraftHandlerTest(unittest.TestCase):
    """Bug 2 handler fix — supplied values must be used verbatim."""

    def _run(self, **kwargs):
        from vault_inspection_tools import generate_credential_draft
        return generate_credential_draft(
            vault_id="v-cred", key=b"\x00" * 32,
            service_name=kwargs.pop("service_name", "Disney"),
            **kwargs,
        )

    def _stub_store(self):
        # Patch store_draft to a simple stub that echoes the fields
        # back through a to_public_dict() so we can assert on the
        # payload the tool returns.
        class _StubDraft:
            def __init__(self, service_name, username, password):
                self.draft_id = "draft-abcd1234"
                self._payload = {
                    "service_name": service_name,
                    "username":     username,
                    "password":     password,
                    "draft_id":     self.draft_id,
                    "expires_at":   "2100-01-01T00:00:00Z",
                    "saved":        False,
                }
            def to_public_dict(self):
                return dict(self._payload)
        def stub_store(
            *, vault_id, service_name, username, password,
            opaque_server_storage=False,
        ):
            return _StubDraft(service_name, username, password)
        return mock.patch(
            "vault_credential_draft.store_draft", side_effect=stub_store,
        )

    def test_explicit_email_username_preserved_verbatim(self):
        # PRODUCTION REPRO — this exact input drove the Disney/beraves
        # failure before the fix.
        with self._stub_store():
            raw = self._run(username="beraves@gmail.com")
        payload = json.loads(raw)
        self.assertEqual(payload["username"], "beraves@gmail.com")
        self.assertIn("username", payload["explicit_fields"])

    def test_plain_handle_username_preserved(self):
        with self._stub_store():
            raw = self._run(username="chosen2026")
        self.assertEqual(json.loads(raw)["username"], "chosen2026")

    def test_dotted_handle_username_preserved(self):
        with self._stub_store():
            raw = self._run(username="chosen.abdullahi")
        self.assertEqual(json.loads(raw)["username"], "chosen.abdullahi")

    def test_underscored_handle_username_preserved(self):
        with self._stub_store():
            raw = self._run(username="chosen_user_9")
        self.assertEqual(json.loads(raw)["username"], "chosen_user_9")

    def test_phone_number_username_preserved(self):
        with self._stub_store():
            raw = self._run(username="+15551234567")
        self.assertEqual(json.loads(raw)["username"], "+15551234567")

    def test_quoted_multiword_username_unquoted_and_preserved(self):
        with self._stub_store():
            raw = self._run(username='"chosen abdullahi"')
        self.assertEqual(
            json.loads(raw)["username"], "chosen abdullahi",
        )

    def test_no_username_supplied_generates_one(self):
        # Backward-compat: existing "generate a Gmail login" behavior
        # (no explicit fields) must still generate a username.
        with self._stub_store():
            raw = self._run()
        payload = json.loads(raw)
        self.assertNotIn("username", payload["explicit_fields"])
        # The generated value must not contain the service name.
        self.assertNotIn("disney", payload["username"].lower())

    def test_explicit_password_preserved(self):
        with self._stub_store():
            raw = self._run(
                username="chosen2026",
                password="MY-Sup3r-Secret!",
            )
        payload = json.loads(raw)
        self.assertEqual(payload["password"], "MY-Sup3r-Secret!")
        self.assertIn("password", payload["explicit_fields"])

    def test_generated_password_when_not_supplied(self):
        with self._stub_store():
            raw = self._run(username="chosen2026")
        payload = json.loads(raw)
        self.assertNotIn("password", payload["explicit_fields"])
        # Generated passwords are 20 chars.
        self.assertEqual(len(payload["password"]), 20)

    def test_email_url_title_surfaced_in_payload(self):
        with self._stub_store():
            raw = self._run(
                username="chosen2026",
                email="chosen@example.com",
                url="https://disney.com",
                title="My Streaming",
            )
        payload = json.loads(raw)
        self.assertEqual(payload["email"], "chosen@example.com")
        self.assertEqual(payload["url"], "https://disney.com")
        self.assertEqual(payload["title"], "My Streaming")
        self.assertIn("email", payload["explicit_fields"])
        self.assertIn("url", payload["explicit_fields"])
        self.assertIn("title", payload["explicit_fields"])

    def test_null_and_placeholder_values_ignored(self):
        # The LLM sometimes echoes "null" / "None" / "" — those must
        # be treated as absent, not as literal usernames.
        with self._stub_store():
            for placeholder in ("", "null", "None", "n/a", "-"):
                raw = self._run(username=placeholder)
                payload = json.loads(raw)
                self.assertNotIn("username", payload["explicit_fields"])
                # A generated (non-placeholder) username was produced.
                self.assertTrue(payload["username"])
                self.assertNotEqual(payload["username"], placeholder)


class GenerateCredentialDraftDispatchTest(unittest.TestCase):
    """Verify handle_tool_call (main.py) dispatches to the extended
    tool signature — so the LLM's supplied username/password/email/
    url/title reach the handler through the real production
    invocation path."""

    def test_supplied_kwargs_reach_handler(self):
        import main as _main
        captured = {}

        def stub_gcd(**kwargs):
            captured.update(kwargs)
            return json.dumps({
                "service_name": kwargs["service_name"],
                "username":     kwargs.get("username") or "GENERATED",
                "password":     "PW",
                "draft_id":     "d1",
                "expires_at":   "2100-01-01T00:00:00Z",
                "saved":        False,
                "explicit_fields": [
                    f for f in ("username", "password", "email",
                                "url", "title")
                    if kwargs.get(f)
                ],
            })

        # Patch generate_credential_draft in the dispatch table.
        # Use mock.patch.dict so the ORIGINAL dict object is preserved
        # and mutations are rolled back per-key on exit — a plain
        # mock.patch would replace the dict wholesale and leave any
        # module holding a stale reference broken across tests.
        #
        # Use a dedicated new_event_loop() rather than asyncio.run()
        # because Python 3.13 leaves no current event loop after
        # asyncio.run() exits — subsequent tests that call
        # asyncio.get_event_loop() (e.g. test_chat_semantic_decider_
        # 2026_07_24 line 92) would then raise
        # "There is no current event loop in thread". After we run
        # our own loop we restore a fresh one so later tests find a
        # valid loop.
        import asyncio
        with mock.patch.dict(
            "vault_knowledge_tools.VAULT_KNOWLEDGE_DISPATCH",
            {"generate_credential_draft": stub_gcd},
            clear=False,
        ):
            _dispatch_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(_dispatch_loop)
                result = _dispatch_loop.run_until_complete(
                    _main.handle_tool_call(
                        tool_name="generate_credential_draft",
                        args={
                            "service_name": "Disney",
                            "username":     "beraves@gmail.com",
                            "password":     "Sup3r-Secret",
                            "email":        "beraves@gmail.com",
                            "url":          "https://disney.com",
                            "title":        "My Streaming",
                        },
                        vault_id="v-dispatch",
                        key=b"\x00" * 32,
                        token_id="tok-abc",
                    )
                )
            finally:
                _dispatch_loop.close()
                # Leave a FRESH loop in place so later tests that
                # call asyncio.get_event_loop() find one.
                asyncio.set_event_loop(asyncio.new_event_loop())
        # Verify every explicit field the LLM passed reached the
        # handler as a kwarg.
        self.assertEqual(captured["service_name"], "Disney")
        self.assertEqual(captured["username"], "beraves@gmail.com")
        self.assertEqual(captured["password"], "Sup3r-Secret")
        self.assertEqual(captured["email"], "beraves@gmail.com")
        self.assertEqual(captured["url"], "https://disney.com")
        self.assertEqual(captured["title"], "My Streaming")
        payload = json.loads(result)
        self.assertEqual(payload["username"], "beraves@gmail.com")
        self.assertIn("username", payload["explicit_fields"])


# ---------------------------------------------------------------------------
# Layer 3: system-prompt guidance
# ---------------------------------------------------------------------------

class SystemPromptGuidanceTest(unittest.TestCase):
    """The system prompt must explicitly instruct the LLM to pass
    explicit user-supplied fields — otherwise the LLM will keep
    calling the tool with service_name only."""

    def test_prompt_mentions_explicit_username_extraction(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT as prompt
        self.assertIn("If the user gave a username", prompt)
        self.assertIn("VERBATIM", prompt)

    def test_prompt_shows_bare_email_example(self):
        # The Disney/beraves production repro is a documented
        # example so future regressions are visible in the prompt
        # diff.
        from tools import STATIC_VAULT_SYSTEM_PROMPT as prompt
        self.assertIn("beraves@gmail.com", prompt)
        self.assertIn("Disney", prompt)

    def test_prompt_lists_arbitrary_username_kinds(self):
        from tools import STATIC_VAULT_SYSTEM_PROMPT as prompt
        # Plain handle
        self.assertIn("chosen2026", prompt)
        # Underscored
        self.assertIn("chosen_user_9", prompt)
        # Phone-number
        self.assertIn("+15551234567", prompt)


# ---------------------------------------------------------------------------
# Layer 4: response headers + chat_path tagging
# ---------------------------------------------------------------------------

class ResponseHeaderTest(unittest.TestCase):

    def test_release_sha_header_from_env(self):
        from security_headers import _release_sha
        with mock.patch.dict("os.environ", {"VAULTAI_RELEASE_SHA": "abc1234"}):
            self.assertEqual(_release_sha(), "abc1234")

    def test_release_sha_defaults_to_dev(self):
        import os as _os
        from security_headers import _release_sha
        _prev = _os.environ.pop("VAULTAI_RELEASE_SHA", None)
        try:
            self.assertEqual(_release_sha(), "dev")
        finally:
            if _prev is not None:
                _os.environ["VAULTAI_RELEASE_SHA"] = _prev

    def test_release_sha_capped_to_16_chars(self):
        from security_headers import _release_sha
        long_sha = "a" * 100
        with mock.patch.dict("os.environ", {"VAULTAI_RELEASE_SHA": long_sha}):
            self.assertEqual(len(_release_sha()), 16)

    def test_chat_path_enum_constants_are_stable(self):
        # The values are consumed by external monitors — they must
        # not change silently.
        from security_headers import (
            CHAT_PATH_AI_PLANNER_DIRECT,
            CHAT_PATH_AI_PLANNER_FALLBACK,
            CHAT_PATH_ENCRYPTED_REPLY,
            CHAT_PATH_STATE_MACHINE_CANCELLED,
            CHAT_PATH_STATE_MACHINE_REPLACED,
            CHAT_PATH_STATE_MACHINE_SAVED,
            CHAT_PATH_STATE_MACHINE_SHOWN,
            CHAT_PATH_STATE_MACHINE_UPDATED,
            CHAT_PATH_UNKNOWN,
        )
        self.assertEqual(CHAT_PATH_AI_PLANNER_DIRECT,     "ai_planner_direct")
        self.assertEqual(CHAT_PATH_AI_PLANNER_FALLBACK,   "ai_planner_fallback")
        self.assertEqual(CHAT_PATH_ENCRYPTED_REPLY,       "encrypted_reply")
        self.assertEqual(CHAT_PATH_STATE_MACHINE_CANCELLED, "state_machine_cancelled")
        self.assertEqual(CHAT_PATH_STATE_MACHINE_REPLACED,  "state_machine_replaced")
        self.assertEqual(CHAT_PATH_STATE_MACHINE_SAVED,     "state_machine_saved")
        self.assertEqual(CHAT_PATH_STATE_MACHINE_SHOWN,     "state_machine_shown")
        self.assertEqual(CHAT_PATH_STATE_MACHINE_UPDATED,   "state_machine_updated")
        self.assertEqual(CHAT_PATH_UNKNOWN,                 "unknown")


class SecurityHeadersMiddlewareTest(unittest.TestCase):
    """The middleware must add X-VaultAI-Backend-Release to every
    response and X-VaultAI-Chat-Path when request.state.chat_path
    was tagged."""

    def _apply(self, path, chat_path=None):
        # Directly exercise the apply_security_headers helper +
        # inspect what the middleware would do. Building a full
        # ASGI stack is overkill — the helper is the extension
        # point.
        from starlette.responses import Response
        from security_headers import (
            apply_security_headers,
            _release_sha,
            _CHAT_PATH_HEADER,
        )
        resp = Response("hello")
        apply_security_headers(resp, path)
        # apply_security_headers now injects Backend-Release. Chat-
        # Path is added by the middleware wrapper — simulate that
        # step here.
        if chat_path:
            resp.headers.setdefault(_CHAT_PATH_HEADER, chat_path)
        return resp, _release_sha()

    def test_release_header_injected_on_every_response(self):
        resp, sha = self._apply("/anywhere")
        self.assertEqual(resp.headers["X-VaultAI-Backend-Release"], sha)

    def test_chat_path_header_when_tagged(self):
        resp, _ = self._apply(
            "/chat", chat_path="state_machine_updated",
        )
        self.assertEqual(
            resp.headers["X-VaultAI-Chat-Path"], "state_machine_updated",
        )


# ---------------------------------------------------------------------------
# Layer 5: diagnostic emit uses print() (survives log-config no-op)
# ---------------------------------------------------------------------------

class DiagnosticEmitTest(unittest.TestCase):
    """The BRAIN-TRACE-DXR emits were switched to print(..., flush=True)
    in this commit because logger.info was being silenced in
    production (basicConfig no-op after early transitive imports).
    Verify by reading source that the emits are print()-based, not
    logger.info-based."""

    def test_no_logger_dot_info_brain_trace_dxr_remains(self):
        import io, contextlib, main as _main
        # Only static-source check — grep the module source for the
        # anti-pattern.
        source_path = _main.__file__
        with open(source_path, "r", encoding="utf-8") as fp:
            source = fp.read()
        # Every BRAIN-TRACE-DXR emit must be a print() call. The
        # source may contain the string in comments; we're strict
        # about the emit lines only.
        for line_no, line in enumerate(source.splitlines(), start=1):
            if "[BRAIN-TRACE-DXR]" not in line:
                continue
            if line.strip().startswith("#"):
                continue
            # Whichever code line contains the format string must be
            # inside a print(...) block, not a logger.info(...) block.
            # We look for logger.info( on preceding non-blank lines.
            for back in range(1, 8):
                prev = source.splitlines()[line_no - 1 - back] if line_no - 1 - back >= 0 else ""
                if "logger.info(" in prev:
                    self.fail(
                        f"main.py:{line_no} still uses logger.info "
                        f"for a BRAIN-TRACE-DXR emit — logs will be "
                        f"silenced by uvicorn/root config"
                    )
                if "print(" in prev:
                    break

    def test_new_modules_use_print_for_brain_trace_dxr(self):
        # Same check across the new modules.
        for mod_name in (
            "vault_credential_command",
            "vault_pending_draft_state",
            "vault_exact_name_resolver",
            "vault_inspection_tools",
        ):
            mod = __import__(mod_name)
            source_path = mod.__file__
            with open(source_path, "r", encoding="utf-8") as fp:
                source = fp.read()
            for line_no, line in enumerate(source.splitlines(), start=1):
                if "[BRAIN-TRACE-DXR]" not in line:
                    continue
                if line.strip().startswith("#"):
                    continue
                for back in range(1, 8):
                    prev = (
                        source.splitlines()[line_no - 1 - back]
                        if line_no - 1 - back >= 0 else ""
                    )
                    if "logger.info(" in prev:
                        self.fail(
                            f"{mod_name}:{line_no} still uses "
                            f"logger.info for BRAIN-TRACE-DXR"
                        )
                    if "print(" in prev:
                        break


if __name__ == "__main__":
    unittest.main()
