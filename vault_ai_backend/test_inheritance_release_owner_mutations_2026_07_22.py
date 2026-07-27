"""Regression tests for the 2026-07-22 pairing_state-aware
credential-mutation gate.

Root cause pinned in production
-------------------------------

Before this fix, ``_refuse_if_access_in_flight`` refused every
credential mutation whose link had a non-null ``access_requested_at``
or ``cooldown_ends_at``. Those columns are stamped by
``/inheritance/access/request`` and are only cleared by
``/access/cancel`` and ``/access/reject``. The forward path
``request → cooldown_active → approved → released`` leaves them
populated forever, so any released link was permanently locked out
of both ``/inheritance/credentials/replace`` and
``/inheritance/credentials/delete`` with ``INH-CRED-007`` — see
production log ``[INH] reference=INH-CRED-007 status=409
details={'link_id': 8}`` on both replace and delete requests.

The fix reads ``pairing_state`` (the authoritative source of truth
per the release-flow docstring) and refuses only during
``cooldown_active`` — the one state where a credential mutation
would race a beneficiary who is watching the countdown. Replace /
delete on ``credentials_saved`` / ``approved`` / ``claimable`` /
``released`` are permitted, and the release-timestamp triple is
cleared as part of the same transition (mirrors what /access/cancel
and /access/reject already do).

Scope of these tests
--------------------

* ``_refuse_if_access_in_flight`` refuses only during
  ``cooldown_active`` (pure unit tests).
* ``_clear_release_timestamps_if_stale`` clears the triple only for
  states that ever populated it.
* The route surface: ``/inheritance/credentials/replace`` and
  ``/inheritance/credentials/delete`` behave correctly across every
  reachable ``pairing_state``.
* Stage allowlist on the ``/inheritance/client-diagnostic``
  endpoint accepts every known ``kRevealStage*`` value emitted by
  the frontend and rejects unknown stages with the operator-safe
  ``INH-CRED-004``.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routes import inheritance_credential_routes as icr
from inheritance_error_codes import INHERR


# ---------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------


_OWNER_VAULT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_BENEFICIARY_VAULT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _valid_package_body(*, link_id: int = 42) -> dict:
    """Wire-legal credential package. Bytes are junk — routes never
    decrypt; the fake escrow just stores them opaquely."""
    return {
        "beneficiary_link_id": link_id,
        "crypto_version": 1,
        "encrypted_payload": _b64u(b"\x11" * 48),
        "payload_nonce":     _b64u(b"\x22" * 12),
        "wrapped_key":       _b64u(b"\x33" * 48),
        "wrapping_ephemeral_pk": _b64u(b"\x44" * 32),
        "wrapping_nonce":    _b64u(b"\x55" * 12),
    }


# ---------------------------------------------------------------------
# Unit tests: the gate itself
# ---------------------------------------------------------------------


class TestRefuseIfAccessInFlight:
    """Pure unit tests over the state-aware gate."""

    def _link(self, *, pairing_state: str,
              access_requested_at: Optional[datetime] = None,
              cooldown_ends_at: Optional[datetime] = None,
              legacy_status: str = "linked") -> dict:
        return {
            "id": 42,
            "pairing_state": pairing_state,
            "access_requested_at": access_requested_at,
            "cooldown_ends_at": cooldown_ends_at,
            "status": legacy_status,
        }

    @pytest.mark.parametrize("state", [
        "paired_no_credentials",
        "credentials_saved",
        "approved",
        "claimable",
        "released",
        "needs_reencryption",
        "revoked",
        "rejected",
    ])
    def test_state_permits_mutation_even_with_stale_timestamps(
        self, state: str,
    ) -> None:
        # Simulate the released-link production case: timestamps are
        # populated (they were stamped at /request time and never
        # cleared) but pairing_state has advanced past cooldown.
        link = self._link(
            pairing_state=state,
            access_requested_at=_now(),
            cooldown_ends_at=_now(),
        )
        # Must NOT raise.
        icr._refuse_if_access_in_flight(link)

    def test_cooldown_active_refuses_with_inh_cred_007(self) -> None:
        link = self._link(
            pairing_state="cooldown_active",
            access_requested_at=_now(),
            cooldown_ends_at=_now(),
        )
        with pytest.raises(HTTPException) as ei:
            icr._refuse_if_access_in_flight(link)
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == INHERR.CRED_ACCESS_IN_FLIGHT.code

    def test_gate_ignores_stale_timestamps_when_state_is_terminal(
        self,
    ) -> None:
        # Regression pin: the OLD gate would have refused this because
        # access_requested_at is not None. The NEW gate must allow it
        # because pairing_state is 'released'.
        link = self._link(
            pairing_state="released",
            access_requested_at=_now(),
            cooldown_ends_at=_now(),
        )
        icr._refuse_if_access_in_flight(link)  # must not raise

    def test_pairing_state_overrides_legacy_transfer_status(self) -> None:
        # Once pairing_state is populated, it is authoritative. A
        # stale legacy transfer_pending status must not block owner
        # credential mutations.
        link = self._link(
            pairing_state="credentials_saved",
            legacy_status="transfer_pending",
        )
        icr._refuse_if_access_in_flight(link)

    def test_blank_pairing_state_still_uses_legacy_transfer_status(
        self,
    ) -> None:
        # Rows that truly predate pairing_state still fall back to the
        # legacy status field.
        link = self._link(
            pairing_state="",
            legacy_status="transfer_pending",
        )
        with pytest.raises(HTTPException) as ei:
            icr._refuse_if_access_in_flight(link)
        assert ei.value.detail["code"] == INHERR.CRED_ACCESS_IN_FLIGHT.code

    def test_null_pairing_state_falls_through_and_permits(
        self,
    ) -> None:
        # Pre-migration rows with no pairing_state at all must not
        # trigger a NoneType comparison bug.
        link = self._link(pairing_state="")
        icr._refuse_if_access_in_flight(link)


class TestClearReleaseTimestampsIfStale:
    """Pure unit tests over the new timestamp cleanup."""

    class _CaptureCursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple]] = []

        def execute(self, sql: str, params: tuple) -> None:
            self.calls.append((" ".join(sql.split()), params))

    @pytest.mark.parametrize("prior_state", [
        "approved", "claimable", "released", "needs_reencryption",
    ])
    def test_clears_when_prior_state_had_stale_timestamps(
        self, prior_state: str,
    ) -> None:
        cur = self._CaptureCursor()
        icr._clear_release_timestamps_if_stale(
            cur, link_id=42, prior_state=prior_state,
        )
        assert len(cur.calls) == 1
        sql, params = cur.calls[0]
        assert "UPDATE beneficiary_links" in sql
        assert "access_requested_at = NULL" in sql
        assert "cooldown_ends_at = NULL" in sql
        assert "decision_at = NULL" in sql
        assert params == (42,)

    @pytest.mark.parametrize("prior_state", [
        "paired_no_credentials",
        "credentials_saved",
        "cooldown_active",  # never reachable (gate blocks) but safe
        "revoked",
        "",  # legacy row
    ])
    def test_noop_when_prior_state_never_had_stale_timestamps(
        self, prior_state: str,
    ) -> None:
        cur = self._CaptureCursor()
        icr._clear_release_timestamps_if_stale(
            cur, link_id=42, prior_state=prior_state,
        )
        assert cur.calls == []


# ---------------------------------------------------------------------
# Route-level integration: replace + delete across every state
# ---------------------------------------------------------------------


class _FakeCursor:
    """Minimal cursor that recognizes only the SQL shapes issued by
    ``save_credentials`` / ``replace_credentials`` / ``delete_credentials``
    / the new ``_clear_release_timestamps_if_stale`` helper. Anything
    else falls through as rowcount=0 so the test fails loudly.
    """

    def __init__(self, store: dict) -> None:
        self._store = store
        self._last: Any = None
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()) -> None:
        s = " ".join(sql.split())
        upper = s.upper()

        # -- beneficiary_links: SELECT (with or without FOR UPDATE)
        if (upper.startswith("SELECT ID, PASSER_VAULT_ID,")
                and "FROM BENEFICIARY_LINKS" in upper):
            link_id, owner = params
            row = self._store["links"].get(link_id)
            if row and row["passer_vault_id"] == owner:
                self._last = dict(row)
            else:
                self._last = None
            self.rowcount = 1 if self._last else 0
            return

        # -- inheritance_credentials: SELECT 1 (save's already-saved check)
        if ("FROM INHERITANCE_CREDENTIALS" in upper
                and "LIMIT 1" in upper):
            link_id = params[0]
            for r in self._store["escrow"].values():
                if (r["beneficiary_link_id"] == link_id
                        and r["deleted_at"] is None):
                    self._last = {"?column?": 1}
                    self.rowcount = 1
                    return
            self._last = None
            self.rowcount = 0
            return

        # -- inheritance_credentials: INSERT
        if upper.startswith("INSERT INTO INHERITANCE_CREDENTIALS"):
            (link_id, owner, crypto_v, encrypted, p_nonce,
             wrapped, eph_pk, w_nonce) = params
            new_id = self._store["next_escrow_id"]
            self._store["next_escrow_id"] += 1
            self._store["escrow"][new_id] = {
                "id": new_id,
                "beneficiary_link_id": link_id,
                "owner_vault_id": owner,
                "crypto_version": crypto_v,
                "encrypted_payload": bytes(encrypted),
                "payload_nonce":     bytes(p_nonce),
                "wrapped_key":       bytes(wrapped),
                "wrapping_ephemeral_pk": bytes(eph_pk),
                "wrapping_nonce":    bytes(w_nonce),
                "state": "credentials_saved",
                "released_at": None,
                "revoked_at": None,
                "deleted_at": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            self.rowcount = 1
            return

        # -- inheritance_credentials: soft-delete
        if (upper.startswith("UPDATE INHERITANCE_CREDENTIALS")
                and "DELETED_AT = NOW()" in upper):
            link_id = params[0]
            self.rowcount = 0
            for r in self._store["escrow"].values():
                if (r["beneficiary_link_id"] == link_id
                        and r["deleted_at"] is None):
                    r["deleted_at"] = _now()
                    r["updated_at"] = _now()
                    self.rowcount += 1
            return

        # -- beneficiary_links: UPDATE pairing_state = 'credentials_saved'
        if (upper.startswith("UPDATE BENEFICIARY_LINKS")
                and "PAIRING_STATE = 'CREDENTIALS_SAVED'" in upper):
            link_id = params[0]
            row = self._store["links"].get(link_id)
            if row:
                row["pairing_state"] = "credentials_saved"
                self.rowcount = 1
            return

        # -- beneficiary_links: UPDATE pairing_state = 'paired_no_credentials'
        if (upper.startswith("UPDATE BENEFICIARY_LINKS")
                and "PAIRING_STATE = 'PAIRED_NO_CREDENTIALS'" in upper):
            link_id = params[0]
            row = self._store["links"].get(link_id)
            if row:
                row["pairing_state"] = "paired_no_credentials"
                self.rowcount = 1
            return

        # -- beneficiary_links: clear the release-timestamp triple
        if (upper.startswith("UPDATE BENEFICIARY_LINKS")
                and "ACCESS_REQUESTED_AT = NULL" in upper
                and "COOLDOWN_ENDS_AT = NULL" in upper
                and "DECISION_AT = NULL" in upper):
            link_id = params[0]
            row = self._store["links"].get(link_id)
            if row:
                row["access_requested_at"] = None
                row["cooldown_ends_at"] = None
                row["decision_at"] = None
                self.rowcount = 1
            return

        # Unrecognized SQL: fail loud in tests by leaving rowcount=0.
        self.rowcount = 0

    def fetchone(self) -> Optional[dict]:
        r = self._last
        self._last = None
        return r

    def close(self) -> None:
        return None


class _FakeConn:
    def __init__(self, store: dict) -> None:
        self._store = store

    def cursor(self, *args: Any, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(self._store)

    def commit(self) -> None: return None
    def rollback(self) -> None: return None
    def close(self) -> None: return None


@pytest.fixture()
def store_at_state():
    """Factory: build a fresh store parameterised by pairing_state and
    whether an escrow row exists / has stale timestamps."""

    def _build(*, pairing_state: str,
               with_escrow: bool = True,
               with_stale_timestamps: bool = False,
               legacy_status: str = "linked",
               owner_vault_id: str = _OWNER_VAULT_ID,
               beneficiary_vault_id: Optional[str] = _BENEFICIARY_VAULT_ID,
               link_id: int = 42) -> dict:
        now = _now()
        link = {
            "id": link_id,
            "passer_vault_id": owner_vault_id,
            "beneficiary_vault_id": beneficiary_vault_id,
            "status": legacy_status,
            "pairing_state": pairing_state,
            "access_requested_at": now if with_stale_timestamps else None,
            "cooldown_ends_at": now if with_stale_timestamps else None,
            "decision_at": now if with_stale_timestamps else None,
        }
        store: dict = {
            "links": {link_id: link},
            "escrow": {},
            "next_escrow_id": 100,
        }
        if with_escrow:
            store["escrow"][77] = {
                "id": 77,
                "beneficiary_link_id": link_id,
                "owner_vault_id": owner_vault_id,
                "crypto_version": 1,
                "encrypted_payload": b"\x01" * 48,
                "payload_nonce": b"\x02" * 12,
                "wrapped_key": b"\x03" * 48,
                "wrapping_ephemeral_pk": b"\x04" * 32,
                "wrapping_nonce": b"\x05" * 12,
                "state": pairing_state,
                "released_at": None,
                "revoked_at": None,
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
            }
        return store

    return _build


def _build_client(store: dict):
    """Mount just the credential router with a fake DB + session."""
    original_get_db = icr.get_db
    icr.get_db = lambda: _FakeConn(store)

    def _override_session() -> dict:
        return {
            "vault_id": _OWNER_VAULT_ID,
            "vault_name": "test",
            "token_id": "test",
            "device_id": "test-dev",
        }

    app = FastAPI()
    app.include_router(icr.router)
    app.dependency_overrides[icr.verify_session_token] = _override_session
    client = TestClient(app)

    def _restore() -> None:
        icr.get_db = original_get_db

    return client, _restore


# ---- SAVE first credential package ---------------------------------


class TestSaveCredentials:

    def test_save_paired_no_credentials_with_legacy_transfer_pending_succeeds(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="paired_no_credentials",
            legacy_status="transfer_pending",
            with_escrow=False,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/save",
                json=_valid_package_body(),
            )
            assert r.status_code == 200, r.text
            assert r.json()["pairing_state"] == "credentials_saved"
            assert r.json()["credentials_saved"] is True
            assert 100 in store["escrow"]
            assert store["links"][42]["pairing_state"] == "credentials_saved"
        finally:
            restore()

    def test_save_when_credentials_saved_still_requires_replace(
        self, store_at_state,
    ) -> None:
        store = store_at_state(pairing_state="credentials_saved")
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/save",
                json=_valid_package_body(),
            )
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-005"
            assert 100 not in store["escrow"]
        finally:
            restore()

    @pytest.mark.parametrize("pairing_state, legacy_status", [
        ("unknown_state", "linked"),
        ("released", "linked"),
        ("paired_no_credentials", "cancelled"),
        ("paired_no_credentials", "deleted"),
    ])
    def test_save_rejects_invalid_cancelled_deleted_or_released_links(
        self, store_at_state, pairing_state: str, legacy_status: str,
    ) -> None:
        store = store_at_state(
            pairing_state=pairing_state,
            legacy_status=legacy_status,
            with_escrow=False,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/save",
                json=_valid_package_body(),
            )
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-007"
            assert 100 not in store["escrow"]
        finally:
            restore()

    def test_save_rejects_unpaired_link(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="paired_no_credentials",
            beneficiary_vault_id=None,
            with_escrow=False,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/save",
                json=_valid_package_body(),
            )
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-002"
            assert 100 not in store["escrow"]
        finally:
            restore()

    def test_save_rejects_wrong_owner(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="paired_no_credentials",
            owner_vault_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            with_escrow=False,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/save",
                json=_valid_package_body(),
            )
            assert r.status_code == 404, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-001"
            assert 100 not in store["escrow"]
        finally:
            restore()

    def test_save_rejects_malformed_encrypted_payload(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="paired_no_credentials",
            with_escrow=False,
        )
        client, restore = _build_client(store)
        try:
            body = _valid_package_body()
            body["encrypted_payload"] = _b64u(b"\x11" * 8)
            r = client.post("/inheritance/credentials/save", json=body)
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-004"
            assert 100 not in store["escrow"]
        finally:
            restore()


# ---- REPLACE across every reachable state -------------------------


class TestReplaceCredentials:

    def test_replace_when_credentials_saved_succeeds(
        self, store_at_state,
    ) -> None:
        store = store_at_state(pairing_state="credentials_saved")
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/replace",
                json=_valid_package_body(),
            )
            assert r.status_code == 200, r.text
            assert r.json()["pairing_state"] == "credentials_saved"
            # Old escrow row is soft-deleted, new row exists.
            assert store["escrow"][77]["deleted_at"] is not None
            assert 100 in store["escrow"]
            assert store["escrow"][100]["deleted_at"] is None
        finally:
            restore()

    def test_replace_during_cooldown_active_refuses_INH_CRED_007(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="cooldown_active",
            with_stale_timestamps=True,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/replace",
                json=_valid_package_body(),
            )
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-007"
            # Nothing mutated.
            assert store["escrow"][77]["deleted_at"] is None
            assert 100 not in store["escrow"]
        finally:
            restore()

    @pytest.mark.parametrize("state", [
        "approved", "claimable", "released",
    ])
    def test_replace_after_release_succeeds_and_clears_timestamps(
        self, store_at_state, state: str,
    ) -> None:
        # Reproduces the production incident on link 8: pairing_state
        # advanced to 'released' but access_requested_at was still
        # populated, so the old gate raised INH-CRED-007. The new gate
        # must accept the mutation AND clear the stale timestamps as
        # part of the same transition so the UI stops rendering a
        # bogus countdown.
        store = store_at_state(
            pairing_state=state,
            with_stale_timestamps=True,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/replace",
                json=_valid_package_body(),
            )
            assert r.status_code == 200, r.text
            assert r.json()["pairing_state"] == "credentials_saved"
            # Old escrow row soft-deleted (audit trail intact).
            assert store["escrow"][77]["deleted_at"] is not None
            # New row inserted, state resets.
            assert 100 in store["escrow"]
            # Stale timestamps cleared.
            link = store["links"][42]
            assert link["access_requested_at"] is None
            assert link["cooldown_ends_at"] is None
            assert link["decision_at"] is None
            assert link["pairing_state"] == "credentials_saved"
        finally:
            restore()

    def test_replace_with_no_escrow_row_refuses_INH_CRED_006(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="paired_no_credentials",
            with_escrow=False,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/replace",
                json=_valid_package_body(),
            )
            assert r.status_code == 404, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-006"
        finally:
            restore()


# ---- DELETE across every reachable state --------------------------


class TestDeleteCredentials:

    def test_delete_when_credentials_saved_succeeds(
        self, store_at_state,
    ) -> None:
        store = store_at_state(pairing_state="credentials_saved")
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/delete",
                json={"beneficiary_link_id": 42},
            )
            assert r.status_code == 200, r.text
            assert r.json()["pairing_state"] == "paired_no_credentials"
            assert r.json()["credentials_saved"] is False
            assert store["escrow"][77]["deleted_at"] is not None
            assert store["links"][42]["pairing_state"] == "paired_no_credentials"
        finally:
            restore()

    def test_delete_during_cooldown_active_refuses_INH_CRED_007(
        self, store_at_state,
    ) -> None:
        store = store_at_state(
            pairing_state="cooldown_active",
            with_stale_timestamps=True,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/delete",
                json={"beneficiary_link_id": 42},
            )
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-007"
            assert store["escrow"][77]["deleted_at"] is None
        finally:
            restore()

    @pytest.mark.parametrize("state", [
        "approved", "claimable", "released",
    ])
    def test_delete_after_release_succeeds_and_clears_timestamps(
        self, store_at_state, state: str,
    ) -> None:
        # The other half of the production incident: owner cannot
        # delete a released package. The new gate must allow it AND
        # clear the stale release-timestamp triple.
        store = store_at_state(
            pairing_state=state,
            with_stale_timestamps=True,
        )
        client, restore = _build_client(store)
        try:
            r = client.post(
                "/inheritance/credentials/delete",
                json={"beneficiary_link_id": 42},
            )
            assert r.status_code == 200, r.text
            assert r.json()["pairing_state"] == "paired_no_credentials"
            assert store["escrow"][77]["deleted_at"] is not None
            link = store["links"][42]
            assert link["pairing_state"] == "paired_no_credentials"
            assert link["access_requested_at"] is None
            assert link["cooldown_ends_at"] is None
            assert link["decision_at"] is None
        finally:
            restore()


# ---------------------------------------------------------------------
# Stage allowlist on /inheritance/client-diagnostic
# ---------------------------------------------------------------------


class TestClientDiagnosticStageAllowlist:
    """The frontend now emits a ``stage`` field naming the specific
    decrypt-pipeline step that failed. The backend allowlist must
    accept exactly the stages the frontend advertises and reject
    everything else with the operator-safe ``INH-CRED-004``.
    """

    # 2026-07-23: stage naming migrated to UPPER_SNAKE — mirrors
    # the kRevealStage* constants in
    # vault_ai_frontend/lib/services/inheritance_credentials.dart.
    _KNOWN_STAGES = [
        "LOAD_SECRET_KEY",
        "PARSE_EPHEMERAL_PUBLIC_KEY",
        "DERIVE_SHARED_SECRET",
        "DERIVE_WRAP_KEY",
        "UNWRAP_DATA_KEY",
        "DECRYPT_PAYLOAD",
        "UTF8_DECODE",
        "JSON_PARSE",
        "MAP_CREDENTIAL",
        "UNSTAGED_UNKNOWN",
    ]

    def setup_method(self, _method) -> None:
        icr._reset_diag_dedup_for_tests()

    def _client(self):
        original_get_db = icr.get_db
        icr.get_db = lambda: _FakeConn({"links": {}, "escrow": {}, "next_escrow_id": 100})
        def _override_session() -> dict:
            return {"vault_id": _OWNER_VAULT_ID, "vault_name": "t",
                    "token_id": "t", "device_id": "d"}
        app = FastAPI()
        app.include_router(icr.router)
        app.dependency_overrides[icr.verify_session_token] = _override_session

        def _restore() -> None:
            icr.get_db = original_get_db

        return TestClient(app), _restore

    def test_every_known_stage_is_accepted(self) -> None:
        for stage in self._KNOWN_STAGES:
            client, restore = self._client()
            try:
                r = client.post(
                    "/inheritance/client-diagnostic",
                    json={
                        "area": "reveal",
                        "reference_code": "INH-RETRIEVE-003-OTHER",
                        "stage": stage,
                    },
                )
                assert r.status_code == 200, (stage, r.text)
                assert r.json() == {"ok": True}
            finally:
                restore()

    def test_unknown_stage_is_rejected_as_INH_CRED_004(self) -> None:
        client, restore = self._client()
        try:
            r = client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-OTHER",
                    "stage": "definitely_not_a_real_stage",
                },
            )
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["code"] == "INH-CRED-004"
        finally:
            restore()

    def test_stage_field_is_optional(self) -> None:
        client, restore = self._client()
        try:
            r = client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-OTHER",
                },
            )
            assert r.status_code == 200, r.text
        finally:
            restore()
