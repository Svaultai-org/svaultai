"""A verified V2 wallet remains visible to the older receive routes."""

import json

import pytest

from routes import crypto_wallet_routes as route


VAULT = "synthetic-vault"


class _Cursor:
    def __init__(self, legacy, v2_rows):
        self.legacy = legacy
        self.v2_rows = v2_rows
        self.one = None
        self.many = []
        self.lookups = []

    def execute(self, sql, params):
        self.lookups.append(params)
        assert params[0] == VAULT
        if "FROM vault_items" in sql:
            self.one = (
                {"encrypted_data": json.dumps(self.legacy)}
                if self.legacy is not None else None
            )
            self.many = []
        elif "FROM wallet_v2_records" in sql:
            self.one = None
            self.many = list(self.v2_rows)
        else:
            raise AssertionError("Unexpected wallet lookup")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class _Db:
    def __init__(self, cursor):
        self.cur = cursor

    def cursor(self, **_):
        return self.cur

    def close(self):
        pass


@pytest.fixture
def receive_enabled(monkeypatch):
    import evm_networks
    import vault_config
    import verified_assets

    monkeypatch.setenv("WALLET_V2_READ_ENABLED", "true")
    monkeypatch.setattr(route, "crypto_wallet_engine_enabled", lambda: True)
    monkeypatch.setattr(route, "asset_is_wallet_engine_supported", lambda _: True)
    monkeypatch.setattr(route, "_is_slice2_live_asset", lambda _: True)
    monkeypatch.setattr(route, "_mainnet_asset_gate", lambda *_: None)
    monkeypatch.setattr(evm_networks, "is_receive_enabled", lambda _: True)
    monkeypatch.setattr(vault_config, "solana_enabled", lambda: True)
    monkeypatch.setattr(vault_config, "tron_enabled", lambda: True)
    monkeypatch.setattr(vault_config, "monero_enabled", lambda: True)
    monkeypatch.setattr(
        vault_config, "ethereum_mainnet_erc20_receive_enabled", lambda: True,
    )
    monkeypatch.setattr(
        verified_assets, "kag_address_gate", lambda *_args, **_kwargs: None,
    )


@pytest.mark.parametrize(
    "asset,network,receive",
    [
        ("ETH", "ethereum_sepolia", route.get_wallet_receive),
        ("USDT_ERC20", "ethereum_sepolia", route.get_wallet_receive),
        ("USDC_ERC20", "ethereum_sepolia", route.get_wallet_receive),
        ("ETH", "ethereum_mainnet", route._mainnet_receive),
        ("USDT_ERC20", "ethereum_mainnet", route._mainnet_receive),
        ("USDC_ERC20", "ethereum_mainnet", route._mainnet_receive),
        ("SOL", "solana_mainnet", route._solana_receive),
        ("USDT_TRC20", "tron_mainnet", route._tron_receive),
        ("XMR", "monero_mainnet", route._xmr_receive),
    ],
)
def test_published_v2_slot_keeps_its_address_and_never_offers_creation(
    monkeypatch, receive_enabled, asset, network, receive,
):
    account = "ETH" if asset in {"USDT_ERC20", "USDC_ERC20"} else asset
    address = f"synthetic-{network}-address"
    cursor = _Cursor(None, [
        {
            "wallet_record_id": "wrong-network-record",
            "chain": "evm",
            "network": "wrong_network",
            "asset": account,
            "public_address": "wrong-network-address",
            "wallet_label": "Wrong network",
            "migration_state": "v2_verified",
        },
        {
            "wallet_record_id": "correct-network-record",
            "chain": "evm",
            "network": network,
            "asset": account,
            "public_address": address,
            "wallet_label": "Private wallet",
            "migration_state": "v2_verified",
        },
    ])
    monkeypatch.setattr(route, "get_db", lambda: _Db(cursor))

    response = receive(asset, {"vault_id": VAULT})

    assert response["wallet_engine"] == "receive_ready"
    assert response["publicAddress"] == address
    assert response["backupStatus"] == "wallet_v2_encrypted"
    assert response["walletRecordId"] == "correct-network-record"
    assert "encryptedWalletSecret" not in response
    assert cursor.lookups == [
        (VAULT, "crypto_wallet_account", (
            account if network == "ethereum_sepolia"
            else f"{account}:{network}"
        )),
        (VAULT, account),
    ]


def test_existing_legacy_receive_keeps_its_address_without_v2_fallback(
    monkeypatch, receive_enabled,
):
    legacy = {
        "schema": "crypto_wallet_account_v1",
        "asset": "ETH",
        "network": "Ethereum Sepolia",
        "walletLabel": "Older wallet",
        "publicAddress": "synthetic-older-address",
        "backupStatus": "encrypted_backup_saved",
    }
    cursor = _Cursor(legacy, [{
        "wallet_record_id": "unrelated-v2-record",
        "network": "ethereum_sepolia",
        "asset": "ETH",
        "public_address": "must-not-use",
        "wallet_label": "Unrelated",
        "migration_state": "v2_verified",
    }])
    monkeypatch.setattr(route, "get_db", lambda: _Db(cursor))

    response = route.get_wallet_receive("ETH", {"vault_id": VAULT})

    assert response["wallet_engine"] == "receive_ready"
    assert response["publicAddress"] == "synthetic-older-address"
    assert "walletRecordId" not in response
    assert cursor.lookups == [(VAULT, "crypto_wallet_account", "ETH")]
