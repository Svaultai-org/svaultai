from __future__ import annotations

import asyncio
import base64
from typing import Any


_VAULT_ID = "11111111-1111-1111-1111-111111111111"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.params: tuple[Any, ...] | None = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.params = params

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Conn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.cursor_obj = _Cursor(rows)
        self.closed = False

    def cursor(self, cursor_factory: Any = None) -> _Cursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def test_owner_list_returns_label_ciphertext_for_zk_rows(monkeypatch) -> None:
    import main

    label_ciphertext = b"\x01" + b"\x02" * 44
    conn = _Conn([
        {
            "id": 7,
            "passer_label": None,
            "passer_label_ciphertext": label_ciphertext,
            "status": "linked",
            "is_linked": True,
            "pairing_expires_at": None,
            "transfer_requested_at": None,
            "transfer_executes_at": None,
            "created_at": None,
            "pairing_state": "credentials_saved",
            "access_requested_at": None,
            "cooldown_ends_at": None,
            "decision_at": None,
            "credentials_saved": True,
            "credential_crypto_version": 1,
            "credential_updated_at": None,
        },
    ])
    monkeypatch.setattr(main, "get_db", lambda: conn)
    monkeypatch.setattr(main, "verify_vault_pin", lambda vault_id, pin: b"key")

    handler = getattr(
        main.beneficiary_list_mine_endpoint,
        "__wrapped__",
        main.beneficiary_list_mine_endpoint,
    )
    result = asyncio.run(
        handler(
            request=None,
            payload=main.BeneficiaryListRequest(
                vault_name="Owner Vault",
                pin="123456",
            ),
            principal={
                "vault_id": _VAULT_ID,
                "vault_name": "Owner Vault",
                "token_id": "token",
                "device_id": "device",
            },
        )
    )

    row = result["beneficiaries"][0]
    assert row["label"] is None
    assert row["passer_label_ciphertext"] == _b64url(label_ciphertext)
    assert conn.cursor_obj.params == (_VAULT_ID,)
    assert conn.closed is True
