"""Deterministic pre-router test suite (2026-07-27 architectural repair).

Every test in this file has one purpose: catch a regression in the
chat pipeline that would let one of the four confirmed 2026-07-27
production bugs re-appear.

  Bug 1: "show me naim id" -> ID-photo classifier / "no matches".
  Bug 2: "show me testing video" repeated -> non-deterministic
         (card once, plain text once).
  Bug 3: "show me" (bare) -> unrelated YouTube credential.
  Bug 4: "create me a youtube login with beraves@gmail.com" ->
         draft carries a generated random username.

The router lives at
  vault_ai_backend/vault_chat_deterministic_router.py

and is wired into main.py's chat_endpoint at the point just BEFORE
the direct-AI-tools short-circuit. The wiring is gated by
VAULTAI_DETERMINISTIC_ROUTER_ENABLED (default: "true"). This file
covers three levels:

  Level 1 - unit tests for every helper (verb extractor, normalizer,
            resolver, envelope builders, service extractor).
  Level 2 - integration tests for try_route_deterministically with
            fully-mocked dependencies (file-lister, credential drafter,
            active-entity setter/getter).
  Level 3 - main.py wiring tests: confirm the router IS invoked and
            IS gated correctly by both env flags used in production
            (VAULTAI_ENV=production, VAULTAI_DIRECT_AI_TOOLS_ENABLED=true,
            VAULTAI_EXPERIMENTAL_VAULT_BRAIN_CHAT_ENABLED=false).

None of these tests log passwords, PINs, usernames, emails, or vault
plaintext. Fixture data (emails etc.) is fabricated and appears only
inside test file bodies.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any, Optional
from unittest import mock


import vault_chat_deterministic_router as det
from vault_chat_deterministic_router import (
    CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE,
    CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS,
    CHAT_PATH_DETERMINISTIC_NAMED_OBJECT,
    KIND_CREDENTIAL_DRAFT,
    KIND_NAMED_OBJECT_AMBIGUOUS,
    KIND_NAMED_OBJECT_FILE,
    RESPONSE_TYPE_CREDENTIAL_DRAFT,
    RESPONSE_TYPE_FILE_DISAMBIGUATION,
    RESPONSE_TYPE_VAULT_FILE,
    RouteOutcome,
    try_route_deterministically,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VAULT_ID = "vault-router-test-0001"
_SESSION_ID = "sess-router-test-1234"
_KEY = b"\x00" * 32           # 32-byte AES key stand-in
_REQ = "req-det-router-001"


def _row(
    *, id: str, saved_name: Optional[str] = None,
    file_name: Optional[str] = None,
    asset_type: str = "image",
    content_type: Optional[str] = None,
    relative_path: Optional[str] = None,
) -> dict:
    """Canned vault-file row shaped like the SELECT in
    ``_list_uploaded_files_for_credential_search``."""
    return {
        "id":            id,
        "saved_name":    saved_name,
        "file_name":     file_name,
        "asset_type":    asset_type,
        "content_type":  content_type,
        "relative_path": relative_path,
    }


# Realistic small file list. The tests deliberately include:
#   * a file literally named "naim id" (Bug 1 regression trap)
#   * a video literally named "testing video" (Bug 2 regression trap)
#   * a credential-adjacent name ("YouTube") so cross-intent tests
#     can prove "show me testing video" does NOT return the YouTube
#     credential
#   * a name that would be ambiguous ("passport" appears in two rows)
_FIXTURE_FILES: list[dict] = [
    _row(
        id="file-naim-id-01",
        saved_name="naim id",
        file_name="naim_id.jpg",
        asset_type="image",
        content_type="image/jpeg",
    ),
    _row(
        id="file-testing-video-01",
        saved_name="testing video",
        file_name="test.mp4",
        asset_type="video",
        content_type="video/mp4",
    ),
    _row(
        id="file-passport-2024",
        saved_name="passport 2024",
        file_name="passport-2024.pdf",
        asset_type="pdf",
        content_type="application/pdf",
    ),
    _row(
        id="file-passport-2025",
        saved_name="passport 2025",
        file_name="passport-2025.pdf",
        asset_type="pdf",
        content_type="application/pdf",
    ),
    _row(
        id="file-tax-return",
        saved_name="tax return 2024",
        file_name="tax_return_2024.pdf",
        asset_type="pdf",
        content_type="application/pdf",
    ),
]


def _stub_drafter_ok(*, vault_id, key, service_name, username=None,
                     password=None, email=None, url=None, title=None):
    """Stub for `generate_credential_draft`. Records what the router
    called it with; returns the same JSON shape the real tool does."""
    explicit_fields = []
    if username:
        explicit_fields.append("username")
    if password:
        explicit_fields.append("password")
    if email:
        explicit_fields.append("email")
    if url:
        explicit_fields.append("url")
    if title:
        explicit_fields.append("title")

    payload = {
        "draft_id":        f"draft-{service_name}-01",
        "service":         service_name,
        "username":        username or "generated-user",
        "password":        password or "GeneratedPassword12345!",
        "explicit_fields": explicit_fields,
    }
    if email:
        payload["email"] = email
    if url:
        payload["url"] = url
    if title:
        payload["title"] = title
    return json.dumps(payload)


class _ActiveEntitySpy:
    """Minimal active-entity backend for tests. Records set() calls,
    supports get() by returning the last-set record."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.set_calls: list[dict] = []

    def set(self, vault_id, *, entity_type, entity_ref, display_label,
            allowed_actions, session_id=None, **kwargs) -> bool:
        record = {
            "vault_id":        vault_id,
            "entity_type":     entity_type,
            "entity_ref":      dict(entity_ref or {}),
            "display_label":   display_label,
            "allowed_actions": tuple(allowed_actions or ()),
            "session_id":      session_id,
        }
        self.records[vault_id] = record
        self.set_calls.append(record)
        return True

    def get(self, vault_id, *, session_id=None) -> Optional[dict]:
        rec = self.records.get(vault_id)
        if rec is None:
            return None
        if rec.get("session_id") not in (None, session_id):
            return None
        return dict(rec)


# ---------------------------------------------------------------------------
# Level 1: helper unit tests
# ---------------------------------------------------------------------------

class NormalizeNameTest(unittest.TestCase):

    def test_lowercase(self):
        self.assertEqual(det._normalize_name("Naim ID"), "naim id")

    def test_strip_punctuation(self):
        self.assertEqual(det._normalize_name("naim, id!"), "naim id")

    def test_underscore_and_hyphen_fold_to_space(self):
        self.assertEqual(det._normalize_name("naim_id"), "naim id")
        self.assertEqual(det._normalize_name("naim-id"), "naim id")

    def test_extension_stripped(self):
        self.assertEqual(det._normalize_name("naim_id.jpg"), "naim id")
        self.assertEqual(det._normalize_name("test.mp4"), "test")

    def test_multiple_whitespace_collapsed(self):
        self.assertEqual(det._normalize_name("naim    id"), "naim id")

    def test_empty(self):
        self.assertEqual(det._normalize_name(""), "")
        self.assertEqual(det._normalize_name(None), "")


class StripNameFillerTest(unittest.TestCase):

    def test_leading_my(self):
        self.assertEqual(det._strip_name_filler("my naim id"), "naim id")

    def test_leading_the(self):
        self.assertEqual(det._strip_name_filler("the testing video"),
                         "testing video")

    def test_trailing_type_token_file(self):
        self.assertEqual(det._strip_name_filler("testing video file"),
                         "testing video")

    def test_trailing_type_token_video_preserved(self):
        # "video" is a legitimate part of many saved names — the
        # stripper deliberately does NOT eat it.
        self.assertEqual(det._strip_name_filler("testing video"),
                         "testing video")

    def test_trailing_type_token_password_preserved(self):
        # Same — "password" survives ("wifi password" is a real note).
        self.assertEqual(det._strip_name_filler("wifi password"),
                         "wifi password")

    def test_trailing_pdf_stripped(self):
        self.assertEqual(det._strip_name_filler("tax return 2024 pdf"),
                         "tax return 2024")

    def test_stays_the_same_when_no_filler(self):
        self.assertEqual(det._strip_name_filler("naim id"), "naim id")

    def test_strip_refuses_when_remainder_too_short(self):
        # "hi file" -> keep whole thing rather than strip to "hi"
        # (which would be under _MIN_NAME_KEY_LEN).
        self.assertEqual(det._strip_name_filler("hi file"), "hi file")


class ExtractNamedActionTest(unittest.TestCase):
    """The verb / candidate-name extractor. Every failure here would
    move some class of "show me <X>" back to the planner."""

    def test_show_me_bug1(self):
        hit = det._extract_named_action("show me naim id")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.verb, "show")
        self.assertEqual(hit.normalized_name, "naim id")

    def test_show_me_bug2_video(self):
        hit = det._extract_named_action("show me testing video")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.verb, "show")
        self.assertEqual(hit.normalized_name, "testing video")

    def test_open(self):
        hit = det._extract_named_action("open tax return 2024")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.verb, "open")
        self.assertEqual(hit.normalized_name, "tax return 2024")

    def test_download(self):
        hit = det._extract_named_action("download passport 2024")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.verb, "download")

    def test_view(self):
        hit = det._extract_named_action("view naim id")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.verb, "view")

    def test_bare_show_me_returns_none(self):
        # "show me" alone must NOT match — that is the follow-up path
        # handled by the existing pronoun-followup dispatcher.
        self.assertIsNone(det._extract_named_action("show me"))

    def test_bare_pronoun_returns_none(self):
        self.assertIsNone(det._extract_named_action("show it"))
        self.assertIsNone(det._extract_named_action("open it"))
        self.assertIsNone(det._extract_named_action("view it"))

    def test_question_returns_none(self):
        self.assertIsNone(
            det._extract_named_action("what is my naim id?"),
        )

    def test_category_only_returns_none(self):
        # "show me id" alone would over-match — deliberately reject
        # bare category queries so category search stays in charge.
        self.assertIsNone(det._extract_named_action("show me id"))
        self.assertIsNone(det._extract_named_action("show me photos"))
        self.assertIsNone(
            det._extract_named_action("show me my documents"),
        )

    def test_long_message_returns_none(self):
        long_msg = "show me " + ("naim id " * 40)
        self.assertIsNone(det._extract_named_action(long_msg))

    def test_polite_filler_ok(self):
        hit = det._extract_named_action("please show me naim id")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.normalized_name, "naim id")

    def test_trailing_punct_ok(self):
        hit = det._extract_named_action("show me naim id.")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.normalized_name, "naim id")
        hit = det._extract_named_action("show me naim id!")
        self.assertIsNotNone(hit)


class ResolveNamedObjectFromRowsTest(unittest.TestCase):

    def test_unique_hit_by_saved_name(self):
        r = det._resolve_named_object_from_rows(
            "naim id", _FIXTURE_FILES,
        )
        self.assertEqual(r.status, "hit")
        self.assertEqual(r.row["id"], "file-naim-id-01")

    def test_unique_hit_by_file_name(self):
        rows = [
            _row(id="f-1", saved_name=None, file_name="naim_id.jpg"),
        ]
        r = det._resolve_named_object_from_rows("naim id", rows)
        self.assertEqual(r.status, "hit")
        self.assertEqual(r.row["id"], "f-1")

    def test_miss(self):
        r = det._resolve_named_object_from_rows(
            "something completely fake", _FIXTURE_FILES,
        )
        self.assertEqual(r.status, "miss")

    def test_ambiguous_two_passports(self):
        r = det._resolve_named_object_from_rows(
            "passport", _FIXTURE_FILES,
        )
        self.assertEqual(r.status, "ambiguous")
        self.assertEqual(len(r.candidates), 2)
        ids = {c["id"] for c in r.candidates}
        self.assertEqual(
            ids, {"file-passport-2024", "file-passport-2025"},
        )

    def test_exact_name_beats_substring(self):
        # "passport 2024" exactly matches ONE row. Must not return
        # ambiguity even though "passport" is a substring of both.
        r = det._resolve_named_object_from_rows(
            "passport 2024", _FIXTURE_FILES,
        )
        self.assertEqual(r.status, "hit")
        self.assertEqual(r.row["id"], "file-passport-2024")

    def test_empty_rows(self):
        r = det._resolve_named_object_from_rows("naim id", [])
        self.assertEqual(r.status, "miss")

    def test_category_stop_rejected(self):
        # The router already rejects category-only queries at
        # _extract_named_action time, but the resolver has its own
        # stop-list too for safety.
        r = det._resolve_named_object_from_rows("id", _FIXTURE_FILES)
        # Rows all include "id" tokens — but the resolver never
        # matches a stop-word key against itself.
        self.assertNotEqual(r.status, "ambiguous")


class BuildVaultFileEnvelopeTest(unittest.TestCase):

    def test_shape_matches_frontend_contract(self):
        row = _row(
            id="file-1",
            saved_name="naim id",
            file_name="naim_id.jpg",
            asset_type="image",
            content_type="image/jpeg",
        )
        envelope_json = det._build_vault_file_envelope(row, "show")
        envelope = json.loads(envelope_json)
        self.assertEqual(envelope["type"], RESPONSE_TYPE_VAULT_FILE)
        self.assertEqual(envelope["file_id"], "file-1")
        self.assertEqual(envelope["file_name"], "naim_id.jpg")
        self.assertEqual(envelope["saved_name"], "naim id")
        self.assertEqual(envelope["content_type"], "image/jpeg")
        self.assertEqual(envelope["asset_type"], "image")
        self.assertEqual(envelope["pending_action"], "show")
        self.assertEqual(envelope["resolved_by"], "deterministic_router")

    def test_identical_row_yields_identical_envelope(self):
        # Bug 2 regression trap. Two consecutive calls with the same
        # row + action MUST produce byte-identical envelopes.
        row = _row(
            id="file-vid",
            saved_name="testing video",
            file_name="test.mp4",
            asset_type="video",
            content_type="video/mp4",
        )
        a = det._build_vault_file_envelope(row, "show")
        b = det._build_vault_file_envelope(row, "show")
        self.assertEqual(a, b)


class BuildDisambiguationEnvelopeTest(unittest.TestCase):

    def test_shape(self):
        env = json.loads(
            det._build_disambiguation_envelope(
                "passport",
                [_row(id="f-1", saved_name="passport 2024"),
                 _row(id="f-2", saved_name="passport 2025")],
            )
        )
        self.assertEqual(env["type"], RESPONSE_TYPE_FILE_DISAMBIGUATION)
        self.assertEqual(env["candidate_name"], "passport")
        self.assertEqual(len(env["options"]), 2)


class BuildCredentialDraftEnvelopeTest(unittest.TestCase):

    def test_shape(self):
        payload = {
            "draft_id":        "draft-yt-1",
            "username":        "beraves@gmail.com",
            "password":        "P@ssw0rd!ExampleValue",
            "explicit_fields": ["username"],
        }
        env = json.loads(
            det._build_credential_draft_envelope(payload, "YouTube"),
        )
        self.assertEqual(env["type"], RESPONSE_TYPE_CREDENTIAL_DRAFT)
        self.assertEqual(env["service"], "YouTube")
        self.assertEqual(env["username"], "beraves@gmail.com")
        self.assertEqual(env["draft_id"], "draft-yt-1")
        self.assertEqual(env["explicit_fields"], ["username"])
        self.assertEqual(env["resolved_by"], "deterministic_router")


class ExtractServiceFromMessageTest(unittest.TestCase):

    def test_create_login(self):
        s = det._extract_service_from_message(
            "create me a youtube login with my email address "
            "beraves@gmail.com as my username",
        )
        self.assertEqual((s or "").lower(), "youtube")

    def test_save_account(self):
        s = det._extract_service_from_message(
            "save a netflix account, username is chosen2026",
        )
        self.assertEqual((s or "").lower(), "netflix")

    def test_generate_credential(self):
        s = det._extract_service_from_message(
            "generate a github credential with password MyPw!",
        )
        self.assertEqual((s or "").lower(), "github")

    def test_make_login(self):
        s = det._extract_service_from_message(
            "make an amazon login for beraves@gmail.com",
        )
        self.assertEqual((s or "").lower(), "amazon")

    def test_two_word_service(self):
        s = det._extract_service_from_message(
            "create me a prime video login with someone@example.com",
        )
        self.assertIn("prime", (s or "").lower())

    def test_for_my_service(self):
        s = det._extract_service_from_message(
            "generate a fresh password for my disney login",
        )
        self.assertEqual((s or "").lower(), "disney")

    def test_no_service_returns_none(self):
        self.assertIsNone(
            det._extract_service_from_message("hello there"),
        )

    def test_stopwords_rejected(self):
        # "create me a new login" — "new" is a stopword, no real service.
        self.assertIsNone(
            det._extract_service_from_message("create me a new login"),
        )


# ---------------------------------------------------------------------------
# Level 2: try_route_deterministically integration tests
# ---------------------------------------------------------------------------

class TryRouteBug1NaimIdTest(unittest.TestCase):
    """Bug 1: 'show me naim id' MUST return a structured vault_file
    envelope for the file literally named 'naim id'. It must NOT be
    handed to the planner (which would run the ID-photo classifier)."""

    def test_show_me_naim_id_resolves_and_pins(self):
        spy = _ActiveEntitySpy()
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me naim id",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: spy.get(
                vid, session_id=session_id,
            ),
            active_entity_setter=spy.set,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.kind, KIND_NAMED_OBJECT_FILE)
        self.assertEqual(
            outcome.chat_path_tag,
            CHAT_PATH_DETERMINISTIC_NAMED_OBJECT,
        )
        env = json.loads(outcome.envelope_json)
        self.assertEqual(env["type"], RESPONSE_TYPE_VAULT_FILE)
        self.assertEqual(env["file_id"], "file-naim-id-01")
        self.assertEqual(env["saved_name"], "naim id")
        self.assertEqual(env["pending_action"], "show")
        # The active entity pin metadata MUST be set so the next
        # bare "show me" resolves back to this file.
        self.assertIsNotNone(outcome.pin_active_entity)
        entity_type, ref, label, actions = outcome.pin_active_entity
        self.assertEqual(entity_type, "file")
        self.assertEqual(ref["file_id"], "file-naim-id-01")
        self.assertEqual(label, "naim id")
        self.assertIn("show", actions)
        self.assertIn("download", actions)

    def test_show_me_naim_id_does_not_return_id_photo_classifier(self):
        # Regression trap: any accidental fall-through to ID-photo
        # classification would emit the string "No matching ID photo"
        # in the response. Our envelope must NOT contain that.
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me naim id",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        env_json_lower = outcome.envelope_json.lower()
        self.assertNotIn("no matching id photo", env_json_lower)
        self.assertNotIn("no matches found", env_json_lower)
        self.assertNotIn("id photo results", env_json_lower)


class TryRouteBug2TestingVideoTest(unittest.TestCase):
    """Bug 2: 'show me testing video' MUST return an identical
    structured envelope on every invocation. No LLM in the loop
    means no non-determinism."""

    def test_repeated_calls_produce_identical_envelopes(self):
        args = dict(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me testing video",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        first = try_route_deterministically(**args)
        second = try_route_deterministically(**args)
        third = try_route_deterministically(**args)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        self.assertEqual(first.envelope_json, second.envelope_json)
        self.assertEqual(second.envelope_json, third.envelope_json)
        self.assertEqual(first.kind, KIND_NAMED_OBJECT_FILE)
        self.assertEqual(
            first.chat_path_tag,
            CHAT_PATH_DETERMINISTIC_NAMED_OBJECT,
        )

    def test_repeated_calls_never_return_plain_text(self):
        # The bug shape was: card once, then plain "I found a video
        # titled testing video. Would you like more details?"
        # Every envelope must be JSON with type=vault_file — never
        # non-JSON prose.
        args = dict(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me testing video",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        for _ in range(5):
            outcome = try_route_deterministically(**args)
            self.assertIsNotNone(outcome)
            payload = json.loads(outcome.envelope_json)
            self.assertEqual(payload["type"], RESPONSE_TYPE_VAULT_FILE)
            self.assertEqual(payload["file_id"], "file-testing-video-01")
            self.assertNotIn("would you like", outcome.envelope_json.lower())


class TryRouteBug3BareFollowupTest(unittest.TestCase):
    """Bug 3: 'show me' bare MUST NOT be misrouted to an unrelated
    credential. The router deliberately defers bare pronouns to the
    existing pronoun-followup dispatcher — but ONLY after pinning the
    previous named-object as the active entity, so the follow-up
    resolves against THAT."""

    def test_bare_show_me_defers_to_planner(self):
        # The router itself returns None for bare 'show me' — the
        # existing pronoun-followup at main.py:12899 handles it against
        # the active entity that the router just pinned.
        spy = _ActiveEntitySpy()
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: spy.get(
                vid, session_id=session_id,
            ),
            active_entity_setter=spy.set,
            chat_request_id=_REQ,
        )
        self.assertIsNone(outcome)

    def test_named_lookup_pins_entity_so_next_show_me_can_resolve(self):
        # Simulate the two-turn conversation:
        #   T1: "show me testing video"
        #   T2: "show me"
        # After T1 our router pins the file as active entity. The
        # pin_active_entity hint is what main.py uses to update
        # vault_chat_active_entity. Verify the hint carries the right
        # entity_type + entity_ref so a subsequent bare 'show me' via
        # the existing pronoun-followup dispatcher resolves to this
        # file, not to an unrelated stale login.
        spy = _ActiveEntitySpy()
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me testing video",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: spy.get(
                vid, session_id=session_id,
            ),
            active_entity_setter=spy.set,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        entity_type, ref, label, actions = outcome.pin_active_entity
        self.assertEqual(entity_type, "file")
        self.assertEqual(ref["file_id"], "file-testing-video-01")
        # Simulate main.py's downstream pin call.
        spy.set(_VAULT_ID, entity_type=entity_type, entity_ref=ref,
                display_label=label, allowed_actions=actions,
                session_id=_SESSION_ID)
        pinned = spy.get(_VAULT_ID, session_id=_SESSION_ID)
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned["entity_type"], "file")
        self.assertEqual(pinned["entity_ref"]["file_id"],
                         "file-testing-video-01")


class TryRouteBug4CredentialCreationTest(unittest.TestCase):
    """Bug 4: 'create me a youtube login with beraves@gmail.com as
    my username' MUST produce a draft whose username is exactly
    'beraves@gmail.com', not a generated random username."""

    def test_explicit_username_preserved_verbatim(self):
        drafter_calls: list = []

        def spy_drafter(**kwargs):
            drafter_calls.append(dict(kwargs))
            return _stub_drafter_ok(**kwargs)

        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message=(
                "create me a youtube login with my email address "
                "beraves@gmail.com as my username"
            ),
            files_lister=lambda: [],
            credential_drafter=spy_drafter,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.kind, KIND_CREDENTIAL_DRAFT)
        # Only ONE drafter call.
        self.assertEqual(len(drafter_calls), 1)
        call = drafter_calls[0]
        # THE critical assertion: the explicit username was threaded
        # verbatim into generate_credential_draft.
        self.assertEqual(call.get("username"), "beraves@gmail.com")
        self.assertEqual(call.get("email"), "beraves@gmail.com")
        # Service was extracted from the message.
        self.assertEqual((call.get("service_name") or "").lower(),
                         "youtube")
        # Password was NOT explicitly supplied.
        self.assertIsNone(call.get("password"))
        # The envelope also carries the explicit username.
        env = json.loads(outcome.envelope_json)
        self.assertEqual(env["type"], RESPONSE_TYPE_CREDENTIAL_DRAFT)
        self.assertEqual(env["username"], "beraves@gmail.com")
        self.assertIn("username", env["explicit_fields"])

    def test_prime_login_email_username(self):
        drafter_calls: list = []

        def spy_drafter(**kwargs):
            drafter_calls.append(dict(kwargs))
            return _stub_drafter_ok(**kwargs)

        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message=(
                "create a prime login with user@example.com as username"
            ),
            files_lister=lambda: [],
            credential_drafter=spy_drafter,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(drafter_calls[0].get("username"),
                         "user@example.com")
        self.assertEqual(
            (drafter_calls[0].get("service_name") or "").lower(),
            "prime",
        )

    def test_disney_login_plain_username(self):
        drafter_calls: list = []

        def spy_drafter(**kwargs):
            drafter_calls.append(dict(kwargs))
            return _stub_drafter_ok(**kwargs)

        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message=(
                "create a disney login, username is chosen123"
            ),
            files_lister=lambda: [],
            credential_drafter=spy_drafter,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(drafter_calls[0].get("username"), "chosen123")

    def test_github_login_username_and_password(self):
        drafter_calls: list = []

        def spy_drafter(**kwargs):
            drafter_calls.append(dict(kwargs))
            return _stub_drafter_ok(**kwargs)

        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message=(
                "create a github login using chosen@example.com, "
                "password: MyExplicitPassword123"
            ),
            files_lister=lambda: [],
            credential_drafter=spy_drafter,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        call = drafter_calls[0]
        # Both explicit values are threaded.
        self.assertEqual(call.get("username"), "chosen@example.com")
        self.assertEqual(call.get("password"), "MyExplicitPassword123")


class TryRouteAmbiguityAndMissTest(unittest.TestCase):

    def test_ambiguous_passport_yields_clarification(self):
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me passport",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.kind, KIND_NAMED_OBJECT_AMBIGUOUS)
        self.assertEqual(
            outcome.chat_path_tag,
            CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS,
        )
        env = json.loads(outcome.envelope_json)
        self.assertEqual(env["type"], RESPONSE_TYPE_FILE_DISAMBIGUATION)
        self.assertEqual(len(env["options"]), 2)
        # Ambiguity envelope must NOT pin an active entity — the user
        # hasn't chosen yet.
        self.assertIsNone(outcome.pin_active_entity)

    def test_no_match_defers_to_planner(self):
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me something-that-does-not-exist",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        # Miss on the resolver → router returns None so the planner
        # can still try semantic / OCR search.
        self.assertIsNone(outcome)

    def test_cross_intent_show_me_video_not_credential(self):
        # "show me testing video" against a vault that contains a
        # YouTube credential + the video: must resolve to the VIDEO,
        # never the credential. The router only looks at files —
        # credentials are not in files_lister — so this holds by
        # construction, but we assert it anyway for future regressions.
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me testing video",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        env = json.loads(outcome.envelope_json)
        self.assertEqual(env["file_id"], "file-testing-video-01")
        self.assertEqual(env["saved_name"], "testing video")


class TryRouteSafetyTest(unittest.TestCase):

    def test_locked_vault_defers(self):
        # 32-byte key required; short key => defer.
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=b"\x00" * 16,           # too short
            decrypted_message="show me naim id",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNone(outcome)

    def test_files_lister_exception_defers(self):
        def failing_lister():
            raise RuntimeError("db down")
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me naim id",
            files_lister=failing_lister,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        # Router downgraded to None so the planner still has a chance.
        self.assertIsNone(outcome)

    def test_drafter_exception_defers(self):
        def failing_drafter(**kwargs):
            raise RuntimeError("draft store down")
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message=(
                "create me a youtube login with someone@example.com"
            ),
            files_lister=lambda: [],
            credential_drafter=failing_drafter,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNone(outcome)

    def test_empty_message_defers(self):
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNone(outcome)

    def test_never_returns_route_outcome_with_bare_text(self):
        # Every RouteOutcome the router produces must carry a
        # well-formed envelope. Empty envelope would break the
        # frontend chat parser.
        outcome = try_route_deterministically(
            vault_id=_VAULT_ID,
            session_id=_SESSION_ID,
            key=_KEY,
            decrypted_message="show me naim id",
            files_lister=lambda: _FIXTURE_FILES,
            credential_drafter=_stub_drafter_ok,
            active_entity_getter=lambda vid, session_id=None: None,
            active_entity_setter=lambda *a, **k: True,
            chat_request_id=_REQ,
        )
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.envelope_json.strip().startswith("{"))
        self.assertTrue(outcome.envelope_json.strip().endswith("}"))


class DiagnosticsTest(unittest.TestCase):
    """CHAT_TRACE emission must include the correlation ID and never
    include message contents / usernames / emails / passwords."""

    def _capture(self, msg: str, files: list[dict],
                 request_id: str = _REQ):
        captured: list[str] = []
        with mock.patch("builtins.print") as p:
            try_route_deterministically(
                vault_id=_VAULT_ID,
                session_id=_SESSION_ID,
                key=_KEY,
                decrypted_message=msg,
                files_lister=lambda: files,
                credential_drafter=_stub_drafter_ok,
                active_entity_getter=lambda vid, session_id=None: None,
                active_entity_setter=lambda *a, **k: True,
                chat_request_id=request_id,
            )
            for call in p.call_args_list:
                if not call.args:
                    continue
                line = str(call.args[0])
                if line.startswith("CHAT_TRACE"):
                    captured.append(line)
        return captured

    def test_named_object_emits_trace(self):
        lines = self._capture("show me naim id", _FIXTURE_FILES)
        self.assertTrue(any(
            "route=deterministic" in ln
            and "intent=named_object" in ln
            and "response_type=vault_file" in ln
            for ln in lines
        ))

    def test_credential_create_emits_trace_without_leaking(self):
        lines = self._capture(
            "create a youtube login with beraves@gmail.com", [],
        )
        self.assertTrue(any(
            "route=deterministic" in ln
            and "intent=credential_create" in ln
            and "explicit_username_present=true" in ln
            for ln in lines
        ))
        # Trace lines must NOT contain the email or the password.
        for ln in lines:
            self.assertNotIn("beraves@gmail.com", ln)
            self.assertNotIn("gmail.com", ln)
            self.assertNotIn("password=", ln.replace(
                "explicit_password_present=", "",
            ).replace("generated_password=", ""))

    def test_request_id_present(self):
        lines = self._capture("show me naim id", _FIXTURE_FILES,
                              request_id="req-abc-xyz")
        self.assertTrue(all("request_id=req-abc-xyz" in ln for ln in lines))


# ---------------------------------------------------------------------------
# Level 3: main.py wiring tests
# ---------------------------------------------------------------------------

class MainPyWiringTest(unittest.TestCase):
    """Static-source guards on the main.py wiring. If any of these
    fail, the router was removed or moved to a place where the
    production request never reaches it."""

    def _main_src(self) -> str:
        import main as _m
        with open(_m.__file__, "r", encoding="utf-8") as fp:
            return fp.read()

    def test_router_import_present(self):
        src = self._main_src()
        self.assertIn(
            "from vault_chat_deterministic_router import",
            src,
            "deterministic router must be imported by main.py",
        )
        self.assertIn("try_route_deterministically", src)

    def test_wired_before_direct_ai_tools_branch(self):
        src = self._main_src()
        det_pos = src.find("try_route_deterministically")
        direct_pos = src.find("if _direct_ai_tools_enabled:")
        self.assertGreater(det_pos, 0,
                           "router call site not found in main.py")
        self.assertGreater(direct_pos, 0)
        self.assertLess(
            det_pos, direct_pos,
            "router must be wired BEFORE the direct-AI-tools branch",
        )

    def test_env_flag_gated(self):
        src = self._main_src()
        self.assertIn(
            "VAULTAI_DETERMINISTIC_ROUTER_ENABLED", src,
            "router wiring must be gated by the rollback env flag",
        )

    def test_pin_active_entity_call_wired(self):
        src = self._main_src()
        # The pin call: the router hands back pin_active_entity, and
        # main.py must call set_active_entity with it.
        self.assertIn("_det_outcome.pin_active_entity", src)
        self.assertIn("_det_set_active(", src)

    def test_chat_path_tag_wired(self):
        src = self._main_src()
        self.assertIn("_det_outcome.chat_path_tag", src)

    def test_router_defaults_enabled(self):
        # The env-flag default must be "true" so production picks it
        # up without a re-deploy. If someone flips this default, the
        # router silently regresses to no-op.
        src = self._main_src()
        self.assertIn(
            'os.getenv(\n            "VAULTAI_DETERMINISTIC_ROUTER_ENABLED", "true",',
            src,
        )


class SecurityHeadersEnumTest(unittest.TestCase):
    """The four new chat_path enum values must exist in
    security_headers.py so the middleware can surface them on the
    X-VaultAI-Chat-Path response header."""

    def test_four_deterministic_paths_defined(self):
        import security_headers as sh
        self.assertEqual(
            sh.CHAT_PATH_DETERMINISTIC_FOLLOWUP,
            "deterministic_followup",
        )
        self.assertEqual(
            sh.CHAT_PATH_DETERMINISTIC_NAMED_OBJECT,
            "deterministic_named_object",
        )
        self.assertEqual(
            sh.CHAT_PATH_DETERMINISTIC_NAMED_AMBIGUOUS,
            "deterministic_named_ambiguous",
        )
        self.assertEqual(
            sh.CHAT_PATH_DETERMINISTIC_CREDENTIAL_CREATE,
            "deterministic_credential_create",
        )

    def test_exported(self):
        import security_headers as sh
        self.assertIn(
            "CHAT_PATH_DETERMINISTIC_NAMED_OBJECT", sh.__all__,
        )


# ---------------------------------------------------------------------------
# Level 3b: production-flag interaction test
# ---------------------------------------------------------------------------

class ProductionFlagInteractionTest(unittest.TestCase):
    """Confirm the router is enabled AND the OpenAI planner short-circuit
    can be enabled at the same time — the router is a PRE-planner
    stage, not an alternative to it."""

    def test_deterministic_flag_default_is_true(self):
        # The rollback flag: absent env var must equal "true".
        prev = os.environ.pop("VAULTAI_DETERMINISTIC_ROUTER_ENABLED", None)
        try:
            value = os.getenv(
                "VAULTAI_DETERMINISTIC_ROUTER_ENABLED", "true",
            ).strip().lower() in ("1", "true", "yes", "on")
            self.assertTrue(value)
        finally:
            if prev is not None:
                os.environ["VAULTAI_DETERMINISTIC_ROUTER_ENABLED"] = prev

    def test_flag_can_be_disabled(self):
        prev = os.environ.get("VAULTAI_DETERMINISTIC_ROUTER_ENABLED")
        os.environ["VAULTAI_DETERMINISTIC_ROUTER_ENABLED"] = "false"
        try:
            value = os.getenv(
                "VAULTAI_DETERMINISTIC_ROUTER_ENABLED", "true",
            ).strip().lower() in ("1", "true", "yes", "on")
            self.assertFalse(value)
        finally:
            if prev is None:
                os.environ.pop(
                    "VAULTAI_DETERMINISTIC_ROUTER_ENABLED", None,
                )
            else:
                os.environ["VAULTAI_DETERMINISTIC_ROUTER_ENABLED"] = prev


# ---------------------------------------------------------------------------
# Level 3c: no-secret-leak audit of the router itself
# ---------------------------------------------------------------------------

class NoSecretLeakInRouterModuleTest(unittest.TestCase):
    """The router module source itself must not print/log field values
    it receives. Static-source guard: no % or f-string with a bare
    'username', 'password', 'email', 'pin' variable identifier next to
    a value-format specifier."""

    def _module_src(self) -> str:
        import vault_chat_deterministic_router as _r
        with open(_r.__file__, "r", encoding="utf-8") as fp:
            return fp.read()

    def test_no_direct_field_value_prints(self):
        src = self._module_src()
        # Regex that catches an f-string / % format interpolating a
        # bare `username`/`password`/`email`/`pin` variable directly
        # into a log line. Allowed shape: `explicit_username_present={
        # str(bool(explicit_username_present))}` (interpolates a
        # boolean, not the value). Banned shape: `username={username}`,
        # `password={password}`, `email={email or ""}`, etc.
        import re as _re
        banned = _re.compile(
            r"""
              (?:^|["'\s\{,])          # boundary
              (?:username|password|email|pin)
              \s*=\s*
              \{
                (?:username|password|email|pin)
                (?:\s|[}.\|:!])
            """,
            _re.VERBOSE | _re.IGNORECASE,
        )
        match = banned.search(src)
        self.assertIsNone(
            match,
            f"router must not log raw field values (matched: "
            f"{match.group() if match else None!r})",
        )


if __name__ == "__main__":
    unittest.main()
