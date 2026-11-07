"""Receive responses identify the exact V2 backup without exposing secrets."""

import json

import pytest

from routes import crypto_wallet_routes as route


@pytest.mark.parametrize(
    "asset,receive",
    [
        ("ETH", lambda principal: route.get_wallet_receive("ETH", principal)),
        ("USDT_ERC20", lambda principal: route.get_wallet_receive("USDT_ERC20", principal)),
        ("ETH", lambda principal: route._mainnet_receive("ETH", principal)),
        ("USDT_ERC20", lambda principal: route._mainnet_receive("USDT_ERC20", principal)),
        ("SOL", lambda principal: route._solana_receive("SOL", principal)),
        ("USDT_TRC20", lambda principal: route._tron_receive("USDT_TRC20", principal)),
        ("XMR", lambda principal: route._xmr_receive("XMR", principal)),
    ],
)
def test_verified_wallet_receive_binds_address_to_v2_backup(
    monkeypatch, asset, receive,
):
    import evm_networks
    import vault_config
    import verified_assets

    record = {
        "asset": asset,
        "network": "synthetic_network",
        "walletLabel": "Synthetic wallet",
        "publicAddress": "synthetic-public-address",
        "walletRecordId": "synthetic-wallet-record-123",
        "backupStatus": "wallet_v2_encrypted",
        "encryptedWalletSecret": "synthetic-secret-must-not-leak",
    }
    monkeypatch.setattr(route, "crypto_wallet_engine_enabled", lambda: True)
    monkeypatch.setattr(route, "asset_is_wallet_engine_supported", lambda _: True)
    monkeypatch.setattr(route, "_is_slice2_live_asset", lambda _: True)
    monkeypatch.setattr(route, "_mainnet_asset_gate", lambda *_: None)
    monkeypatch.setattr(route, "_load_wallet_account_record", lambda *_: record)
    monkeypatch.setattr(route, "_load_wallet_account_record_network", lambda *_: record)
    monkeypatch.setattr(evm_networks, "is_receive_enabled", lambda _: True)
    monkeypatch.setattr(vault_config, "solana_enabled", lambda: True)
    monkeypatch.setattr(vault_config, "tron_enabled", lambda: True)
    monkeypatch.setattr(vault_config, "monero_enabled", lambda: True)
    monkeypatch.setattr(vault_config, "ethereum_mainnet_erc20_receive_enabled", lambda: True)
    monkeypatch.setattr(verified_assets, "kag_address_gate", lambda *_args, **_kwargs: None)

    response = receive({"vault_id": "synthetic-vault"})
    assert response["wallet_engine"] == "receive_ready"
    assert response["publicAddress"] == record["publicAddress"]
    assert response["walletRecordId"] == record["walletRecordId"]
    assert response["backupStatus"] == "wallet_v2_encrypted"
    assert "synthetic-secret-must-not-leak" not in json.dumps(response)


def test_legacy_receive_is_not_mislabeled_as_v2(monkeypatch):
    import vault_config

    monkeypatch.setattr(vault_config, "solana_enabled", lambda: True)
    monkeypatch.setattr(route, "_load_wallet_account_record_network", lambda *_: {
        "publicAddress": "synthetic-legacy-address",
        "walletLabel": "Synthetic old wallet",
        "backupStatus": "encrypted_backup_saved",
    })
    response = route._solana_receive("SOL", {"vault_id": "synthetic-vault"})
    assert response["wallet_engine"] == "receive_ready"
    assert response["publicAddress"] == "synthetic-legacy-address"
    assert "walletRecordId" not in response
    assert "backupStatus" not in response
