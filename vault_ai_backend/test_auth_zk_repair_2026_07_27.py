"""Secure ZK repair route tests.

The repair path is intentionally explicit: a fresh legacy-PIN session on
the current device must already exist, then the client may replace the
broken OPAQUE row. If the old beneficiary sk_vault is not recoverable,
the backend preserves encrypted packages but marks them for owner
re-encryption.
"""

from __future__ import annotations

import base64
import asyncio
from typing import Any, Optional
from unittest import mock

import pytest
from fastapi import HTTPException

from routes import auth_zk_routes as zk
from vault_handle import to_display


_VAULT_ID = "11111111-1111-1111-1111-111111111111"
_HANDLE_BYTES = bytes(range(15))
_HANDLE = to_display(_HANDLE_BYTES)


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class _Request:
    headers = {"x-device-id": "device-1"}


_PRINCIPAL = {
    "vault_id": _VAULT_ID,
    "vault_name": "beneficiary",
    "token_id": "token-id",
    "device_id": "device-1",
}


class _Cursor:
    def __init__(self, rows: list[Optional[dict[str, Any]]]) -> None:
        self.rows = list(rows)
        self.sql: list[str] = []
        self.params: list[tuple[Any, ...] | None] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.sql.append(" ".join(sql.split()))
        self.params.append(params)

    def fetchone(self) -> Optional[dict[str, Any]]:
        if not self.rows:
            return None
        return self.rows.pop(0)


class _Conn:
    def __init__(self, rows: list[Optional[dict[str, Any]]]) -> None:
        self.cursor_obj = _Cursor(rows)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, cursor_factory: Any = None) -> _Cursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _payload(*, branch: str, pk: bytes = b"\x09" * 32) -> zk.ZkRepairFinalizeRequest:
    return zk.ZkRepairFinalizeRequest(
        vault_handle=_HANDLE,
        ke3=_b64u(b"registration-upload"),
        wrapped_mvk=_b64u(b"\x01wrapped-mvk"),
        wrapped_sk_vault=_b64u(b"\x01wrapped-sk"),
        pk_vault_public=_b64u(pk),
        display_name_ciphertext=_b64u(b"\x01display-name"),
        repair_branch=branch,
    )


def test_repair_init_is_vault_scoped_and_uses_stored_handle_identifier() -> None:
    conn = _Conn([{"vault_handle": _HANDLE_BYTES}])
    with mock.patch("routes.auth_zk_routes.get_db", return_value=conn), \
            mock.patch("routes.auth_zk_routes._require_recent_repair_session"), \
            mock.patch(
                "routes.auth_zk_routes.opaque_registration_start",
                return_value=b"ke2",
            ) as start:
        response = asyncio.run(
            zk.zk_repair_init(
                zk.ZkRepairInitRequest(vault_handle=_HANDLE, ke1=_b64u(b"ke1")),
                _Request(),
                _PRINCIPAL,
            )
        )

    assert response.ke2 == _b64u(b"ke2")
    assert conn.cursor_obj.params[0] == (_VAULT_ID,)
    assert start.call_args.args[1] == zk._opaque_credential_id(_HANDLE_BYTES)


def test_preserve_repair_rewrites_opaque_without_rotating_public_key() -> None:
    conn = _Conn([
        {"vault_id": _VAULT_ID, "vault_handle": _HANDLE_BYTES,
         "pk_vault_public": b"\x07" * 32},
    ])
    with mock.patch("routes.auth_zk_routes.get_db", return_value=conn), \
            mock.patch("routes.auth_zk_routes._require_recent_repair_session"), \
            mock.patch(
                "routes.auth_zk_routes.opaque_registration_finish",
                return_value=b"modern-record",
            ):
        response = asyncio.run(
            zk.zk_repair_finalize(
                _payload(branch=zk.ZK_REPAIR_BRANCH_PRESERVE, pk=b"\x07" * 32),
                _Request(),
                _PRINCIPAL,
            )
        )

    assert response.repaired is True
    assert response.branch == zk.ZK_REPAIR_BRANCH_PRESERVE
    assert response.pk_rotated is False
    assert response.requires_owner_reencryption is False
    assert response.reencryption_required_count == 0
    assert conn.commits == 1
    sql = "\n".join(conn.cursor_obj.sql)
    assert "needs_reencryption" not in sql


def test_rotate_repair_marks_existing_packages_for_owner_reencryption() -> None:
    conn = _Conn([
        {"vault_id": _VAULT_ID, "vault_handle": _HANDLE_BYTES,
         "pk_vault_public": b"\x07" * 32},
        {"c": 2},
    ])
    with mock.patch("routes.auth_zk_routes.get_db", return_value=conn), \
            mock.patch("routes.auth_zk_routes._require_recent_repair_session"), \
            mock.patch(
                "routes.auth_zk_routes.opaque_registration_finish",
                return_value=b"modern-record",
            ):
        response = asyncio.run(
            zk.zk_repair_finalize(
                _payload(branch=zk.ZK_REPAIR_BRANCH_ROTATE, pk=b"\x08" * 32),
                _Request(),
                _PRINCIPAL,
            )
        )

    assert response.branch == zk.ZK_REPAIR_BRANCH_ROTATE
    assert response.pk_rotated is True
    assert response.requires_owner_reencryption is True
    assert response.reencryption_required_count == 2
    sql = "\n".join(conn.cursor_obj.sql)
    assert "needs_reencryption" in sql
    assert "UPDATE inheritance_credentials" in sql
    assert "UPDATE inheritance_device_authorizations" in sql
    assert conn.commits == 1


def test_preserve_repair_rejects_public_key_mismatch() -> None:
    conn = _Conn([
        {"vault_id": _VAULT_ID, "vault_handle": _HANDLE_BYTES,
         "pk_vault_public": b"\x07" * 32},
    ])
    with mock.patch("routes.auth_zk_routes.get_db", return_value=conn), \
            mock.patch("routes.auth_zk_routes._require_recent_repair_session"), \
            mock.patch(
                "routes.auth_zk_routes.opaque_registration_finish",
                return_value=b"modern-record",
            ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                zk.zk_repair_finalize(
                    _payload(
                        branch=zk.ZK_REPAIR_BRANCH_PRESERVE,
                        pk=b"\x08" * 32,
                    ),
                    _Request(),
                    _PRINCIPAL,
                )
            )

    assert exc.value.status_code == 409
    assert conn.rollbacks == 1


def test_repair_finalize_rejects_wrong_vault_handle() -> None:
    conn = _Conn([
        {"vault_id": _VAULT_ID, "vault_handle": b"\x01" * 15,
         "pk_vault_public": b"\x07" * 32},
    ])
    with mock.patch("routes.auth_zk_routes.get_db", return_value=conn), \
            mock.patch("routes.auth_zk_routes._require_recent_repair_session"), \
            mock.patch(
                "routes.auth_zk_routes.opaque_registration_finish",
                return_value=b"modern-record",
            ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                zk.zk_repair_finalize(
                    _payload(branch=zk.ZK_REPAIR_BRANCH_ROTATE),
                    _Request(),
                    _PRINCIPAL,
                )
            )

    assert exc.value.status_code == 403
    assert conn.rollbacks == 1


def test_malformed_repair_payload_is_rejected_before_state_update() -> None:
    with mock.patch("routes.auth_zk_routes._require_recent_repair_session"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                zk.zk_repair_finalize(
                    zk.ZkRepairFinalizeRequest(
                        vault_handle=_HANDLE,
                        ke3=_b64u(b"registration-upload"),
                        wrapped_mvk=_b64u(b"\x01wrapped-mvk"),
                        wrapped_sk_vault=_b64u(b"\x01wrapped-sk"),
                        pk_vault_public=_b64u(b"too-short"),
                        display_name_ciphertext=_b64u(b"\x01display-name"),
                        repair_branch=zk.ZK_REPAIR_BRANCH_ROTATE,
                    ),
                    _Request(),
                    _PRINCIPAL,
                )
            )

    assert exc.value.status_code == 400
