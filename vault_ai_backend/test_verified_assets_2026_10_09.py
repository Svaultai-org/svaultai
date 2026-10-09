"""Closed PAX Gold integration and real route safety, without external I/O.

The RPC/indexer replies and the wallet/control store are in-process fixtures.
No account is created, no production database is contacted, and no transaction
is sent to any network. Broadcast tests use a deterministic test-only key and
exercise signature binding plus a simulated RPC response, not real funds.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import evm_rpc
import evm_transaction_history
import vault_config
import verified_assets
from _test_fake_mainnet_store import FakeMainnetStore, make_signed_tx_and_matching_draft
from crypto_entitlement import require_crypto_entitlement
from device_gate import verify_trusted_device
from routes import crypto_wallet_routes as wallet_routes


ASSET = "PAXG_ERC20"
NETWORK = "ethereum_mainnet"
CONTRACT = "0x45804880De22913dAFE09f4980848ECE6EcbAf78"
RPC = "https://rpc.example.invalid/mainnet"
FROM = "0x" + "ab" * 20
DEST = "0x" + "cd" * 20
VAULT = "verified-assets-test-only"
ROOT_PATH = f"/crypto/wallet/network/{NETWORK}/{ASSET}"
GAS_PRICE = 30_000_000_000
GAS_LIMIT = 73_421
FEE = GAS_PRICE * GAS_LIMIT


def _forbid_external_io(*_args, **_kwargs):
    raise AssertionError("Verified-assets tests must not access external network or database")


def _fixed_units(value: int, decimals: int = 18) -> str:
    """Independent integer-only expectation; never uses ambient Decimal precision."""
    digits = str(value).rjust(decimals + 1, "0")
    fraction = digits[-decimals:].rstrip("0")
    return digits[:-decimals] + ("." + fraction if fraction else "")


@pytest.fixture
def enabled(monkeypatch):
    flags = {
        "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED": "true",
        "VAULTAI_ASSETS_PAXG_ENABLED": "true",
        "VAULTAI_ASSETS_KAG_ENABLED": "false",
        "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED": "true",
        "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED": "true",
        "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED": "true",
        "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED": "false",
        "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE": "/does-not-exist/verified-assets-test.flag",
        "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT": "1000",
        "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS": "60",
        "ETHEREUM_MAINNET_RPC_URL": RPC,
        "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER": "etherscan",
        "ETHEREUM_MAINNET_TX_INDEXER_API_KEY": "test-indexer-key-not-a-credential",
        "ETHEREUM_MAINNET_TX_INDEXER_BASE_URL": "https://indexer.example.invalid/api",
    }
    for name, value in flags.items():
        monkeypatch.setenv(name, value)
    vault_config.reset_for_tests()
    verified_assets.reset_verification_cache()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _forbid_external_io)
    monkeypatch.setattr(wallet_routes, "get_db", _forbid_external_io)

    chain = Mock(return_value=1)
    probe = Mock(side_effect=lambda _url, method, _params: {
        "result": "0x60016000" if method == "eth_getCode" else "0x" + format(18, "064x")
    })
    monkeypatch.setattr(evm_rpc, "eth_chain_id_at_url", chain)
    monkeypatch.setattr(evm_rpc, "_emit_rpc_at_url", probe)
    fake = FakeMainnetStore()
    monkeypatch.setattr(wallet_routes, "_mainnet_store", fake)
    monkeypatch.setattr(vault_config, "_db_pause_override", fake.is_mainnet_send_paused, raising=False)
    wallet_routes.reset_mainnet_safety_state_for_tests()
    yield SimpleNamespace(chain=chain, probe=probe, store=fake)
    verified_assets.reset_verification_cache()
    vault_config.reset_for_tests()
    wallet_routes.reset_mainnet_safety_state_for_tests()


@pytest.fixture
def routes(enabled, monkeypatch):
    app = FastAPI()
    app.include_router(wallet_routes.router)
    principal = lambda: {"vault_id": VAULT}
    app.dependency_overrides[verify_trusted_device] = principal
    app.dependency_overrides[require_crypto_entitlement] = principal
    record = {
        "schema": "crypto_wallet_account_v1", "asset": "ETH",
        "network": NETWORK, "walletLabel": "Test-only Ethereum wallet",
        "publicAddress": FROM, "encryptedWalletSecret": "test-only-ciphertext",
        "keyOrigin": "generated_client_side", "signingMode": "client_side",
        "backupStatus": "encrypted_backup_saved",
    }
    loader = Mock(side_effect=lambda vault, service: record if vault == VAULT and service == f"ETH:{NETWORK}" else None)
    monkeypatch.setattr(wallet_routes, "_load_wallet_account_record", loader)
    rpc = {
        "eth_block_number_at_url": Mock(return_value=19_000_001),
        "eth_get_transaction_count_at_url": Mock(return_value=7),
        "eth_gas_price_wei_at_url": Mock(return_value=GAS_PRICE),
        "eth_estimate_gas_at_url": Mock(return_value=GAS_LIMIT),
        "eth_get_balance_wei_at_url": Mock(return_value=FEE + 1),
        "erc20_balance_of_at_url": Mock(return_value=10 * 10**18),
        "eth_send_raw_transaction_at_url": Mock(side_effect=_forbid_external_io),
        "eth_get_transaction_by_hash_at_url": Mock(side_effect=_forbid_external_io),
        "eth_get_transaction_receipt_at_url": Mock(side_effect=_forbid_external_io),
    }
    for name, function in rpc.items():
        monkeypatch.setattr(evm_rpc, name, function)
    indexer = Mock(side_effect=_forbid_external_io)
    monkeypatch.setattr(evm_transaction_history, "_http_get", indexer)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, record=record, loader=loader, rpc=rpc, indexer=indexer, state=enabled)


def _draft(routes, amount="1.234567890123456789", **overrides):
    payload = {"fromAddress": FROM, "destinationAddress": DEST, "amountEth": amount}
    payload.update(overrides)
    return routes.client.post(ROOT_PATH + "/send/draft", json=payload)


def _catalog(routes):
    response = routes.client.get("/crypto/wallet/asset-catalog")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("name,value", [
    ("VAULTAI_ASSETS_PAXG_ENABLED", "false"),
    ("VAULTAI_ASSETS_PAXG_ENABLED", "not-a-boolean"),
    ("VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED", "false"),
])
def test_registry_disabled_before_any_provider_call(enabled, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    vault_config.reset_for_tests()
    result = verified_assets.verify_paxg_integration()
    assert result == {"verified": False, "reason": "asset_integration_disabled"}
    enabled.chain.assert_not_called()
    enabled.probe.assert_not_called()


def test_registry_missing_rpc_is_unavailable_not_verified(enabled, monkeypatch):
    monkeypatch.delenv("ETHEREUM_MAINNET_RPC_URL")
    assert verified_assets.verify_paxg_integration() == {"verified": False, "reason": "rpc_not_configured"}
    enabled.probe.assert_not_called()


def test_registry_wrong_chain_never_probes_contract(enabled):
    enabled.chain.return_value = 11155111
    assert verified_assets.verify_paxg_integration() == {"verified": False, "reason": "chain_mismatch"}
    enabled.probe.assert_not_called()


@pytest.mark.parametrize("code", [None, 42, "", "0x", "0x00", "0x0000", "0xzz", "0x1", "6000"])
def test_registry_missing_or_malformed_code_fails_closed(enabled, code):
    enabled.probe.side_effect = None
    enabled.probe.return_value = {"result": code}
    assert verified_assets.verify_paxg_integration() == {"verified": False, "reason": "verified_token_contract_missing"}
    assert enabled.probe.call_count == 1


@pytest.mark.parametrize("decimals", [None, 18, "0x12", "0x" + format(6, "064x"), "0x" + format(19, "064x"), "0x" + "z" * 64])
def test_registry_only_accepts_well_formed_exact_18_decimals(enabled, decimals):
    enabled.probe.side_effect = [{"result": "0x6000"}, {"result": decimals}]
    result = verified_assets.verify_paxg_integration()
    assert result["verified"] is False
    assert result["reason"] in {"verified_token_decimals_mismatch", "verified_token_provider_unavailable"}


def test_registry_provider_error_is_redacted(enabled):
    enabled.chain.side_effect = evm_rpc.EvmRpcError("upstream_io")
    result = verified_assets.verify_paxg_integration()
    assert result == {"verified": False, "reason": "verified_token_provider_unavailable"}
    assert RPC not in str(result)


def test_registry_probes_only_pinned_contract_and_caches_public_verification(enabled, monkeypatch):
    monkeypatch.setenv("ETHEREUM_MAINNET_PAXG_CONTRACT_ADDRESS", "0x" + "ef" * 20)
    monkeypatch.setenv("ETHEREUM_MAINNET_PAXG_DECIMALS", "6")
    first = verified_assets.verify_paxg_integration()
    assert first["verified"] is True
    assert first["verifiedAt"].endswith("Z")
    assert verified_assets.verify_paxg_integration() == first
    assert enabled.probe.call_args_list[0].args == (RPC, "eth_getCode", [CONTRACT, "latest"])
    assert enabled.probe.call_args_list[1].args == (RPC, "eth_call", [{"to": CONTRACT, "data": "0x313ce567"}, "latest"])
    assert enabled.probe.call_count == 2
    from evm_networks import token_contract_for, networks_for_asset
    assert token_contract_for(NETWORK, ASSET) == CONTRACT
    assert token_contract_for("ethereum_sepolia", ASSET) == ""
    assert networks_for_asset(ASSET) == (NETWORK,)
    assert vault_config.ethereum_mainnet_token_decimals(ASSET) == 18
    assert vault_config.ethereum_mainnet_token_unit(ASSET) == "PAXG"


def test_fastapi_catalog_exact_categories_closed_verified_tuple_and_issuer_note(routes):
    catalog = _catalog(routes)
    assert catalog["schema"] == "svaultai_asset_catalog_v1"
    assert [(c["id"], c["label"]) for c in catalog["categories"]] == list(verified_assets.CATEGORIES)
    assert len(catalog["categories"]) == 10
    assert all(c["available"] is False for c in catalog["categories"][2:])
    assert catalog["categories"][2]["reason"] == "asset_integration_disabled"
    assert all(c["reason"] == "no_verified_token_integration" for c in catalog["categories"][3:])
    assert len(catalog["assets"]) == 2
    asset = catalog["assets"][0]
    for key, expected in {"id": ASSET, "symbol": "PAXG", "standard": "ERC20", "network": NETWORK,
                          "chainId": 1, "contractAddress": CONTRACT, "decimals": 18,
                          "category": "digital_gold", "verified": True}.items():
        assert asset[key] == expected
    assert all(asset[key] is True for key in ("receiveEnabled", "balanceEnabled", "sendEnabled", "activityConnected"))
    assert "freeze" in asset["transferNote"] and "gas" in asset["transferNote"] and "ETH" in asset["transferNote"]
    assert asset["verificationSource"] == "https://github.com/paxosglobal/paxos-gold-contract"


def test_catalog_and_routes_still_require_authoritative_entitlement(routes, monkeypatch):
    routes.app.dependency_overrides.pop(require_crypto_entitlement)
    monkeypatch.setattr("crypto_entitlement._resolve_upgraded_flag", lambda _vault: False)
    for path in ("/crypto/wallet/asset-catalog", ROOT_PATH + "/receive", ROOT_PATH + "/balance", ROOT_PATH + "/transactions"):
        response = routes.client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "crypto_vault_upgrade_required"
    routes.state.probe.assert_not_called()


@pytest.mark.parametrize("flag,keys", [
    ("VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED", ("receiveEnabled", "balanceEnabled", "activityConnected")),
    ("VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED", ("receiveEnabled", "balanceEnabled", "activityConnected")),
    ("VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED", ("sendEnabled",)),
    ("ETHEREUM_MAINNET_TX_INDEXER_API_KEY", ("activityConnected",)),
])
def test_catalog_capabilities_respect_independent_configured_gates(routes, monkeypatch, flag, keys):
    monkeypatch.setenv(flag, "" if flag.endswith("API_KEY") else "false")
    asset = _catalog(routes)["assets"][0]
    assert asset["verified"] is True
    assert all(asset[key] is False for key in keys)


def test_receive_and_account_detail_share_only_parent_mainnet_wallet(routes):
    receive = routes.client.get(ROOT_PATH + "/receive").json()
    assert receive["wallet_engine"] == "receive_ready"
    assert receive["asset"] == ASSET and receive["unit"] == "PAXG"
    assert receive["publicAddress"] == FROM and receive["underlyingAsset"] == "ETH"
    assert "ETH for gas" in receive["gasNote"]
    detail = routes.client.get(ROOT_PATH).json()
    assert detail["wallet_engine"] == "account_ready"
    assert detail["account"]["underlyingAsset"] == "ETH"
    assert detail["account"]["publicAddress"] == FROM
    assert "encryptedWalletSecret" not in detail["account"]
    assert all(call.args == (VAULT, f"ETH:{NETWORK}") for call in routes.loader.call_args_list)


@pytest.mark.parametrize("suffix", ["/receive", "", "/transactions"])
def test_parent_wallet_missing_never_invents_address(routes, suffix):
    routes.loader.side_effect = None
    routes.loader.return_value = None
    response = routes.client.get(ROOT_PATH + suffix)
    assert response.status_code == 200
    body = response.json()
    assert body.get("wallet_engine", body.get("reason")) == "create_eth_mainnet_wallet_first"
    assert not body.get("publicAddress") and not body.get("account")
    routes.indexer.assert_not_called()


def test_parent_sepolia_record_is_not_used_as_mainnet_wallet(routes):
    routes.record["network"] = "ethereum_sepolia"
    body = routes.client.get(ROOT_PATH + "/receive").json()
    assert body["wallet_engine"] == "create_eth_mainnet_wallet_first"
    assert "publicAddress" not in body


@pytest.mark.parametrize("base_units", [1, 1_234_567_890_123_456_789, 123_456_789_012_345_678_901_234_567_890, 2**256 - 1])
def test_live_balance_keeps_exact_18_decimal_uint256_precision(routes, base_units):
    token = routes.rpc["erc20_balance_of_at_url"]
    token.return_value = base_units
    response = routes.client.get(ROOT_PATH + "/balance", params={"address": FROM})
    assert response.status_code == 200
    body = response.json()
    assert body["balanceStatus"] == "available"
    assert body["availableAmount"] == _fixed_units(base_units)
    assert body["baseUnits"] == str(base_units)
    assert body["confirmedBalanceBaseUnits"] == body["spendableBalanceBaseUnits"] == str(base_units)
    assert body["decimals"] == 18 and body["tokenContract"] == CONTRACT
    assert body["asset"] == ASSET and body["networkId"] == NETWORK and body["chainId"] == 1
    token.assert_called_once_with(RPC, token_contract_address=CONTRACT, holder_address=FROM)


def test_live_balance_failure_is_unavailable_not_zero(routes):
    routes.rpc["erc20_balance_of_at_url"].side_effect = evm_rpc.EvmRpcError("upstream_io")
    body = routes.client.get(ROOT_PATH + "/balance", params={"address": FROM}).json()
    assert body["balanceStatus"] == "unavailable" and body["availableAmount"] is None
    assert body["providerStatus"] == "unavailable"
    assert body["reason"] == "upstream_io"


def test_disabled_registry_stops_receive_balance_and_history_before_wallet_provider(routes, monkeypatch):
    monkeypatch.setenv("VAULTAI_ASSETS_PAXG_ENABLED", "false")
    for suffix in ("/receive", "/balance", "/transactions"):
        body = routes.client.get(ROOT_PATH + suffix, params={"address": FROM}).json()
        assert body["wallet_engine"] == "asset_integration_unavailable"
        assert body["availableAmount"] is None and body["transactions"] == []
    routes.loader.assert_not_called()
    routes.rpc["erc20_balance_of_at_url"].assert_not_called()
    routes.indexer.assert_not_called()


def _indexer_row(*, tx_suffix="01", contract=CONTRACT, value=1_234_567_890_123_456_789, incoming=False):
    return {"hash": "0x" + tx_suffix * 32, "contractAddress": contract,
            "from": DEST if incoming else FROM, "to": FROM if incoming else DEST,
            "value": str(value), "tokenDecimal": "6", "tokenSymbol": "ATTACKER",
            "confirmations": "5", "timeStamp": "1791500000", "isError": "0"}


def test_history_queries_pinned_mainnet_contract_and_rejects_other_token_rows(routes):
    routes.indexer.side_effect = None
    routes.indexer.return_value = {"status": "1", "result": [
        _indexer_row(), _indexer_row(tx_suffix="02", incoming=True, value=1),
        _indexer_row(tx_suffix="03", contract="0x" + "ef" * 20),
    ]}
    body = routes.client.get(ROOT_PATH + "/transactions", params={"limit": 12}).json()
    assert body["transactionsStatus"] == "available" and body["network"] == NETWORK
    assert len(body["transactions"]) == 2
    first, incoming = body["transactions"]
    assert first["asset"] == ASSET and first["unit"] == "PAXG"
    assert first["amount"] == "1.234567890123456789" and first["direction"] == "outgoing"
    assert incoming["amount"] == "0.000000000000000001" and incoming["direction"] == "incoming"
    args = routes.indexer.call_args
    assert args.args == ("https://indexer.example.invalid/api",)
    assert args.kwargs["params"]["contractaddress"] == CONTRACT
    assert args.kwargs["params"]["chainid"] == 1
    assert args.kwargs["params"]["address"] == FROM
    assert args.kwargs["params"]["action"] == "tokentx"
    assert args.kwargs["params"]["offset"] == 12


def test_history_without_indexer_is_honestly_unavailable(routes, monkeypatch):
    monkeypatch.delenv("ETHEREUM_MAINNET_TX_INDEXER_API_KEY")
    body = routes.client.get(ROOT_PATH + "/transactions").json()
    assert body["transactionsStatus"] == "unavailable" and body["transactions"] == []
    routes.indexer.assert_not_called()


def test_history_provider_failure_does_not_look_like_empty_success(routes):
    routes.indexer.side_effect = evm_transaction_history.TxIndexerError("upstream_io")
    body = routes.client.get(ROOT_PATH + "/transactions").json()
    assert body["transactionsStatus"] == "unavailable"
    assert body["transactions"] == [] and body["reason"] == "upstream_error"


def test_draft_paxg_precision_contract_gas_and_parent_wallet_binding(routes):
    amount = "1.234567890123456789"
    response = _draft(routes, amount)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "draft_ready" and body["asset"] == ASSET
    assert body["amount"] == amount and body["amountBaseUnits"] == "1234567890123456789"
    assert body["decimals"] == 18 and body["unit"] == "PAXG"
    assert body["tokenContract"] == body["transactionTo"] == CONTRACT
    assert body["transactionValueWei"] == "0" and body["feeUnit"] == "ETH"
    assert body["chainId"] == 1 and body["gasLimit"] == str(GAS_LIMIT)
    assert body["estimatedFeeWei"] == body["maximumFeeWei"] == body["totalMaximumDebitWei"] == str(FEE)
    assert body["remainingBalanceWei"] == "1"
    calldata = "0xa9059cbb" + DEST[2:].rjust(64, "0") + format(int(body["amountBaseUnits"]), "064x")
    assert body["dataHex"] == calldata
    routes.rpc["eth_estimate_gas_at_url"].assert_called_once_with(RPC, from_address=FROM, to_address=CONTRACT, value_wei=0, data_hex=calldata)
    routes.rpc["erc20_balance_of_at_url"].assert_called_once_with(RPC, token_contract_address=CONTRACT, holder_address=FROM, block_tag="pending")
    routes.rpc["eth_get_balance_wei_at_url"].assert_called_once_with(RPC, FROM, block_tag="pending")
    draft = routes.state.store._drafts[body["draftId"]]
    assert draft["vault_id"] == VAULT and draft["asset"] == ASSET and draft["transaction_to"] == CONTRACT
    assert draft["value_wei"] == 0 and draft["data_hex"] == calldata
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


@pytest.mark.parametrize("amount", ["0", "-1", "+1", "1e-18", "abc", "1.0000000000000000001", str(2**256)])
def test_paxg_invalid_amount_or_precision_is_rejected_without_draft(routes, amount):
    response = _draft(routes, amount)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["wallet_engine"] == "invalid_amount"
    assert routes.state.store._drafts == {}
    routes.rpc["eth_estimate_gas_at_url"].assert_not_called()


@pytest.mark.parametrize("change,code", [
    ({"fromAddress": "0x" + "ef" * 20}, "from_address_mismatch"),
    ({"destinationAddress": "not-an-address"}, "invalid_destination_address"),
    ({"destinationAddress": FROM}, "self_send_refused"),
])
def test_draft_rejects_invalid_or_unowned_addresses(routes, change, code):
    response = _draft(routes, **change)
    assert response.status_code == 422
    assert response.json()["detail"]["wallet_engine"] == code
    routes.rpc["eth_estimate_gas_at_url"].assert_not_called()
    assert routes.state.store._drafts == {}


def test_draft_requires_existing_parent_wallet(routes):
    routes.loader.side_effect = None
    routes.loader.return_value = None
    body = _draft(routes).json()
    assert body["status"] == "draft_unavailable" and body["reason"] == "no_mainnet_wallet"
    routes.rpc["eth_estimate_gas_at_url"].assert_not_called()


def test_draft_insufficient_paxg_balance_checks_exact_base_units(routes):
    routes.rpc["erc20_balance_of_at_url"].return_value = 1_234_567_890_123_456_788
    body = _draft(routes).json()
    assert body["status"] == "insufficient_balance" and body["reason"] == "insufficient_token_balance"
    assert body["requiredBaseUnits"] == "1234567890123456789"
    assert body["availableBaseUnits"] == "1234567890123456788" and body["unit"] == "PAXG"
    assert routes.state.store._drafts == {}


def test_draft_insufficient_eth_gas_never_substitutes_token_for_network_fee(routes):
    routes.rpc["eth_get_balance_wei_at_url"].return_value = FEE - 1
    body = _draft(routes).json()
    assert body["status"] == "insufficient_balance" and body["reason"] == "insufficient_gas_eth"
    assert body["requiredWei"] == str(FEE) and body["availableWei"] == str(FEE - 1)
    assert routes.state.store._drafts == {}


@pytest.mark.parametrize("function,reason", [
    ("eth_estimate_gas_at_url", "upstream_rpc"),
    ("eth_get_balance_wei_at_url", "balance_check_failed"),
    ("erc20_balance_of_at_url", "token_balance_check_failed"),
])
def test_draft_simulation_revert_or_provider_failure_is_fail_closed(routes, function, reason):
    routes.rpc[function].side_effect = evm_rpc.EvmRpcError("upstream_rpc")
    body = _draft(routes).json()
    assert body["status"] == "draft_unavailable" and body["reason"] == reason
    assert routes.state.store._drafts == {}
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


@pytest.mark.parametrize("flag,value", [
    ("VAULTAI_ASSETS_PAXG_ENABLED", "false"),
    ("VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED", "false"),
    ("VAULTAI_CRYPTO_MAINNET_SEND_PAUSED", "true"),
])
def test_send_draft_and_broadcast_flags_cannot_be_bypassed(routes, monkeypatch, flag, value):
    # Gate a genuine reviewed new attempt, not a malformed no-draft request.
    # An already-consumed exact replay must retain its authoritative hash.
    from test_paxg_encrypted_draft_2026_10_09 import prepared
    fixture, draft_id = prepared(routes)
    routes.rpc["eth_estimate_gas_at_url"].reset_mock()
    monkeypatch.setenv(flag, value)
    draft = _draft(routes).json()
    assert draft.get("status") != "draft_ready"
    response = routes.client.post(ROOT_PATH + "/send/broadcast", json={
        "signedTransaction": fixture["signed_tx_hex"], "draftId": draft_id})
    assert response.status_code == 200
    assert response.json().get("status") != "submitted"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()
    routes.rpc["eth_estimate_gas_at_url"].assert_not_called()
    assert routes.state.store._drafts[draft_id]["consumed_at"] is None


@pytest.mark.parametrize("suffix", ["/receive", "/balance", "/transactions"])
def test_paxg_wrong_network_never_returns_actionable_result(routes, suffix):
    path = f"/crypto/wallet/network/ethereum_sepolia/{ASSET}{suffix}"
    body = routes.client.get(path, params={"address": FROM}).json()
    assert body.get("wallet_engine") not in {"receive_ready", "account_ready"}
    assert body.get("balanceStatus") != "available"
    assert body.get("transactionsStatus") != "available"
    routes.rpc["erc20_balance_of_at_url"].assert_not_called()
    routes.indexer.assert_not_called()


def test_paxg_broadcast_requires_bound_draft_before_simulated_rpc(routes):
    fixture = make_signed_tx_and_matching_draft(to_addr=CONTRACT)
    response = routes.client.post(ROOT_PATH + "/send/broadcast", json={"signedTransaction": fixture["signed_tx_hex"]})
    assert response.status_code == 422
    assert response.json()["detail"]["wallet_engine"] == "draft_id_required"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


def test_signed_paxg_broadcast_remains_exactly_once_with_fake_provider(routes):
    calldata = "0xa9059cbb" + DEST[2:].rjust(64, "0") + format(1, "064x")
    fixture = make_signed_tx_and_matching_draft(to_addr=CONTRACT, data=bytes.fromhex(calldata[2:]), gas_limit=GAS_LIMIT)
    did = "paxg-test-only-signed-draft"
    routes.state.store.seed_draft(did, vault_id=VAULT, network_id=NETWORK, asset=ASSET,
        sender_address=fixture["sender_address"], destination_address=DEST,
        value_wei=0, data_hex=calldata, nonce=fixture["nonce"], gas_limit=fixture["gas_limit"],
        gas_price=fixture["gas_price"], chain_id=1, transaction_to=CONTRACT)
    send = routes.rpc["eth_send_raw_transaction_at_url"]
    send.side_effect = None
    send.return_value = fixture["local_tx_hash"]
    visible = routes.rpc["eth_get_transaction_by_hash_at_url"]
    visible.side_effect = None
    visible.return_value = {"hash": fixture["local_tx_hash"], "blockNumber": None}
    payload = {"signedTransaction": fixture["signed_tx_hex"], "draftId": did, "idempotencyKey": "paxg-test-idempotency-2026-10-09"}
    first = routes.client.post(ROOT_PATH + "/send/broadcast", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "submitted" and first.json()["asset"] == ASSET
    assert first.json()["txHash"] == fixture["local_tx_hash"]
    second = routes.client.post(ROOT_PATH + "/send/broadcast", json=payload)
    assert second.status_code == 200 and second.json() == first.json()
    send.assert_called_once_with(RPC, fixture["signed_tx_hex"])


def test_arbitrary_unregistered_token_never_drafts_or_sends(routes):
    path = f"/crypto/wallet/network/{NETWORK}/UNVERIFIED_GOLD/send/draft"
    response = routes.client.post(path, json={"fromAddress": FROM, "destinationAddress": DEST, "amountEth": "1"})
    assert response.status_code == 200
    assert response.json()["status"] == "draft_unavailable"
    assert response.json()["reason"] == "asset_not_enabled_on_mainnet"
    routes.rpc["eth_estimate_gas_at_url"].assert_not_called()
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


@pytest.mark.parametrize("route_asset", ["ETH", "USDT_ERC20", "USDC_ERC20"])
@pytest.mark.parametrize("disabled", [False, True])
def test_paxg_stored_draft_cannot_broadcast_through_old_crypto_route(routes, monkeypatch, route_asset, disabled):
    calldata = "0xa9059cbb" + DEST[2:].rjust(64, "0") + format(1, "064x")
    fixture = make_signed_tx_and_matching_draft(to_addr=CONTRACT, data=bytes.fromhex(calldata[2:]), gas_limit=GAS_LIMIT)
    did = "paxg-test-only-route-bound-draft"
    routes.state.store.seed_draft(did, vault_id=VAULT, network_id=NETWORK, asset=ASSET,
        sender_address=fixture["sender_address"], destination_address=DEST,
        value_wei=0, data_hex=calldata, nonce=fixture["nonce"], gas_limit=fixture["gas_limit"],
        gas_price=fixture["gas_price"], chain_id=1, transaction_to=CONTRACT)
    if disabled:
        monkeypatch.setenv("VAULTAI_ASSETS_PAXG_ENABLED", "false")
        verified_assets.reset_verification_cache()
    response = routes.client.post(f"/crypto/wallet/network/{NETWORK}/{route_asset}/send/broadcast", json={
        "signedTransaction": fixture["signed_tx_hex"], "draftId": did})
    assert response.status_code == 400
    assert response.json()["detail"]["wallet_engine"] == "draft_asset_mismatch"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()
    assert not routes.state.store._drafts[did].get("consumed")


@pytest.mark.parametrize("route_asset", ["ETH", "USDT_ERC20", "USDC_ERC20"])
def test_paxg_cached_outcome_cannot_be_relabelled_as_old_crypto(routes, monkeypatch, route_asset):
    fixture = make_signed_tx_and_matching_draft(to_addr=CONTRACT)
    monkeypatch.setattr(wallet_routes, "_lookup_idempotent_broadcast", lambda *_: (
        {"status": "submitted", "asset": ASSET, "txHash": fixture["local_tx_hash"]}, False))
    response = routes.client.post(f"/crypto/wallet/network/{NETWORK}/{route_asset}/send/broadcast", json={
        "signedTransaction": fixture["signed_tx_hex"],
        "idempotencyKey": "paxg-test-only-cache-route-binding"})
    assert response.status_code == 400
    assert response.json()["detail"]["wallet_engine"] == "draft_asset_mismatch"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()
