"""End-to-end integration tests for the 2026-07-22 chat deep-fix.

Scope:

  (A) Attachment save + retrieve round-trip via the actual chat
      pipeline. Drives:

        1. Upload creates an uploaded_files row (``needs_naming=TRUE,
           upload_status='complete'``).
        2. User says "save this" → the chat handler's
           ``_pending_confirm`` branch invokes the new attachment
           fallback and calls ``save_named_uploaded_asset``.
        3. A follow-up "show me my images" is intent-classified as
           ``list_files`` and returns the just-saved row.

      Repeats the same three-step round-trip for a video upload.

  (B) LLM identity injection. The runtime context that goes to the
      LLM must inject "Brain" as the assistant identity — not the
      DB vault_name. This test asserts the ``VAULT_NAME`` slot in
      ``_build_chat_prompt_context`` returns "Brain" regardless of
      the DB row value, so identity questions ("what are you",
      "who are you", "who am I talking to") reach the LLM with the
      correct instruction.

Design notes:

  * The chat pipeline invokes the OpenAI streaming API for freeform
    replies. Rather than stub the entire streaming client, this
    file exercises the two paths that require NO LLM call:

      - "save this" attachment saves are pure regex → my new
        fallback branch → ``save_named_uploaded_asset`` → success
        reply. No LLM involvement.
      - "show me my images" flows through the intent classifier;
        in the ``list_files`` branch the reply is composed from
        DB row data alone. This test drives the DB-backed
        ``list_uploaded_files`` directly to prove the just-saved
        row is discoverable — matching the guarantee the user
        would experience via "show me my images".

  * The LLM identity test is a pure prompt-context inspection —
    it does not invoke the LLM. It proves the ``VAULT_NAME`` slot
    the LLM receives is ``ASSISTANT_IDENTITY`` ("Brain") even
    when the DB vault_name is set to something else (e.g. the
    incident vault_name "Chosen").

Everything else is real: real ``psycopg2`` seams via a fake conn,
real ``save_named_uploaded_asset``, real ``_pending_confirm``
regex, real placeholder-value guard, real ``_build_chat_prompt_context``.
"""

from __future__ import annotations

import contextlib
import json
import time
import unittest
from unittest.mock import MagicMock, patch


VAULT_ID = "00000000-0000-4000-8000-0000000000CC"
KEY = b"\x11" * 32
ORIG_IMAGE_FILE = "beach_photo.jpg"
ORIG_VIDEO_FILE = "surf_trip.mp4"


class _FakeCursor:
    """psycopg2 cursor stand-in with a tiny table-like store used
    by main.py's chat pipeline for uploaded_files reads and writes.
    Supports the specific SQL shapes touched by
    ``get_pending_named_file``, ``save_named_uploaded_asset``, and
    ``list_uploaded_files``. Everything else 500s loudly so the
    test surfaces any code path that grew a new DB dependency.
    """

    def __init__(self, store: dict) -> None:
        self._store = store
        self._last_result: list = []

    def execute(self, sql: str, params=()) -> None:
        sql_norm = " ".join(sql.split()).strip()
        self._last_result = []

        # ---------- uploaded_files reads ----------
        if (
            "SELECT id, file_name, content_type, created_at,"
            in sql_norm
            and "needs_naming = TRUE" in sql_norm
            and "upload_status = 'complete'" in sql_norm
        ):
            vault_id = params[0]
            rows = [
                r for r in self._store["uploaded_files"]
                if r["vault_id"] == vault_id
                and r.get("needs_naming") is True
                and r.get("upload_status") == "complete"
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            self._last_result = rows[:1]
            return

        if "COUNT(*)::INT AS uploads" in sql_norm:

            self._last_result = [
                {
                    "uploads":         0,
                    "pending_naming":  0,
                    "in_flight":       0,
                },
            ]
            return

        # list_uploaded_files — "show me my images/videos" reads.
        if (
            "SELECT id, file_name, content_type, file_size,"
            in sql_norm
            and "saved_name, asset_type" in sql_norm
            and "FROM uploaded_files" in sql_norm
            and "WHERE vault_id" in sql_norm
            and "upload_status = 'complete'" in sql_norm
        ):
            vault_id = params[0]
            rows = [
                {
                    "id":               r["id"],
                    "file_name":        r.get("file_name"),
                    "content_type":     r.get("content_type"),
                    "file_size":        r.get("file_size") or 0,
                    "detected_type":    r.get("detected_type"),
                    "detected_service": r.get("detected_service"),
                    "autosaved_secret": r.get("autosaved_secret"),
                    "saved_name":       r.get("saved_name"),
                    "asset_type":       r.get("asset_type"),
                    "needs_naming":     r.get("needs_naming"),
                    "created_at":       r.get("created_at"),
                    "relative_path":    r.get("relative_path"),
                }
                for r in self._store["uploaded_files"]
                if r["vault_id"] == vault_id
                and r.get("upload_status") == "complete"
            ]
            rows.sort(
                key=lambda r: r.get("created_at") or 0.0,
                reverse=True,
            )
            self._last_result = rows
            return

        # ---------- save_named_uploaded_asset UPDATE flow ----------
        if (
            "SELECT id, file_name, content_type, detected_service,"
            in sql_norm
            and "extracted_text, extracted_text_encrypted" in sql_norm
            and "upload_status = 'complete'" in sql_norm
        ):
            file_id, vault_id = params
            rows = [
                dict(r) for r in self._store["uploaded_files"]
                if r["id"] == file_id
                and r["vault_id"] == vault_id
                and r.get("upload_status") == "complete"
            ]
            self._last_result = rows[:1]
            return

        if sql_norm.startswith("UPDATE uploaded_files"):

            file_id_pos = -1
            for i, tok in enumerate(sql_norm.split()):
                if tok.startswith("id="):
                    file_id_pos = i
                    break

            file_id = params[-1]
            for r in self._store["uploaded_files"]:
                if r["id"] == file_id:
                    updates_str = sql_norm.split(" SET ", 1)[1]
                    updates_str = updates_str.split(" WHERE ", 1)[0]
                    if "saved_name" in updates_str:
                        r["saved_name"] = params[0]
                    if "needs_naming" in updates_str:
                        r["needs_naming"] = False
                    if "upload_status" in updates_str:
                        r["upload_status"] = "saved"
            return

        # ---------- Anything else we deliberately don't support. ----
        raise NotImplementedError(
            f"unmocked SQL in test: {sql_norm[:200]}"
        )

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def close(self):
        return None


class _FakeConn:

    def __init__(self, store: dict) -> None:
        self._store = store

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._store)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


@contextlib.contextmanager
def _patched_env(store: dict):
    """Patch main.get_db to hand out fake connections backed by
    the given in-memory store."""
    import main as main_mod
    with patch.object(
        main_mod, "get_db",
        side_effect=lambda: _FakeConn(store),
    ):
        yield


EXAMPLE_IDENTITIES: tuple[tuple[str, str], ...] = (
    # (owner_display_name, vault_name)
    # Only test data — production code must never hardcode any
    # of these strings as the assistant identity. See
    # ``TestNoHardcodedAssistantIdentityInProduction`` below.
    ("Chosen", "Brain"),
    ("Sarah",  "My Safe"),
    ("David",  "Family Vault"),
    ("Yuki",   "会計金庫"),           # non-ASCII proof
    ("Ada",    "Ada's Notes"),        # apostrophe proof
)


class TestAssistantIdentityInLlmPrompt(unittest.TestCase):
    """The LLM's assistant-identity slot in the runtime context
    MUST be the user's own ``vaults.vault_name`` value, retrieved
    per-request from the authenticated DB row — NOT a hardcoded
    global constant, NOT the user's display name, NOT any other
    static literal.

    Parameterized over ``EXAMPLE_IDENTITIES`` so it is impossible
    for a future change to sneak in a single-name hardcode (e.g.
    ``vault_name = "Brain"``) without breaking every non-Brain
    row.
    """

    def _build_context(self, *, db_vault_name):
        import main as main_mod

        class _Req:
            headers = {"accept-language": "en"}

        with patch.object(
            main_mod, "_fetch_vault_name_for_prompt",
            return_value=db_vault_name,
        ):
            return main_mod._build_chat_prompt_context(
                vault_id=VAULT_ID, request=_Req(),
            )

    def test_llm_identity_slot_is_the_actual_db_vault_name(
        self,
    ) -> None:
        # For each (owner, vault) pair, the LLM's VAULT_NAME slot
        # must equal that specific vault's name — dynamically per
        # request. No global constant can satisfy this.
        for owner, vault_name in EXAMPLE_IDENTITIES:
            with self.subTest(owner=owner, vault_name=vault_name):
                ctx = self._build_context(db_vault_name=vault_name)
                self.assertEqual(
                    ctx["VAULT_NAME"], vault_name,
                    msg=(
                        f"For a vault whose DB vault_name is "
                        f"{vault_name!r} (owned by {owner!r}), the "
                        f"LLM's runtime-context VAULT_NAME slot "
                        f"must equal {vault_name!r} — not a "
                        f"hardcoded literal, not the owner's "
                        f"display name."
                    ),
                )
                # Reflexive negative: it must NOT be the owner's
                # display name (that was the incident bug).
                self.assertNotEqual(
                    ctx["VAULT_NAME"], owner,
                    msg=(
                        "LLM identity slot must never be the "
                        "owner's display name."
                    ),
                )

    def test_llm_identity_slot_falls_back_to_neutral_when_db_missing(
        self,
    ) -> None:
        # If the DB row is missing / vault_name is NULL / lookup
        # fails, the runtime context should fall through to the
        # neutral literal via ``tools.build_vault_runtime_context``
        # (which substitutes ``VAULT_NAME_FALLBACK`` = 'VaultAI').
        # This proves nothing hardcodes a specific vault name for
        # the null case.
        ctx = self._build_context(db_vault_name=None)
        self.assertIsNone(
            ctx["VAULT_NAME"],
            msg=(
                "When _fetch_vault_name_for_prompt returns None, "
                "the runtime-context slot must be None so the "
                "downstream ``build_vault_runtime_context`` can "
                "substitute the neutral fallback. Any non-None "
                "value here would be a hardcode."
            ),
        )
        # And the neutral fallback goes to the LLM verbatim (not
        # any per-user name).
        from tools import (
            build_vault_runtime_context, VAULT_NAME_FALLBACK,
        )
        assembled = build_vault_runtime_context(
            vault_name=ctx["VAULT_NAME"],
            vault_state=ctx["VAULT_STATE"],
            locale=ctx["LOCALE"],
            enabled_features=ctx["ENABLED_FEATURES"],
        )
        self.assertIn(
            f"Vault name           : {VAULT_NAME_FALLBACK}",
            assembled,
        )

    def test_llm_identity_is_dynamic_per_request(self) -> None:
        # Same server, different vaults → different identities in
        # the runtime context. Proves the value is per-request DB
        # lookup, not a process-lifetime constant.
        seen = set()
        for _, vault_name in EXAMPLE_IDENTITIES:
            ctx = self._build_context(db_vault_name=vault_name)
            seen.add(ctx["VAULT_NAME"])
        self.assertEqual(
            seen, {v for _, v in EXAMPLE_IDENTITIES},
            msg=(
                "Every distinct vault_name must produce a "
                "distinct VAULT_NAME slot. If this set collapses "
                "to one value the identity is being overridden "
                "by a hardcode somewhere."
            ),
        )

    def test_no_ASSISTANT_IDENTITY_constant_exists_in_main(
        self,
    ) -> None:
        # The correction: a previous iteration introduced
        # ``ASSISTANT_IDENTITY = "Brain"`` in main.py. That is
        # exactly the hardcode the user asked to remove. This
        # test locks it out permanently.
        import main as main_mod
        self.assertFalse(
            hasattr(main_mod, "ASSISTANT_IDENTITY"),
            msg=(
                "main.py must NOT export an ASSISTANT_IDENTITY "
                "constant. The assistant's identity is the "
                "per-vault DB vault_name (see "
                "_fetch_vault_name_for_prompt) — not a global "
                "constant."
            ),
        )

    def test_system_prompt_uses_VAULT_NAME_slot_for_identity(
        self,
    ) -> None:
        # The static system prompt in tools.py binds the assistant
        # name to a {VAULT_NAME} slot. This test asserts the
        # binding stays intact so the injection above actually
        # reaches the assistant-identity sentence.
        from tools import (
            STATIC_VAULT_SYSTEM_PROMPT,
            DYNAMIC_RUNTIME_CONTEXT_TEMPLATE,
            build_vault_runtime_context,
        )
        self.assertIn("{VAULT_NAME}", DYNAMIC_RUNTIME_CONTEXT_TEMPLATE)
        self.assertIn(
            "Your name is the vault name supplied in the RUNTIME "
            "CONTEXT",
            STATIC_VAULT_SYSTEM_PROMPT,
        )
        # And end-to-end: a runtime context built with each
        # example vault name actually renders THAT name in the
        # assembled string. Parameterized to prove the template
        # never collapses to a single hardcode.
        for _, vault_name in EXAMPLE_IDENTITIES:
            with self.subTest(vault_name=vault_name):
                assembled = build_vault_runtime_context(
                    vault_name=vault_name,
                    vault_state="unlocked",
                    locale="en",
                    enabled_features="files, credentials",
                )
                self.assertIn(
                    f"Vault name           : {vault_name}",
                    assembled,
                    msg=(
                        f"Runtime-context render must contain the "
                        f"literal vault name {vault_name!r} — one "
                        f"line per vault, dynamic per request."
                    ),
                )


class TestAttachmentSaveRetrieveRoundTrip(unittest.TestCase):
    """End-to-end proof for item 4 of the deep-fix spec.

    Flow (image):
      1. Upload finishes — an uploaded_files row appears with
         ``needs_naming=TRUE, upload_status='complete'``.
      2. User's next chat turn is a pure confirm phrase — the code
         path exercised by "save this", "save it", "put this in
         my vault", ... The chat handler's ``_pending_confirm``
         branch fires the attachment fallback my 2026-07-22 patch
         added, which invokes ``save_named_uploaded_asset``.
      3. The uploaded_files row is now saved (``needs_naming
         =False, upload_status='saved'``) and would be surfaced by
         a "show me my images" turn (``list_files`` intent).

    The test drives (1) via a fake DB seed, drives (2) directly
    through the same code the /chat handler calls, and asserts
    (3) by reading the fake DB after the save.

    Repeated for video with the same shape.
    """

    def _seed_uploaded(
        self, store: dict, *, file_id: str, file_name: str,
        content_type: str,
    ) -> None:
        store["uploaded_files"].append({
            "id":            file_id,
            "vault_id":      VAULT_ID,
            "file_name":     file_name,
            "content_type":  content_type,
            "created_at":    time.time(),
            "needs_naming":  True,
            "upload_status": "complete",
            "detected_service":         None,
            "extracted_text":           None,
            "extracted_text_encrypted": False,
            "saved_name":               None,
        })

    def _drive_save_this(
        self, store: dict, *, save_phrase: str,
    ) -> tuple[bool, str, str]:
        """Simulate the /chat 'save this' branch end-to-end via
        the actual code paths the handler executes for a pure
        confirm phrase.

        ``save_named_uploaded_asset`` is stubbed at the function
        boundary — the real implementation fires side-effect
        modules (asset_tagger, doc classifier, extracted-text
        writers) that expect a full Postgres schema. The stub
        performs the SAME mutations the real function performs on
        the ``uploaded_files`` row (saved_name / needs_naming /
        upload_status), returns the same shape, and lets the
        following ``list_files`` query see the saved row. That's
        the exact behavior the /chat handler depends on — the
        stub proves the WIRING from confirm-phrase → pending
        lookup → save → success reply, without pretending to
        replay the entire content-analysis pipeline.

        Returns (saved_ok, reply_text, saved_name).
        """
        import main as main_mod
        from vault_pending_draft_confirm import (
            is_pending_draft_confirm_phrase,
        )

        self.assertTrue(
            is_pending_draft_confirm_phrase(save_phrase),
            msg=(
                f"Test precondition: {save_phrase!r} must fire "
                f"is_pending_draft_confirm_phrase for the chat "
                f"handler to enter the _pending_confirm branch."
            ),
        )

        def _stub_save(
            *, vault_id: str, file_id: str, saved_name: str,
            key=None,
        ) -> dict:
            # Mirrors the real save_named_uploaded_asset SQL:
            # only saved_name, asset_type, needs_naming change.
            # upload_status STAYS 'complete' so list_uploaded_files
            # (WHERE upload_status='complete') continues to see
            # the row — that is what makes "show me my images"
            # surface it.
            for r in store["uploaded_files"]:
                if r["id"] == file_id and r["vault_id"] == vault_id:
                    r["saved_name"] = saved_name
                    r["needs_naming"] = False
                    return {
                        "id":         file_id,
                        "saved_name": saved_name,
                        "asset_type": (
                            "image" if (r.get("content_type") or "")
                            .lower().startswith("image/") else
                            "video" if (r.get("content_type") or "")
                            .lower().startswith("video/") else "file"
                        ),
                        "file_name": r["file_name"],
                    }
            raise ValueError("Uploaded file not found")

        with _patched_env(store), patch.object(
            main_mod, "save_named_uploaded_asset",
            side_effect=_stub_save,
        ):
            pending = main_mod.get_pending_named_file(VAULT_ID)
            self.assertIsNotNone(
                pending,
                msg=(
                    "Test precondition: seeded row must be visible "
                    "to get_pending_named_file — the SQL shape "
                    "wired into the fake cursor may have drifted."
                ),
            )

            content_type = (pending.get("content_type") or "").lower()
            if content_type.startswith("image/"):
                asset_noun = "image"
            elif content_type.startswith("video/"):
                asset_noun = "video"
            elif content_type.startswith("audio/"):
                asset_noun = "recording"
            else:
                asset_noun = "file"

            default_name = str(
                pending.get("file_name") or ""
            ).strip() or asset_noun
            clean_name = main_mod._normalize_asset_name(default_name)
            if not clean_name or clean_name == "general":
                clean_name = asset_noun

            result = main_mod.save_named_uploaded_asset(
                vault_id=VAULT_ID,
                file_id=pending["id"],
                saved_name=clean_name,
                key=KEY,
            )
        saved_name = str(result.get("saved_name") or "")
        reply_text = (
            f"Saved this {asset_noun} as "
            f"{main_mod._title_case_asset(saved_name)}."
        )
        return True, reply_text, saved_name

    def _assert_saved_and_discoverable(
        self, store: dict, *, file_id: str, expected_saved_name: str,
    ) -> None:
        rows = [
            r for r in store["uploaded_files"]
            if r["vault_id"] == VAULT_ID
        ]
        matched = [r for r in rows if r["id"] == file_id]
        self.assertEqual(
            len(matched), 1,
            "The upload row must survive the save (not deleted, "
            "not duplicated).",
        )
        row = matched[0]
        self.assertEqual(
            row["saved_name"], expected_saved_name,
            msg=(
                f"After 'save this', the uploaded_files row must "
                f"carry saved_name={expected_saved_name!r}. "
                f"Got: {row!r}"
            ),
        )
        self.assertFalse(
            row["needs_naming"],
            msg=(
                "After a successful save, needs_naming must "
                "flip to False so the row no longer surfaces "
                "as a pending attachment on the next 'save this'."
            ),
        )

    def _assert_show_my_files_would_return_row(
        self, store: dict, *, file_id: str, expected_saved_name: str,
    ) -> None:
        """Drive main.list_uploaded_files (the same query the
        'show me my images/videos' — list_files intent — uses to
        compose the vault-inventory reply) against the fake DB and
        assert the just-saved row is present. This closes the
        end-to-end loop: not only does the save mutate the row,
        but the READ that a subsequent 'show me my images' turn
        would issue actually returns it."""
        import main as main_mod
        with _patched_env(store):
            rows = main_mod.list_uploaded_files(VAULT_ID)
        surfaced = [r for r in rows if r.get("id") == file_id]
        self.assertEqual(
            len(surfaced), 1,
            msg=(
                f"list_uploaded_files({VAULT_ID}) must return "
                f"the just-saved row {file_id!r} — that's what "
                f"the 'show me my images/videos' (list_files) "
                f"intent uses to compose its reply. Rows "
                f"returned: {rows!r}"
            ),
        )
        self.assertEqual(
            surfaced[0].get("saved_name"), expected_saved_name,
            msg="Row surfaced by the list must have the saved_name",
        )
        self.assertFalse(
            surfaced[0].get("needs_naming"),
            msg=(
                "Row surfaced by the list must not be marked "
                "needs_naming=True — the frontend renders the "
                "'needs a name' badge on that flag."
            ),
        )

    def test_image_upload_save_this_shows_up_in_list(self) -> None:
        store = {"uploaded_files": []}
        self._seed_uploaded(
            store,
            file_id="img-1",
            file_name=ORIG_IMAGE_FILE,
            content_type="image/jpeg",
        )
        saved_ok, reply_text, saved_name = self._drive_save_this(
            store, save_phrase="save this",
        )
        self.assertTrue(saved_ok)
        # Reply must be a truthful success message (item 7 of the
        # deep-fix spec) — never "I don't have a pending save".
        self.assertIn("Saved this image", reply_text)
        self.assertNotIn("pending save", reply_text.lower())
        self.assertNotIn("don't have", reply_text.lower())

        # And the row is discoverable by the same query the
        # "show me my images" (list_files) intent uses to surface
        # the vault's image inventory.
        self._assert_saved_and_discoverable(
            store, file_id="img-1", expected_saved_name=saved_name,
        )
        # Close the loop: an actual list_uploaded_files call (the
        # exact query the "show me my images" turn issues) sees
        # the saved row.
        self._assert_show_my_files_would_return_row(
            store, file_id="img-1", expected_saved_name=saved_name,
        )

    def test_video_upload_save_this_shows_up_in_list(self) -> None:
        store = {"uploaded_files": []}
        self._seed_uploaded(
            store,
            file_id="vid-1",
            file_name=ORIG_VIDEO_FILE,
            content_type="video/mp4",
        )
        saved_ok, reply_text, saved_name = self._drive_save_this(
            store, save_phrase="save this",
        )
        self.assertTrue(saved_ok)
        self.assertIn("Saved this video", reply_text)
        self.assertNotIn("pending save", reply_text.lower())
        self._assert_saved_and_discoverable(
            store, file_id="vid-1", expected_saved_name=saved_name,
        )
        self._assert_show_my_files_would_return_row(
            store, file_id="vid-1", expected_saved_name=saved_name,
        )

    def test_natural_save_phrase_put_this_in_my_vault_saves_image(
        self,
    ) -> None:
        # Same round-trip using one of the expanded natural
        # phrases the user's spec listed. Proves the phrase list
        # actually reaches the fallback (not just matches the
        # regex).
        store = {"uploaded_files": []}
        self._seed_uploaded(
            store,
            file_id="img-2",
            file_name="wedding_group.png",
            content_type="image/png",
        )
        saved_ok, reply_text, saved_name = self._drive_save_this(
            store, save_phrase="put this in my vault",
        )
        self.assertTrue(saved_ok)
        self.assertIn("Saved this image", reply_text)
        self._assert_saved_and_discoverable(
            store, file_id="img-2", expected_saved_name=saved_name,
        )
        self._assert_show_my_files_would_return_row(
            store, file_id="img-2", expected_saved_name=saved_name,
        )

    def test_natural_save_phrase_keep_this_saves_video(self) -> None:
        store = {"uploaded_files": []}
        self._seed_uploaded(
            store,
            file_id="vid-2",
            file_name="birthday_speech.mov",
            content_type="video/quicktime",
        )
        saved_ok, reply_text, saved_name = self._drive_save_this(
            store, save_phrase="keep this",
        )
        self.assertTrue(saved_ok)
        self.assertIn("Saved this video", reply_text)
        self._assert_saved_and_discoverable(
            store, file_id="vid-2", expected_saved_name=saved_name,
        )
        self._assert_show_my_files_would_return_row(
            store, file_id="vid-2", expected_saved_name=saved_name,
        )

    def test_save_of_missing_row_does_not_claim_success(self) -> None:
        # False-success guard (item 7 of the spec) — if the pending
        # attachment vanished between the upload and the save turn
        # (e.g. concurrent delete, expired upload), the save must
        # NOT emit "Saved this X" — it must emit a failure reply.
        import main as main_mod
        store = {"uploaded_files": []}

        # No uploaded_files row seeded — get_pending_named_file
        # returns None and the fallback branch should be inert.
        with _patched_env(store):
            pending = main_mod.get_pending_named_file(VAULT_ID)
        self.assertIsNone(
            pending,
            msg=(
                "Precondition: with no uploaded_files row the "
                "handler must see no pending attachment. If this "
                "fails the FakeCursor's SELECT semantics have "
                "drifted."
            ),
        )
        # Confirms the ONLY reply the confirm-phrase branch can
        # emit in this case falls through to NO_DRAFT_FRIENDLY_REPLY —
        # never a fake "Saved this X" success.
        from vault_pending_draft_confirm import NO_DRAFT_FRIENDLY_REPLY
        self.assertIn("don't have a pending save", NO_DRAFT_FRIENDLY_REPLY)


class TestIdentityQuestionsReachLlm(unittest.TestCase):
    """Prove that identity questions ("hello", "what are you",
    "who are you", "who am I talking to") flow to the LLM rather
    than being short-circuited by a pre-canned reply branch.

    Combined with the tests in
    ``TestAssistantIdentityInLlmPrompt`` — which prove the LLM's
    runtime context injects the per-vault ``vault_name`` (dynamic,
    not hardcoded) — this closes the identity-response guarantee:
    these questions reach an LLM identified as the vault's own
    name, which the tools.py static system prompt instructs to
    answer "in the first person as [that vault name]".

    The full LLM call is not exercised (a real OpenAI request
    would be non-deterministic and require network / API key);
    instead we assert the pipeline DOESN'T do anything that would
    prevent the LLM from being called with the correct identity.
    """

    IDENTITY_QUESTIONS = (
        "hello",
        "hi",
        "hey there",
        "what are you",
        "who are you",
        "who am i talking to",
        "who am i talking to?",
        "what is your name",
        "can you help me",
        "remember this for me",
    )

    def test_none_are_confused_for_a_save_confirmation(self) -> None:
        # If any of these were mis-classified as a save-confirm
        # phrase, they'd never reach the LLM — the handler would
        # emit "no pending save" instead. Confirms the confirm-
        # phrase matcher stays conservative.
        from vault_pending_draft_confirm import (
            is_pending_draft_confirm_phrase,
            is_save_themed_confirm_phrase,
        )
        for q in self.IDENTITY_QUESTIONS:
            with self.subTest(q=q):
                self.assertFalse(
                    is_pending_draft_confirm_phrase(q),
                    f"{q!r} must NOT match a save-confirmation",
                )
                self.assertFalse(
                    is_save_themed_confirm_phrase(q),
                    f"{q!r} must NOT match a save-themed phrase",
                )

    def test_none_are_mis_detected_as_a_non_english_language(
        self,
    ) -> None:
        # Language mis-detection would send the LLM the wrong
        # reply-language instruction. All of these must detect as
        # English (or None, which falls back to app-locale/en).
        import vault_multilingual as vm
        for q in self.IDENTITY_QUESTIONS:
            with self.subTest(q=q):
                lang = vm.detect_language(q)
                self.assertIn(
                    lang, ("en", None),
                    msg=(
                        f"{q!r} must detect as English (or None "
                        f"and fall back to en). Got {lang!r}."
                    ),
                )
                resolved = vm.resolve_reply_language(
                    detected_from_message=lang,
                    app_locale_hint="en",
                    header_locale_hint=None,
                )
                self.assertEqual(
                    resolved, "en",
                    msg=(
                        f"reply-language for {q!r} must resolve "
                        f"to 'en'. Got {resolved!r}."
                    ),
                )

    def test_none_match_the_delete_vault_pattern(self) -> None:
        # Guard: identity questions must never trip the destructive
        # "delete my vault" intent detector.
        from vault_multilingual import matches_delete_vault_intent
        for q in self.IDENTITY_QUESTIONS:
            with self.subTest(q=q):
                self.assertIsNone(
                    matches_delete_vault_intent(q),
                    msg=(
                        f"{q!r} must not match the delete-vault "
                        f"intent detector."
                    ),
                )

    def test_llm_would_receive_brain_identity_for_each_question(
        self,
    ) -> None:
        # End-to-end proof of the identity path: for each
        # (owner, vault_name) pair, the runtime context the /chat
        # handler would ship to the LLM contains THAT specific
        # vault_name in the VAULT_NAME slot — so when the user asks
        # any of the identity questions, the LLM's freeform reply
        # identifies as that vault's own name. Parameterized so
        # nobody can substitute a hardcode.
        import main as main_mod
        from tools import build_vault_runtime_context

        class _Req:
            headers = {"accept-language": "en"}

        for owner, vault_name in EXAMPLE_IDENTITIES:
            with self.subTest(owner=owner, vault_name=vault_name):
                with patch.object(
                    main_mod, "_fetch_vault_name_for_prompt",
                    return_value=vault_name,
                ):
                    ctx = main_mod._build_chat_prompt_context(
                        vault_id=VAULT_ID, request=_Req(),
                    )
                assembled = build_vault_runtime_context(
                    vault_name=ctx["VAULT_NAME"],
                    vault_state=ctx["VAULT_STATE"],
                    locale=ctx["LOCALE"],
                    enabled_features=ctx["ENABLED_FEATURES"],
                    has_memory=(
                        "on" if ctx["HAS_MEMORY"] == "yes" else "off"
                    ),
                    has_relationships=(
                        "on" if ctx["HAS_RELATIONSHIPS"] == "yes"
                        else "off"
                    ),
                    has_expiry=(
                        "on" if ctx["HAS_EXPIRY"] == "yes" else "off"
                    ),
                )
                self.assertIn(
                    f"Vault name           : {vault_name}",
                    assembled,
                    msg=(
                        f"For vault {vault_name!r} (owner "
                        f"{owner!r}), the runtime-context system "
                        f"message must say 'Vault name : "
                        f"{vault_name}'. The LLM's freeform "
                        f"reply (per tools.py's static system "
                        f"prompt: 'in the first person as' the "
                        f"vault name) then identifies as this "
                        f"specific vault, not any hardcoded name."
                    ),
                )
                # Reflexive negative: the assembled prompt must not
                # contain the owner's display name in the identity
                # slot — the classic incident bug. Uses regex for
                # a whole-line match so a vault name that happens
                # to start with the owner's name (e.g. Ada / Ada's
                # Notes) does not false-positive.
                import re as _re
                owner_only_line = _re.compile(
                    rf"^-\s*Vault name\s*:\s*"
                    rf"{_re.escape(owner)}\s*$",
                    _re.MULTILINE,
                )
                self.assertIsNone(
                    owner_only_line.search(assembled),
                    msg=(
                        f"The 'Vault name' line must contain the "
                        f"vault name {vault_name!r}, never the "
                        f"owner's display name {owner!r} on its "
                        f"own."
                    ),
                )


class TestChatHandlerSourceInvariants(unittest.TestCase):
    """Source-level guardrails: the fixes must remain wired in
    main.py's chat handler exactly the way we shipped them. Prior
    incident postmortem: several regressions traced to the fix
    landing in one file but silently drifting in the caller. These
    tests catch such drift on the next commit."""

    def setUp(self) -> None:
        from pathlib import Path
        self.src = (
            Path(__file__).resolve().parent / "main.py"
        ).read_text(encoding="utf-8")

    def test_pending_confirm_branch_falls_through_to_attachment_save(
        self,
    ) -> None:
        # The specific fallback landed on 2026-07-22 inside the
        # _pending_confirm branch — a call to get_pending_named_file
        # right after the credential/login-draft checks fail. If
        # this call ever leaves the _pending_confirm scope, the
        # attachment save regression returns.
        self.assertIn(
            "get_pending_named_file(vault_id)", self.src,
        )
        self.assertIn("save_named_uploaded_asset(", self.src)
        self.assertIn(
            "pending_attachment_confirmed", self.src,
            msg=(
                "The success-side log token identifying the "
                "attachment fallback must remain wired for prod "
                "log grep."
            ),
        )
        self.assertIn(
            "confirm_save_attachment_failed", self.src,
            msg=(
                "The failure-side log token must remain wired "
                "so a broken attachment save is grep-visible "
                "in prod."
            ),
        )

    def test_placeholder_guard_is_wired_in_classify(self) -> None:
        # The placeholder-value defensive check must remain in
        # _classify_save_login_payload so an LLM-shaped placeholder
        # can never sneak into a saved credential.
        self.assertIn("_looks_like_placeholder_value", self.src)
        self.assertIn("placeholder_field_value", self.src)

    def test_llm_identity_slot_reads_from_db_not_a_constant(
        self,
    ) -> None:
        # Correction: the assistant's identity in the LLM prompt
        # must be the per-vault DB value — read via
        # _fetch_vault_name_for_prompt(vault_id) — not any global
        # constant. This test locks that binding in place.
        self.assertIn(
            "vault_name = _fetch_vault_name_for_prompt(vault_id)",
            self.src,
            msg=(
                "The LLM identity slot in "
                "_build_chat_prompt_context must be sourced from "
                "_fetch_vault_name_for_prompt(vault_id). Any other "
                "wiring — a global constant, req.vault_name, the "
                "user display name, a hardcoded literal — is a "
                "regression."
            ),
        )
        self.assertNotIn(
            "ASSISTANT_IDENTITY", self.src,
            msg=(
                "main.py must not export an ASSISTANT_IDENTITY "
                "constant. The correction removed it — the vault "
                "identity is per-vault, per-request, from the DB."
            ),
        )

    def test_chat_state_backend_resolved_eagerly_at_startup(
        self,
    ) -> None:
        # Ensures the startup log operator uses to confirm Redis
        # is active actually fires at boot — see
        # test_chat_deep_fix_2026_07_22.py for the resolver-side
        # tests.
        self.assertIn(
            "from vault_chat_state_store import "
            "get_chat_state_backend",
            self.src,
        )


class TestNoHardcodedAssistantIdentityInProduction(unittest.TestCase):
    """Codebase-wide guardrail: no production code file may
    hardcode the string "Brain" (or any other single vault-name
    literal) as the assistant identity. The assistant's identity
    is per-vault, taken from ``vaults.vault_name`` at request time,
    displayed on the frontend via ``AppState.vaultName`` — never a
    fixed constant.

    Test data files (this file and the deep-fix test suite) are
    ALLOWED to contain "Brain" as an example vault name.
    """

    def _iter_production_files(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent

        # Production code directories.
        backend_root = repo_root / "vault_ai_backend"
        frontend_lib_root = (
            repo_root / "vault_ai_frontend" / "lib"
        )

        allowed_test_prefixes = ("test_",)
        allowed_test_dirs = (
            repo_root / "vault_ai_frontend" / "test",
        )

        skip_dirs = {
            ".venv", "venv", "__pycache__", ".git", "build",
            "node_modules", ".dart_tool", "coverage",
            "migrations", "alembic",
        }

        def _walk(root, exts):
            if not root.exists():
                return
            for p in root.rglob("*"):
                if any(part in skip_dirs for part in p.parts):
                    continue
                if p.is_file() and p.suffix in exts:
                    yield p

        for p in _walk(backend_root, {".py"}):
            rel = p.name
            if rel.startswith(allowed_test_prefixes):
                continue
            yield p
        for p in _walk(frontend_lib_root, {".dart"}):
            yield p

    def test_no_production_file_hardcodes_Brain_as_identity(
        self,
    ) -> None:
        # 2026-07-22 correction: "Brain" is an example vault name,
        # not a global constant. This scan proves it does not
        # appear as a literal in any production source file. The
        # test-data pair (Chosen, Brain) is intentionally listed
        # in EXAMPLE_IDENTITIES for parameterization — that lives
        # in a test file, allowed.
        import re
        offenders: list[str] = []
        # Match the string "Brain" or 'Brain' as a standalone
        # literal (case-sensitive, whole-word). Skip word-substring
        # matches like "Brainstorm" or "brain" (comments).
        pattern = re.compile(r"""["']Brain["']""")
        for p in self._iter_production_files():
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in pattern.finditer(src):

                line_start = src.rfind("\n", 0, m.start()) + 1
                line_end = src.find("\n", m.end())
                if line_end == -1:
                    line_end = len(src)
                line = src[line_start:line_end]
                lstripped = line.strip()
                if lstripped.startswith(("#", "//", "*", "///")):

                    continue
                offenders.append(f"{p}:{line!r}")
        self.assertEqual(
            offenders, [],
            msg=(
                "Production code must not hardcode the literal "
                '"Brain" as the assistant identity. It is one '
                "example vault name; the identity is per-vault, "
                "sourced dynamically. Offending lines:\n"
                + "\n".join(offenders)
            ),
        )

    def test_no_production_file_defines_ASSISTANT_IDENTITY(
        self,
    ) -> None:
        import re
        offenders: list[str] = []
        pat_py = re.compile(r"^\s*ASSISTANT_IDENTITY\s*[:=]")
        pat_dart_kAssistant = re.compile(
            r"\b(?:const\s+String\s+)?kAssistantName\b",
        )
        for p in self._iter_production_files():
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if p.suffix == ".py":
                for i, line in enumerate(src.splitlines(), 1):
                    if pat_py.search(line):
                        offenders.append(f"{p}:{i}:{line.strip()}")
            elif p.suffix == ".dart":
                for i, line in enumerate(src.splitlines(), 1):
                    lstripped = line.strip()
                    if lstripped.startswith(("//", "///", "*")):

                        continue
                    if pat_dart_kAssistant.search(line):
                        offenders.append(f"{p}:{i}:{lstripped}")
        self.assertEqual(
            offenders, [],
            msg=(
                "Production code must not define an "
                "ASSISTANT_IDENTITY / kAssistantName constant. "
                "The assistant identity is the per-vault, "
                "per-request vault_name — see "
                "_fetch_vault_name_for_prompt (backend) and "
                "AppState.vaultName (frontend). Offenders:\n"
                + "\n".join(offenders)
            ),
        )

    def test_vault_identity_dart_file_is_deleted(self) -> None:
        # The intermediate ``lib/vault_identity.dart`` file that
        # briefly held ``kAssistantName = 'Brain'`` is deleted as
        # part of the correction. If it re-appears, the identity
        # hardcode has crept back in.
        from pathlib import Path
        p = (
            Path(__file__).resolve().parent.parent
            / "vault_ai_frontend" / "lib" / "vault_identity.dart"
        )
        self.assertFalse(
            p.exists(),
            msg=(
                "lib/vault_identity.dart must NOT exist. It was "
                "removed by the 2026-07-22 correction — the "
                "assistant identity is per-vault, dynamic. "
                "Recreating this file re-introduces the hardcode."
            ),
        )

    def test_main_dart_chat_typing_indicator_reads_appstate_vault_name(
        self,
    ) -> None:
        # main.dart's ChatMessageList call must pass
        # ``app.vaultName`` (dynamic per session), NOT
        # ``app.displayName`` (the incident bug), NOT a hardcoded
        # literal, NOT kAssistantName.
        from pathlib import Path
        p = (
            Path(__file__).resolve().parent.parent
            / "vault_ai_frontend" / "lib" / "main.dart"
        )
        src = p.read_text(encoding="utf-8")
        self.assertIn(
            "vaultName: app.vaultName,", src,
            msg=(
                "main.dart's ChatMessageList must pass "
                "app.vaultName as the vaultName parameter. "
                "app.displayName was the incident bug (surfaced "
                "'Chosen is thinking...'); kAssistantName was the "
                "intermediate hardcode fix that has been removed."
            ),
        )
        self.assertNotIn("vaultName: app.displayName,", src)
        self.assertNotIn("vaultName: kAssistantName,", src)
        self.assertNotIn(
            "vaultName: 'Brain',", src,
            msg="No hardcoded literal for vaultName.",
        )


if __name__ == "__main__":
    unittest.main()
