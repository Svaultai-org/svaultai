"""Released V2 export scope tests with synthetic ciphertext only."""

import base64
from unittest import mock

import pytest
from fastapi import HTTPException

from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER
from routes import inheritance_v2_export_routes as export


BENEFICIARY = {"vault_id": "synthetic-beneficiary"}


class FakeDb:
    def __init__(self):
        self.link = {
            "passer_vault_id": "synthetic-owner",
            "wrapped_vault_key": ZK_BENEFICIARY_V2_MARKER,
            "pairing_state": "released",
            "crypto_version": 2,
        }
        self.legacy_item = None
        self.items = [{"id": 4, "item_type_ciphertext": b"type-ct",
                       "service_ciphertext": b"service-ct",
                       "payload_ciphertext": b"payload-ct"}]
        self.queries = []

    def cursor(self, **_kwargs):
        return FakeCursor(self)

    def close(self):
        pass


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.value = None

    def execute(self, sql, params):
        normalized = " ".join(sql.split()).upper()
        self.db.queries.append((normalized, params))
        if "FROM BENEFICIARY_LINKS" in normalized:
            self.value = self.db.link if params == (17, BENEFICIARY["vault_id"]) else None
        elif "SELECT 1 FROM VAULT_ITEMS" in normalized:
            self.value = self.db.legacy_item
        elif "COUNT(*) AS ITEM_COUNT" in normalized:
            self.value = {
                "item_count": len(self.db.items),
                "ciphertext_bytes": sum(
                    len(bytes(row[field])) for row in self.db.items
                    for field in ("item_type_ciphertext", "service_ciphertext",
                                  "payload_ciphertext")
                ),
            }
        elif "SELECT ID, ITEM_TYPE_CIPHERTEXT" in normalized:
            self.value = self.db.items
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.value

    def fetchall(self):
        return self.value


def test_export_off_by_default_and_released_beneficiary_only(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(export, "get_db", lambda: db)
    limit = mock.Mock()
    monkeypatch.setattr(export, "enforce_export_rate_limit", limit)
    monkeypatch.delenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", raising=False)
    with pytest.raises(HTTPException) as disabled:
        export.export_released_vault_items(17, BENEFICIARY)
    assert disabled.value.status_code == 404
    assert db.queries == []

    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    with pytest.raises(HTTPException) as unauthorized:
        export.export_released_vault_items(17, {"vault_id": "other"})
    assert unauthorized.value.status_code == 404
    db.link["pairing_state"] = "approved"
    with pytest.raises(HTTPException) as not_retrieved:
        export.export_released_vault_items(17, BENEFICIARY)
    assert not_retrieved.value.status_code == 404
    limit.assert_not_called()


def test_export_returns_only_opaque_items_after_release(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(export, "get_db", lambda: db)
    limit = mock.Mock()
    monkeypatch.setattr(export, "enforce_export_rate_limit", limit)
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    result = export.export_released_vault_items(17, BENEFICIARY)
    assert result == {
        "owner_vault_id": "synthetic-owner",
        "beneficiary_link_id": 17,
        "items": [{
            "item_id": 4,
            "item_type_ciphertext": base64.urlsafe_b64encode(b"type-ct").rstrip(b"=").decode(),
            "service_ciphertext": base64.urlsafe_b64encode(b"service-ct").rstrip(b"=").decode(),
            "payload_ciphertext": base64.urlsafe_b64encode(b"payload-ct").rstrip(b"=").decode(),
        }],
    }
    assert "BENEFICIARY_VAULT_ID = %S" in db.queries[0][0]
    assert db.queries[-1][1] == ("synthetic-owner", 501)
    limit.assert_called_once_with(vault_id=BENEFICIARY["vault_id"])


def test_export_refuses_unmigrated_or_over_limit_items(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(export, "get_db", lambda: db)
    monkeypatch.setattr(export, "enforce_export_rate_limit", mock.Mock())
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    db.legacy_item = {"?column?": 1}
    with pytest.raises(HTTPException) as legacy:
        export.export_released_vault_items(17, BENEFICIARY)
    assert legacy.value.status_code == 409
    db.legacy_item = None
    db.items = db.items * 501
    with pytest.raises(HTTPException) as too_many:
        export.export_released_vault_items(17, BENEFICIARY)
    assert too_many.value.status_code == 409
    db.items = [{"id": 1, "item_type_ciphertext": b"a",
                 "service_ciphertext": b"b",
                 "payload_ciphertext": b"x" * (4 * 1024 * 1024 + 1)}]
    with pytest.raises(HTTPException) as too_large:
        export.export_released_vault_items(17, BENEFICIARY)
    assert too_large.value.status_code == 409


def test_export_rate_limit_stops_before_content_read(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(export, "get_db", lambda: db)
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    monkeypatch.setattr(
        export, "enforce_export_rate_limit",
        mock.Mock(side_effect=HTTPException(status_code=429, detail="rate_limited")),
    )
    with pytest.raises(HTTPException) as limited:
        export.export_released_vault_items(17, BENEFICIARY)
    assert limited.value.status_code == 429
    assert len(db.queries) == 1
