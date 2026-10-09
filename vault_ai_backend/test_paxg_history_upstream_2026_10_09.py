"""PAXG activity distinguishes provider errors from empty history, offline only."""

from __future__ import annotations

import json

import pytest

import evm_transaction_history as history
from test_verified_assets_2026_10_09 import (
    ASSET,
    CONTRACT,
    FROM,
    NETWORK,
    ROOT_PATH,
    _indexer_row,
    enabled,
    routes,
)


ERROR_BODIES = [
    {"status": "0", "message": "NOTOK", "result": "Invalid API Key synthetic-secret"},
    {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"},
    {"status": "0", "message": "NOTOK", "result": "Free API access is not supported for this chain. Upgrade your plan."},
    {"status": "0", "message": "NOTOK", "result": "Daily request quota exceeded"},
    {"status": "0", "message": "Invalid API Key", "result": []},
    {"status": "0", "result": []},
    {"status": "0", "message": "No transactions found", "result": None},
    {"status": "0", "message": "No transactions found", "result": "upstream failed"},
    {"status": "0", "message": "NOTOK", "result": [{"error": "provider failed"}]},
    {"status": "1", "message": "NOTOK", "result": []},
    {"status": "1", "result": "not a transaction list"},
    {"status": "1", "result": [None]},
    {"status": "1", "message": "OK", "result": [{"error": "synthetic-secret"}]},
    {"status": "1", "message": "OK", "result": [{"unexpected": "synthetic-secret"}]},
    {"status": "1", "message": "OK", "result": [], "error": "synthetic-secret"},
    {"status": "0", "message": "No transactions found", "result": [], "error": "synthetic-secret"},
    {"status": "unexpected", "result": []},
    {"result": [], "error": {"code": -32603, "message": "synthetic-secret"}},
]


@pytest.mark.parametrize("body", ERROR_BODIES)
def test_paxg_route_provider_errors_are_unavailable_not_empty_success(routes, body, caplog):
    routes.indexer.side_effect = None
    routes.indexer.return_value = body
    response = routes.client.get(ROOT_PATH + "/transactions")
    assert response.status_code == 200
    result = response.json()
    assert result["transactionsStatus"] == "unavailable"
    assert result["reason"] == "upstream_error"
    assert result["transactions"] == []
    assert "synthetic-secret" not in json.dumps(result) + caplog.text
    assert "Invalid API Key" not in json.dumps(result) + caplog.text
    assert "Upgrade your plan" not in json.dumps(result) + caplog.text


@pytest.mark.parametrize("body", [
    {"status": "0", "message": "No transactions found", "result": []},
    {"status": "0", "message": "No records found", "result": []},
    {"status": "0", "message": "No transactions found", "result": "No transactions found"},
    {"status": "0", "message": "NOTOK", "result": "No records found"},
    {"status": "1", "message": "OK", "result": []},
])
def test_paxg_route_genuine_empty_history_remains_successful(routes, body):
    routes.indexer.side_effect = None
    routes.indexer.return_value = body
    response = routes.client.get(ROOT_PATH + "/transactions")
    assert response.status_code == 200
    result = response.json()
    assert result["transactionsStatus"] == "available"
    assert result["transactions"] == []
    assert result.get("reason") != "upstream_error"


def test_paxg_valid_transfer_history_preserves_exact_amount_and_contract(routes):
    routes.indexer.side_effect = None
    routes.indexer.return_value = {"status": "1", "message": "OK", "result": [_indexer_row()]}
    result = routes.client.get(ROOT_PATH + "/transactions").json()
    assert result["transactionsStatus"] == "available"
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["amount"] == "1.234567890123456789"
    assert result["transactions"][0]["asset"] == ASSET
    assert routes.indexer.call_args.kwargs["params"]["contractaddress"] == CONTRACT


@pytest.mark.parametrize("overrides", [
    {"hash": "malformed"},
    {"contractAddress": None},
    {"contractAddress": "malformed"},
    {"from": "malformed"},
    {"value": "malformed"},
    {"error": "synthetic-secret"},
])
def test_paxg_malformed_successful_record_is_unavailable(routes, overrides):
    routes.indexer.side_effect = None
    routes.indexer.return_value = {
        "status": "1", "message": "OK",
        "result": [{**_indexer_row(), **overrides}],
    }
    result = routes.client.get(ROOT_PATH + "/transactions").json()
    assert result["transactionsStatus"] == "unavailable"
    assert result["reason"] == "upstream_error"
    assert result["transactions"] == []
    assert "synthetic-secret" not in json.dumps(result)


def test_paxg_well_formed_other_token_is_filtered_without_false_provider_error(routes):
    routes.indexer.side_effect = None
    routes.indexer.return_value = {
        "status": "1", "message": "OK",
        "result": [_indexer_row(contract="0x" + "ef" * 20)],
    }
    result = routes.client.get(ROOT_PATH + "/transactions").json()
    assert result["transactionsStatus"] == "available"
    assert result["transactions"] == []
    assert result.get("reason") != "upstream_error"


@pytest.mark.parametrize("value", [
    -1, "-1", True, False, 1.0, "1.0", "1e18", "0x01", "+1",
    " 1", "1 ", "", None, "\u0661", 2**256, str(2**256), "0" * 79,
    "9" * 10_000,
])
def test_paxg_impossible_or_malformed_uint256_value_is_unavailable(routes, value):
    routes.indexer.side_effect = None
    routes.indexer.return_value = {
        "status": "1", "message": "OK",
        "result": [{**_indexer_row(), "value": value}],
    }
    result = routes.client.get(ROOT_PATH + "/transactions").json()
    assert result["transactionsStatus"] == "unavailable"
    assert result["reason"] == "upstream_error"
    assert result["transactions"] == []


@pytest.mark.parametrize("value", [0, "0", "0001", 1, 2**256 - 1, str(2**256 - 1)])
def test_paxg_uint256_boundaries_and_zero_events_are_preserved(routes, value):
    routes.indexer.side_effect = None
    routes.indexer.return_value = {
        "status": "1", "message": "OK",
        "result": [{**_indexer_row(), "value": value}],
    }
    result = routes.client.get(ROOT_PATH + "/transactions").json()
    assert result["transactionsStatus"] == "available"
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["amount"] == history._format_units(int(value), 18)


@pytest.mark.parametrize("value", [-1, "-1", True, str(2**256)])
def test_legacy_token_value_normalizer_policy_is_not_changed(value):
    raw = history._row_to_raw_erc20(
        {**_indexer_row(), "value": value}, expected_contract=CONTRACT,
    )
    assert raw is not None
    assert raw.value_units == int(value)


@pytest.mark.parametrize("provider", ["etherscan", "blockscout"])
def test_paxg_strict_mode_applies_to_each_existing_indexer(provider, monkeypatch):
    monkeypatch.setattr(history, "_network_indexer_config", lambda _: (
        provider, "https://indexer.example.invalid", "synthetic-key", 1,
    ))
    monkeypatch.setattr(history, "_http_get", lambda *_, **__: {
        "status": "0", "message": "NOTOK", "result": "Invalid API Key",
    })
    with pytest.raises(history.TxIndexerError, match="^upstream_rpc$"):
        history._query_provider(
            address=FROM, action="tokentx", contract_address=CONTRACT,
            limit=20, network_id=NETWORK, strict_upstream=True,
        )


@pytest.mark.parametrize("asset", ["ETH", "USDT_ERC20", "USDC_ERC20"])
def test_existing_crypto_history_does_not_opt_into_paxg_policy(asset, monkeypatch):
    captured = []
    monkeypatch.setattr(history, "_network_indexer_configured", lambda _: True)
    monkeypatch.setattr(history, "_network_token_contract", lambda *_: CONTRACT)
    monkeypatch.setattr(history, "_network_token_decimals", lambda *_: 18)
    monkeypatch.setattr(history, "_network_token_unit", lambda *_: "TEST")

    def query(**kwargs):
        captured.append(kwargs)
        return []

    monkeypatch.setattr(history, "_query_provider", query)
    result = (
        history.list_eth_transactions(FROM, network_id=NETWORK)
        if asset == "ETH"
        else history.list_erc20_transactions(FROM, asset=asset, network_id=NETWORK)
    )
    assert result["transactionsStatus"] == "available"
    assert len(captured) == 1
    assert "strict_upstream" not in captured[0]


@pytest.mark.parametrize("provider", ["etherscan", "blockscout"])
@pytest.mark.parametrize("body", [
    {"status": "0", "message": "NOTOK", "result": "Invalid API Key"},
    {"status": "1", "message": "OK", "result": [], "error": "synthetic-error"},
])
def test_default_existing_indexer_behavior_is_unchanged(provider, body, monkeypatch):
    monkeypatch.setattr(history, "_network_indexer_config", lambda _: (
        provider, "https://indexer.example.invalid", "synthetic-key", 1,
    ))
    monkeypatch.setattr(history, "_http_get", lambda *_, **__: body)
    assert history._query_provider(
        address=FROM, action="tokentx", contract_address=CONTRACT,
        limit=20, network_id=NETWORK,
    ) == []
