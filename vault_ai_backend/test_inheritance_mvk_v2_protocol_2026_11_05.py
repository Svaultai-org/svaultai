"""V2 escrow envelope stays separated from legacy PIN escrow."""

import pytest
from fastapi import HTTPException
from unittest import mock

from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER
from routes.inheritance_credential_routes import (
    _require_credential_protocol, _require_v2_escrow_proof,
)
from routes import auth_zk_routes


def test_legacy_link_accepts_only_v1(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    link = {"wrapped_vault_key": "legacy-encrypted-key"}
    _require_credential_protocol(link, 1)
    with pytest.raises(HTTPException) as denied:
        _require_credential_protocol(link, 2)
    assert denied.value.status_code == 409


def test_v2_link_rejects_v1_pin_package_and_is_default_off(monkeypatch):
    link = {"wrapped_vault_key": ZK_BENEFICIARY_V2_MARKER}
    monkeypatch.delenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", raising=False)
    with pytest.raises(HTTPException) as disabled:
        _require_credential_protocol(link, 2)
    assert disabled.value.detail == "zk_inheritance_v2_disabled"
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    with pytest.raises(HTTPException) as old_package:
        _require_credential_protocol(link, 1)
    assert old_package.value.detail == "zk_mvk_package_required"
    _require_credential_protocol(link, 2)


def test_v2_escrow_requires_fresh_one_time_proof(monkeypatch):
    principal = {"vault_id": "synthetic-owner", "token_id": "synthetic-session"}
    link = {"wrapped_vault_key": ZK_BENEFICIARY_V2_MARKER}
    consume = mock.Mock()
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", consume)
    with pytest.raises(HTTPException) as missing:
        _require_v2_escrow_proof(link, None, principal)
    assert missing.value.status_code == 400
    _require_v2_escrow_proof(link, "synthetic-proof", principal)
    consume.assert_called_once_with("synthetic-proof", principal)
