"""Synthetic flag-matrix checks for ZK signup and legacy adoption cutover."""

from __future__ import annotations

import os
from unittest import mock

import pytest
from fastapi import HTTPException

from test_zk_pin_initialization_2026_07_19 import (
    _base_payload, _b64url_no_pad, _run_register,
)


@pytest.mark.parametrize(
    "raw_pin_disabled,verifier_free,supplies_verifier,status,stored_verifier",
    [
        (False, False, True, 200, "supplied"),
        (False, False, False, 503, None),
        (True, False, True, 503, None),
        (True, False, False, 503, None),
        (False, True, True, 409, None),
        (False, True, False, 200, ""),
        (True, True, True, 409, None),
        (True, True, False, 200, ""),
    ],
)
def test_zk_signup_flag_matrix(
    raw_pin_disabled, verifier_free, supplies_verifier, status, stored_verifier,
):
    payload = _base_payload()
    if not supplies_verifier:
        payload.pop("pin_verifier")
    response, conn = _run_register(
        payload, verifier_free=verifier_free,
        raw_pin_disabled=raw_pin_disabled,
    )
    assert response.status_code == status, response.text
    inserts = [
        params for cur in conn.cursors for sql, params in cur.calls
        if "INSERT INTO vaults" in sql
    ]
    if stored_verifier is None:
        assert inserts == []
        assert "123456" not in response.text
    else:
        assert len(inserts) == 1
        assert inserts[0][2] == (
            payload["pin_verifier"] if stored_verifier == "supplied" else ""
        )


@pytest.mark.parametrize(
    "raw_pin_disabled,verifier_free,blocked",
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_adoption_never_preserves_legacy_verifier_under_cutover(
    raw_pin_disabled, verifier_free, blocked,
):
    from routes import auth_zk_routes as zk

    base = _base_payload()
    payload = zk.ZkAdoptRequest(
        vault_handle=base["vault_handle"],
        opaque_registration_record=_b64url_no_pad(b"synthetic-record"),
        wrapped_mvk=base["wrapped_mvk"],
        wrapped_sk_vault=base["wrapped_sk_vault"],
        pk_vault_public=base["pk_vault_public"],
        display_name_ciphertext=base["display_name_ciphertext"],
    )
    with (
        mock.patch.dict(os.environ, {
            "VAULTAI_ZK_RAW_PIN_CONTENT_DISABLED":
                "true" if raw_pin_disabled else "false",
            "VAULTAI_ZK_VERIFIER_FREE_REGISTRATION_ENABLED":
                "true" if verifier_free else "false",
        }),
        mock.patch.object(zk, "get_db", side_effect=RuntimeError("synthetic DB"))
        as get_db,
    ):
        if blocked:
            with pytest.raises(HTTPException) as caught:
                zk._zk_adopt_sync(payload, {"vault_id": "synthetic-vault"})
            assert caught.value.status_code == 409
            assert caught.value.detail["code"] == "private_adoption_requires_migration"
            get_db.assert_not_called()
        else:
            # With both cutover flags off, legacy adoption still reaches the
            # existing storage path. No real database is opened in this test.
            with pytest.raises(RuntimeError, match="synthetic DB"):
                zk._zk_adopt_sync(payload, {"vault_id": "synthetic-vault"})
            get_db.assert_called_once()
