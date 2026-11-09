"""Older signing clients must not mistake a private wallet for an empty one."""

import pytest

from routes import crypto_wallet_routes as route


VAULT = "synthetic-vault"
RECORD = {
    "schema": "crypto_wallet_account_v2",
    "asset": "ETH",
    "network": "ethereum_mainnet",
    "publicAddress": "0x0000000000000000000000000000000000000001",
    "walletRecordId": "synthetic-wallet-record",
    "backupStatus": "wallet_v2_encrypted",
    "migrationState": "v2_verified",
}


def _assert_update_required(response, asset):
    assert response["status"] == "client_update_required"
    assert response["wallet_engine"] == "client_update_required"
    assert response["asset"] == asset
    assert "Update SVaultAI" in response["message"]
    assert "publicAddress" not in response
    assert "encryptedWalletSecret" not in response


@pytest.mark.parametrize("asset", ["ETH", "USDT_ERC20", "USDC_ERC20"])
def test_old_sepolia_secret_route_identifies_v2_parent_wallet(
    monkeypatch, asset,
):
    seen = []
    monkeypatch.setattr(route, "crypto_wallet_engine_enabled", lambda: True)
    monkeypatch.setattr(route, "asset_is_wallet_engine_supported", lambda _: True)
    monkeypatch.setattr(route, "_is_slice2_live_asset", lambda _: True)
    monkeypatch.setattr(
        route, "_load_wallet_account_record",
        lambda vault, account: seen.append((vault, account)) or dict(RECORD),
    )

    response = route.get_encrypted_wallet_secret(asset, {"vault_id": VAULT})

    _assert_update_required(response, asset)
    assert seen == [(VAULT, "ETH")]


@pytest.mark.parametrize("asset", ["ETH", "USDT_ERC20", "USDC_ERC20"])
def test_old_mainnet_secret_route_identifies_v2_network_slot(
    monkeypatch, asset,
):
    import evm_networks
    import vault_config

    seen = []
    monkeypatch.setattr(route, "crypto_wallet_engine_enabled", lambda: True)
    monkeypatch.setattr(
        route, "_resolve_network_for_route",
        lambda _: (evm_networks.NETWORK_ETHEREUM_MAINNET, None),
    )
    monkeypatch.setattr(route, "_mainnet_asset_gate", lambda *_: None)
    monkeypatch.setattr(evm_networks, "is_receive_enabled", lambda _: True)
    monkeypatch.setattr(
        vault_config, "ethereum_mainnet_erc20_receive_enabled", lambda: True,
    )
    monkeypatch.setattr(
        route, "_load_wallet_account_record_network",
        lambda vault, account, network: (
            seen.append((vault, account, network)) or dict(RECORD)
        ),
    )

    response = route.get_encrypted_wallet_secret_network(
        "ethereum_mainnet", asset, {"vault_id": VAULT},
    )

    _assert_update_required(response, asset)
    assert response["network"] == "Ethereum Mainnet"
    assert seen == [(VAULT, "ETH", evm_networks.NETWORK_ETHEREUM_MAINNET)]


@pytest.mark.parametrize(
    "asset,network,enabled,send_enabled",
    [
        ("SOL", "solana_mainnet",
         "solana_enabled", "solana_send_enabled"),
        ("USDT_TRC20", "tron_mainnet",
         "tron_enabled", "tron_send_enabled"),
    ],
)
def test_old_chain_secret_route_requires_update_for_v2_slot(
    monkeypatch, asset, network, enabled, send_enabled,
):
    import vault_config

    seen = []
    monkeypatch.setattr(vault_config, enabled, lambda: True)
    monkeypatch.setattr(vault_config, send_enabled, lambda: True)
    monkeypatch.setattr(
        route, "_resolve_network_for_route", lambda _: (network, None),
    )
    monkeypatch.setattr(
        route, "_load_wallet_account_record_network",
        lambda vault, account, requested_network: (
            seen.append((vault, account, requested_network)) or {
                **RECORD, "asset": asset, "network": network,
            }
        ),
    )

    response = route.get_encrypted_wallet_secret_network(
        network, asset, {"vault_id": VAULT},
    )

    _assert_update_required(response, asset)
    assert response["network"] == network
    assert seen == [(VAULT, asset, network)]
    assert "Recreate" not in response["message"]


def test_old_secret_route_keeps_legacy_ciphertext_available(monkeypatch):
    monkeypatch.setattr(route, "crypto_wallet_engine_enabled", lambda: True)
    monkeypatch.setattr(route, "asset_is_wallet_engine_supported", lambda _: True)
    monkeypatch.setattr(route, "_is_slice2_live_asset", lambda _: True)
    monkeypatch.setattr(route, "_load_wallet_account_record", lambda *_: {
        "schema": "crypto_wallet_account_v1",
        "backupStatus": "encrypted_backup_saved",
        "encryptedWalletSecret": "synthetic-legacy-ciphertext",
    })

    response = route.get_encrypted_wallet_secret("ETH", {"vault_id": VAULT})

    assert response == {
        "status": "encrypted_secret_ready",
        "asset": "ETH",
        "encryptedWalletSecret": "synthetic-legacy-ciphertext",
    }
