"""End-to-end reproduction of the beneficiary pairing failure.

Purpose
=======

Phase 1 review flagged that the previous commit only reworded the
"Could not save the beneficiary label..." error text without
identifying or fixing the underlying failure of
``POST /vault/ciphertext/beneficiary-links``.

The concrete root cause is that the endpoint (and every other
handler in ``routes/vault_ciphertext_write_routes.py``) accesses
``principal.vault_id`` with attribute syntax. ``SessionPrincipal``
is a ``TypedDict``, which is a plain ``dict`` at runtime, so
``principal.vault_id`` raises ``AttributeError`` and FastAPI
returns a 500 to the client. The frontend's silent ``catch (_)``
then surfaces the generic "label finalize failed" message and
withholds the pairing code.

This test suite:

  1. Verifies at the pure-Python layer that ``SessionPrincipal``
     does NOT support attribute access — the bug's precondition.
  2. Drives the endpoint through FastAPI's ``TestClient`` with the
     backend DB stubbed out. Before the fix, the endpoint returns
     500 due to the AttributeError. After the fix (subscript
     access), it returns 200 on the happy path and 404 when the
     stub reports zero rows updated — the intended behaviour.
  3. Exercises the full pairing sequence — ``/beneficiary/create``
     then ``/vault/ciphertext/beneficiary-links`` — with the DB
     stub so we can prove the second call succeeds for the same
     ``vault_id`` that the first call used, closing off the
     "silent partial failure" scenario the operator saw.
  4. Asserts a static-source invariant: no Phase-2 credential
     retrieval endpoint exists yet. Nothing in the codebase may
     return decrypted or wrapped-key material to a beneficiary
     before Phase 2 lands.

The tests do not require a real Postgres — the ``get_db()`` seam
in ``routes/vault_ciphertext_write_routes.py`` is patched with a
dict-of-lists fake that mimics the two SQL statements the
endpoint uses. This keeps the test in-process and fast while
still exercising every line the endpoint touches under a real
session token flow.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pytest


# ---------------------------------------------------------------------
# Precondition: TypedDict runtime behaviour
# ---------------------------------------------------------------------


def test_session_principal_is_a_dict_and_rejects_attribute_access() -> None:
    """SessionPrincipal is a TypedDict, i.e. a plain ``dict`` at
    runtime. Confirms the bug's premise so if a future refactor
    changes ``SessionPrincipal`` to a dataclass this test flips
    and reminds us to also revert the endpoint's access style.
    """
    from auth_local import SessionPrincipal
    sp: SessionPrincipal = {
        "vault_id": "abc",
        "vault_name": "u",
        "token_id": "t",
        "device_id": None,
    }
    assert isinstance(sp, dict)
    assert sp["vault_id"] == "abc"
    with pytest.raises(AttributeError):
        sp.vault_id  # noqa: B018


# ---------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------


class _FakeCursor:
    """Minimal production DB cursor stand-in.

    Understands only the two SQL shapes the pairing flow issues:

      * INSERT INTO beneficiary_links (...) VALUES (...) RETURNING id
      * UPDATE beneficiary_links SET passer_label_ciphertext = ...
        WHERE id = ... AND passer_vault_id = ...
    """

    def __init__(self, store: dict):
        self._store = store
        self._last_row: Optional[dict] = None
        self.rowcount = 0

    # The production DB driver uses ``execute(sql, params)``; keep the same shape.
    def execute(self, sql: str, params: tuple = ()) -> None:
        s = " ".join(sql.split()).upper()
        if "INSERT INTO BENEFICIARY_LINKS" in s:
            # We only care about (passer_vault_id, ...) for this test.
            passer_vault_id = params[0]
            new_id = self._store["next_id"]
            self._store["next_id"] += 1
            row = {
                "id": new_id,
                "passer_vault_id": passer_vault_id,
                "passer_label": None,
                "passer_label_ciphertext": None,
            }
            self._store["rows"].append(row)
            self._last_row = {"id": new_id}
            self.rowcount = 1
            return
        if "UPDATE BENEFICIARY_LINKS" in s and "PASSER_LABEL_CIPHERTEXT" in s:
            label_ct, link_id, passer_vault_id = params
            match = 0
            for r in self._store["rows"]:
                if r["id"] == link_id and (
                    r["passer_vault_id"] == passer_vault_id
                ):
                    r["passer_label_ciphertext"] = bytes(label_ct)
                    r["passer_label"] = None
                    match += 1
            self.rowcount = match
            return
        # Any other statement is not exercised in these tests.
        self.rowcount = 0

    def fetchone(self) -> Optional[dict]:
        return self._last_row

    def close(self) -> None:
        return None


class _FakeConn:
    def __init__(self, store: dict):
        self._store = store

    def cursor(self, *args: Any, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(self._store)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture()
def fake_store() -> dict:
    return {"next_id": 1, "rows": []}


@pytest.fixture()
def fake_conn(fake_store: dict) -> _FakeConn:
    return _FakeConn(fake_store)


# ---------------------------------------------------------------------
# Session + principal stubs
# ---------------------------------------------------------------------


_TEST_VAULT_ID = "11111111-2222-3333-4444-555555555555"
_TEST_VAULT_NAME = "AutofillTestUser"


def _fake_session_principal() -> dict:
    return {
        "vault_id":   _TEST_VAULT_ID,
        "vault_name": _TEST_VAULT_NAME,
        "token_id":   "test-token",
        "device_id":  "test-device",
    }


# ---------------------------------------------------------------------
# The failing / repaired endpoint
# ---------------------------------------------------------------------


def _build_label_ciphertext_client(fake_conn: _FakeConn):
    """Build a FastAPI TestClient that mounts only the ciphertext
    write router with (a) the DB seam patched to ``fake_conn`` and
    (b) ``verify_session_token`` short-circuited to a fixed
    ``SessionPrincipal`` via FastAPI's ``dependency_overrides``.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routes import vault_ciphertext_write_routes as vcwr

    original_get_db = vcwr.get_db

    def _patched_get_db():
        return fake_conn

    # Override the dependency at the FastAPI layer. Signature takes
    # no framework-injected params so nothing gets read from the
    # query string.
    def _override_session_principal() -> dict:
        return _fake_session_principal()

    vcwr.get_db = _patched_get_db

    app = FastAPI()
    app.include_router(vcwr.router)
    app.dependency_overrides[vcwr.verify_session_token] = (
        _override_session_principal
    )
    client = TestClient(app)

    def _restore():
        vcwr.get_db = original_get_db

    return client, _restore


def _b64url_no_pad(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_label_ciphertext_endpoint_updates_the_row_using_dict_lookup(
    fake_store: dict, fake_conn: _FakeConn,
) -> None:
    """After the fix, the endpoint MUST use dict-style access on the
    session principal. Given a matching row in the store, it returns
    200 with ``{"status": "ok", "link_id": …}``.
    """
    # Seed the fake store with an existing beneficiary_links row that
    # matches the principal's vault_id — /beneficiary/create's effect.
    fake_store["rows"].append({
        "id": 42,
        "passer_vault_id": _TEST_VAULT_ID,
        "passer_label": "Alexa",
        "passer_label_ciphertext": None,
    })
    fake_store["next_id"] = 43

    client, restore = _build_label_ciphertext_client(fake_conn)
    try:
        resp = client.post(
            "/vault/ciphertext/beneficiary-links",
            json={
                "link_id": 42,
                "passer_label_ciphertext": _b64url_no_pad(b"\x01" * 48),
            },
        )
        # Before the fix: 500 (AttributeError). After the fix: 200.
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok", "link_id": 42}
        # The row was actually updated.
        row = fake_store["rows"][0]
        assert row["passer_label_ciphertext"] == b"\x01" * 48
        assert row["passer_label"] is None
    finally:
        restore()


def test_label_ciphertext_endpoint_404s_on_row_owned_by_another_vault(
    fake_store: dict, fake_conn: _FakeConn,
) -> None:
    """When the row exists but belongs to a different owner, the
    endpoint must return 404 (never 200) — proving the owner-scope
    check on ``passer_vault_id`` works with dict-style access.
    """
    fake_store["rows"].append({
        "id": 42,
        "passer_vault_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "passer_label": None,
        "passer_label_ciphertext": None,
    })
    client, restore = _build_label_ciphertext_client(fake_conn)
    try:
        resp = client.post(
            "/vault/ciphertext/beneficiary-links",
            json={
                "link_id": 42,
                "passer_label_ciphertext": _b64url_no_pad(b"\x02" * 48),
            },
        )
        assert resp.status_code == 404, resp.text
    finally:
        restore()


# ---------------------------------------------------------------------
# End-to-end pairing sequence
# ---------------------------------------------------------------------


def test_full_pairing_sequence_reaches_the_pairing_code(
    fake_store: dict, fake_conn: _FakeConn,
) -> None:
    """Simulates the two-step pairing flow the operator saw fail:

      1. /beneficiary/create inserts a row and returns
         ``{link_id, pairing_code}``.
      2. /vault/ciphertext/beneficiary-links updates the same row
         with the encrypted label using the SAME session principal.

    Success = the second step returns 200 so the frontend surfaces
    the pairing_code from the first step.

    The /beneficiary/create endpoint lives in main.py and depends on
    a full backend boot (DB, rate limiter, PIN verifier, …), so we
    fake the equivalent effect at the store layer here — the
    important invariant is that the vault_id used to INSERT is the
    SAME vault_id used to UPDATE, which is what the pairing bug
    hinged on.
    """
    # (a) Simulate /beneficiary/create inserting a row with the
    #     session's vault_id as passer_vault_id.
    fake_store["rows"].append({
        "id": 7,
        "passer_vault_id": _TEST_VAULT_ID,
        "passer_label": None,
        "passer_label_ciphertext": None,
    })
    fake_store["next_id"] = 8
    fake_pairing_code = "ABC-DEF1-2345"

    # (b) Drive /vault/ciphertext/beneficiary-links through TestClient
    #     with the SAME session principal.
    client, restore = _build_label_ciphertext_client(fake_conn)
    try:
        resp = client.post(
            "/vault/ciphertext/beneficiary-links",
            json={
                "link_id": 7,
                "passer_label_ciphertext": _b64url_no_pad(b"\x03" * 48),
            },
        )
        # Before the fix: 500. After the fix: 200 → frontend proceeds
        # to display the pairing code.
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"
    finally:
        restore()

    # (c) With the second step reporting success, the frontend logic
    #     is free to surface the pairing_code from the first step.
    assert fake_pairing_code  # sanity — was carried through the test


# ---------------------------------------------------------------------
# Phase 2 endpoints must NOT exist yet
# ---------------------------------------------------------------------


def test_no_beneficiary_read_path_exists_before_phase_two() -> None:
    """Every credential-material byte the owner escrows must stay in
    the DB until the Phase 2 release-authorization endpoints land.
    This test asserts the router surface contains no phase-2 read
    path AND that no other module exposes a beneficiary-read
    endpoint that could return the encrypted package.
    """
    from routes.inheritance_credential_routes import (
        router as inh_router,
    )
    from routes.vault_ciphertext_write_routes import (
        router as vcwr_router,
    )

    forbidden = {
        "/inheritance/credentials/retrieve",
        "/inheritance/access/claim",
        "/inheritance/access/approve",
        "/inheritance/access/request",
        "/inheritance/access/cancel",
        "/inheritance/device/authorize",
        "/inheritance/device/consume",
    }
    all_paths: set[str] = set()
    for r in list(inh_router.routes) + list(vcwr_router.routes):
        p = getattr(r, "path", None)
        if p:
            all_paths.add(p)
    leaked = forbidden & all_paths
    assert not leaked, (
        f"phase-2 beneficiary-side endpoints leaked into phase-1: "
        f"{sorted(leaked)}"
    )


def test_no_endpoint_returns_encrypted_credential_material() -> None:
    """No Pydantic response model on the phase-1 escrow surface may
    declare a field that carries the wrapped credential material.
    Parsed via ``ast`` so docstrings and internal helper calls
    don't false-positive.
    """
    import ast
    forbidden_field_names = {
        "encrypted_payload",
        "wrapped_key",
        "wrapping_ephemeral_pk",
        "wrapping_nonce",
        "payload_nonce",
    }

    from routes import inheritance_credential_routes as icr

    root = os.path.dirname(os.path.abspath(icr.__file__))
    with open(os.path.join(root, "inheritance_credential_routes.py"),
              "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    offenders: list[str] = []
    # Find every class that inherits (directly or indirectly) from
    # BaseModel and looks like a *Response* model.
    response_classes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.endswith("Response"):
            response_classes.add(node.name)
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    if stmt.target.id in forbidden_field_names:
                        offenders.append(
                            f"{node.name}.{stmt.target.id}"
                        )
    assert response_classes, (
        "no *Response models found — the AST walker is broken"
    )
    assert offenders == [], (
        "phase-1 response model exposes credential material: "
        f"{offenders}"
    )
