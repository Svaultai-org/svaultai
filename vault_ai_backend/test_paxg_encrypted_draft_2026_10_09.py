"""Synthetic PAXG encrypted-intent and exact-fee tests: no external I/O/funds."""
from __future__ import annotations

import base64
from dataclasses import replace
from unittest.mock import Mock

import pytest

from _test_fake_mainnet_store import make_signed_tx_and_matching_draft
from evm_rpc import encode_erc20_transfer_calldata
from evm_signed_tx_verify import decode_and_recover, verify_signed_tx_against_draft
from paxg_draft_binding import bind_decoded_paxg_draft, paxg_intent_commitment
from test_verified_assets_2026_10_09 import (
    ASSET, CONTRACT, DEST, FEE, GAS_LIMIT, GAS_PRICE, NETWORK, ROOT_PATH, VAULT,
    _draft, enabled, routes,
)

AMOUNT = "1.234567890123456789"
UNITS = 1234567890123456789
CT = base64.urlsafe_b64encode(b"synthetic-ciphertext-no-vault-content" * 2).decode().rstrip("=")
LOOKUP = base64.urlsafe_b64encode(b"l" * 32).decode().rstrip("=")


def signed(**overrides):
    from eth_utils import to_checksum_address
    fields = dict(nonce=7, gas_price=GAS_PRICE, gas_limit=GAS_LIMIT,
                  to_addr=CONTRACT, value_wei=0,
                  data=bytes.fromhex(encode_erc20_transfer_calldata(
                      destination_address=DEST, amount_base_units=UNITS)[2:]), chain_id=1)
    fields.update(overrides)
    fields["to_addr"] = to_checksum_address(fields["to_addr"])
    return make_signed_tx_and_matching_draft(**fields)


def intent(fixture):
    return dict(asset=ASSET, sender_address=fixture["sender_address"],
                destination_address=DEST, value_wei=fixture["value_wei"],
                data_hex=fixture["data_hex"], nonce=fixture["nonce"],
                gas_limit=fixture["gas_limit"], gas_price=fixture["gas_price"],
                chain_id=fixture["chain_id"], transaction_to=fixture["transaction_to"])


def bound(fixture):
    digest = paxg_intent_commitment(draft_id="synthetic-random-draft", vault_id=VAULT,
                                    network_id=NETWORK, **intent(fixture))
    return dict(draft_id="synthetic-random-draft", vault_id=VAULT, network_id=NETWORK,
                asset=ASSET, paxg_ciphertext_bound=True, paxg_intent_commitment=digest,
                nonce=7, gas_limit=GAS_LIMIT, gas_price=GAS_PRICE, chain_id=1)


def prepared(routes):
    fixture = signed()
    routes.record["publicAddress"] = fixture["sender_address"]
    response = _draft(routes, AMOUNT, fromAddress=fixture["sender_address"],
                      draftPayloadCiphertext=CT, senderAddressLookupHash=LOOKUP)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "draft_ready"
    return fixture, body["draftId"]


def test_intent_commitment_is_exact_deterministic_and_signature_bindable():
    fixture = signed()
    draft = bound(fixture)
    assert len(draft["paxg_intent_commitment"]) == 32
    decoded = decode_and_recover(fixture["signed_tx_hex"])
    hydrated = bind_decoded_paxg_draft(draft, decoded)
    assert verify_signed_tx_against_draft(raw_signed_tx_hex=fixture["signed_tx_hex"], draft=hydrated).ok
    assert hydrated["destination_address"] == DEST.lower()
    assert bind_decoded_paxg_draft({**draft, "paxg_intent_commitment": memoryview(draft["paxg_intent_commitment"])}, decoded) == hydrated


@pytest.mark.parametrize("field,value", [
    ("nonce", 8), ("gas_price", GAS_PRICE + 1), ("gas_limit", GAS_LIMIT + 1),
    ("value_wei", 1), ("chain_id_from_v", 11155111),
    ("to_lower", "0x" + "dd" * 20), ("recovered_sender_lower", "0x" + "ee" * 20),
    ("data_hex", encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=UNITS + 1)),
    ("data_hex", encode_erc20_transfer_calldata(destination_address="0x" + "ef" * 20, amount_base_units=UNITS)),
    ("data_hex", "0xa9059cbb" + "1" + "0" * 127),
    ("data_hex", "0x095ea7b3" + "0" * 128),
    ("data_hex", encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=0)),
    ("data_hex", encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=UNITS) + "00"),
])
def test_altered_signed_public_tuple_cannot_hydrate(field, value):
    fixture = signed()
    decoded = replace(decode_and_recover(fixture["signed_tx_hex"]), **{field: value})
    with pytest.raises(ValueError, match="binding_failed"):
        bind_decoded_paxg_draft(bound(fixture), decoded)


@pytest.mark.parametrize("field,value", [("draft_id", "other-draft"), ("vault_id", "other-vault"),
                                         ("network_id", "ethereum_sepolia"), ("asset", "USDT_ERC20")])
def test_binding_cannot_transfer_between_drafts_vaults_networks(field, value):
    fixture = signed()
    with pytest.raises(ValueError, match="binding_failed"):
        bind_decoded_paxg_draft({**bound(fixture), field: value}, decode_and_recover(fixture["signed_tx_hex"]))


@pytest.mark.parametrize("commitment", [None, b"", b"x" * 31, b"x" * 33, "x" * 32])
def test_missing_malformed_commitment_never_hydrates(commitment):
    fixture = signed()
    with pytest.raises(ValueError, match="binding_missing"):
        bind_decoded_paxg_draft({**bound(fixture), "paxg_intent_commitment": commitment},
                               decode_and_recover(fixture["signed_tx_hex"]))


def test_ciphertext_draft_broadcast_and_exact_replay_once(routes):
    fixture, draft_id = prepared(routes)
    persisted = routes.state.store._drafts[draft_id]
    for field in ("sender_address_lower", "asset", "destination_address", "value_wei", "data_hex", "transaction_to"):
        assert persisted[field] is None
    assert len(persisted["paxg_intent_commitment"]) == 32
    routes.rpc["eth_send_raw_transaction_at_url"].return_value = fixture["local_tx_hash"]
    routes.rpc["eth_get_transaction_by_hash_at_url"].return_value = {"hash": fixture["local_tx_hash"]}
    routes.rpc["eth_send_raw_transaction_at_url"].side_effect = None
    routes.rpc["eth_get_transaction_by_hash_at_url"].side_effect = None
    payload = dict(signedTransaction=fixture["signed_tx_hex"], draftId=draft_id, idempotencyKey="paxg-ct-replay-01")
    first = routes.client.post(ROOT_PATH + "/send/broadcast", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "submitted"
    again = routes.client.post(ROOT_PATH + "/send/broadcast", json=payload)
    assert again.status_code == 200
    assert again.json()["txHash"] == fixture["local_tx_hash"]
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    consumed = routes.client.post(ROOT_PATH + "/send/broadcast", json={**payload, "idempotencyKey": "paxg-ct-replay-02"})
    assert consumed.json()["status"] == "already_submitted"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()


@pytest.mark.parametrize("overrides", [
    {"nonce": 8}, {"gas_price": GAS_PRICE + 1}, {"gas_limit": GAS_LIMIT + 1},
    {"chain_id": 11155111}, {"value_wei": 1}, {"to_addr": "0x" + "dd" * 20},
    {"priv_key_hex": "0x" + "45" * 32},
    {"data": bytes.fromhex(encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=UNITS + 1)[2:])},
])
def test_real_signature_tamper_rejects_before_claim_or_rpc(routes, overrides):
    _, draft_id = prepared(routes)
    claim = Mock(wraps=routes.state.store.claim_draft)
    routes.state.store.claim_draft = claim
    mutated = signed(**overrides)
    result = routes.client.post(ROOT_PATH + "/send/broadcast", json=dict(
        signedTransaction=mutated["signed_tx_hex"], draftId=draft_id))
    assert result.status_code == 400, result.text
    assert result.json()["detail"]["wallet_engine"] == "paxg_encrypted_draft_binding_failed"
    claim.assert_not_called()
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()
    assert routes.state.store._drafts[draft_id]["consumed_at"] is None


@pytest.mark.parametrize("legacy_asset", ["ETH", "USDT_ERC20", "USDC_ERC20"])
def test_bound_ct_row_cannot_bypass_asset_gate_through_other_route(routes, legacy_asset):
    fixture, draft_id = prepared(routes)
    result = routes.client.post(f"/crypto/wallet/network/{NETWORK}/{legacy_asset}/send/broadcast", json=dict(
        signedTransaction=fixture["signed_tx_hex"], draftId=draft_id))
    assert result.status_code == 400
    assert result.json()["detail"]["wallet_engine"] == "draft_asset_mismatch"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


def test_old_unbound_ciphertext_row_requires_redraft(routes):
    fixture, draft_id = prepared(routes)
    routes.state.store._drafts[draft_id]["paxg_intent_commitment"] = None
    result = routes.client.post(ROOT_PATH + "/send/broadcast", json=dict(
        signedTransaction=fixture["signed_tx_hex"], draftId=draft_id))
    assert result.status_code == 400
    assert result.json()["detail"]["wallet_engine"] == "paxg_encrypted_draft_binding_missing"
    assert routes.state.store._drafts[draft_id]["consumed_at"] is None
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


def test_caller_cannot_choose_intent_commitment(routes):
    result = _draft(routes, paxgIntentCommitment="attacker-controlled")
    assert result.status_code == 422


@pytest.mark.parametrize("field,value", [("nonce", 8), ("gas_limit", GAS_LIMIT + 1),
                                         ("gas_price", GAS_PRICE + 1), ("chain_id", 11155111)])
def test_existing_verifier_retains_independent_persisted_protocol_checks(routes, field, value):
    fixture, draft_id = prepared(routes)
    routes.state.store._drafts[draft_id][field] = value
    claim = Mock(wraps=routes.state.store.claim_draft)
    routes.state.store.claim_draft = claim
    result = routes.client.post(ROOT_PATH + "/send/broadcast", json={
        "signedTransaction": fixture["signed_tx_hex"], "draftId": draft_id})
    assert result.status_code == 400
    assert result.json()["detail"]["wallet_engine"] == field + "_mismatch"
    claim.assert_not_called()
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


def test_plaintext_history_excludes_only_new_bound_ct_rows(routes):
    fixture, draft_id = prepared(routes)
    routes.rpc["eth_send_raw_transaction_at_url"].side_effect = None
    routes.rpc["eth_send_raw_transaction_at_url"].return_value = fixture["local_tx_hash"]
    routes.rpc["eth_get_transaction_by_hash_at_url"].side_effect = None
    routes.rpc["eth_get_transaction_by_hash_at_url"].return_value = {"hash": fixture["local_tx_hash"]}
    assert routes.client.post(ROOT_PATH + "/send/broadcast", json={
        "signedTransaction": fixture["signed_tx_hex"], "draftId": draft_id}).status_code == 200
    response = routes.client.get(f"/crypto/wallet/network/{NETWORK}/outgoing/history")
    assert response.json()["status"] == "ok" and response.json()["outgoing"] == []
    assert routes.state.store._drafts[draft_id]["value_wei"] is None


def test_additive_migration_sqlalchemy_wrapper_has_no_bind_parameters(monkeypatch):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import text
    path = Path(__file__).parent / "migrations/versions/0048_paxg_encrypted_draft_binding.py"
    spec = importlib.util.spec_from_file_location("test_paxg_binding_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0047_concierge_exposure"
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    assert len(statements) == 2
    assert all(not text(statement)._bindparams for statement in statements)
    assert all("UPDATE" not in statement and "DELETE" not in statement for statement in statements)
    statements.clear()
    migration.downgrade()
    assert len(statements) == 2
    assert all("DROP TABLE" not in statement and "DELETE" not in statement for statement in statements)


@pytest.mark.parametrize("amount", [None, "", "0", "-1", "1e2", "0.0000000000000000001", "9" * 80])
def test_paxg_fee_requote_missing_or_invalid_exact_amount_fails_closed(routes, amount):
    payload = {"fromAddress": routes.record["publicAddress"], "destinationAddress": DEST, "asset": ASSET}
    if amount is not None:
        payload["amountEth"] = amount
    result = routes.client.post(f"/crypto/wallet/network/{NETWORK}/send/fee_estimate", json=payload)
    assert result.status_code == 200
    assert result.json()["reason"] == "exact_paxg_amount_required"
    routes.rpc["eth_estimate_gas_at_url"].assert_not_called()


def test_paxg_fee_requote_estimates_exact_reviewed_calldata(routes):
    result = routes.client.post(f"/crypto/wallet/network/{NETWORK}/send/fee_estimate", json={
        "fromAddress": routes.record["publicAddress"], "destinationAddress": DEST,
        "asset": ASSET, "amountEth": AMOUNT})
    assert result.json()["status"] == "fee_estimate_ready"
    assert result.json()["amountBaseUnits"] == str(UNITS)
    assert result.json()["maximumFeeWei"] == str(FEE)
    assert routes.rpc["eth_estimate_gas_at_url"].call_args.kwargs["data_hex"] == encode_erc20_transfer_calldata(
        destination_address=DEST, amount_base_units=UNITS)


@pytest.mark.parametrize("asset", ["USDT_ERC20", "USDC_ERC20"])
def test_legacy_token_quote_without_amount_retains_one_unit_default(routes, asset, monkeypatch):
    suffix = "USDT" if asset == "USDT_ERC20" else "USDC"
    monkeypatch.setenv(f"ETHEREUM_MAINNET_{suffix}_CONTRACT_ADDRESS", "0x" + "12" * 20)
    result = routes.client.post(f"/crypto/wallet/network/{NETWORK}/send/fee_estimate", json={
        "fromAddress": routes.record["publicAddress"], "destinationAddress": DEST, "asset": asset})
    assert result.json()["status"] == "fee_estimate_ready"
    assert "amountBaseUnits" not in result.json()
    assert routes.rpc["eth_estimate_gas_at_url"].call_args.kwargs["data_hex"] == encode_erc20_transfer_calldata(
        destination_address=DEST, amount_base_units=1)


@pytest.mark.parametrize("rpc_name,value", [
    ("eth_estimate_gas_at_url", 0), ("eth_estimate_gas_at_url", -1),
    ("eth_estimate_gas_at_url", "60000"), ("eth_estimate_gas_at_url", True),
    ("eth_estimate_gas_at_url", None), ("eth_estimate_gas_at_url", 2**63),
    ("eth_gas_price_wei_at_url", 0), ("eth_gas_price_wei_at_url", -1),
    ("eth_gas_price_wei_at_url", "1000000000"), ("eth_gas_price_wei_at_url", False),
    ("eth_gas_price_wei_at_url", None), ("eth_gas_price_wei_at_url", 2**256),
])
def test_paxg_malformed_rpc_fee_never_becomes_draft_or_quote(routes, rpc_name, value):
    routes.rpc[rpc_name].return_value = value
    draft = _draft(routes, AMOUNT, draftPayloadCiphertext=CT, senderAddressLookupHash=LOOKUP)
    assert draft.status_code == 200 and draft.json()["status"] == "draft_unavailable", draft.text
    assert draft.json()["reason"] == "paxg_fee_parameters_invalid"
    quote = routes.client.post(f"/crypto/wallet/network/{NETWORK}/send/fee_estimate", json={
        "fromAddress": routes.record["publicAddress"], "destinationAddress": DEST,
        "asset": ASSET, "amountEth": AMOUNT})
    assert quote.status_code == 200 and quote.json()["status"] == "fee_estimate_unavailable", quote.text
    assert quote.json()["reason"] == "paxg_fee_parameters_invalid"
    assert routes.state.store._drafts == {}


@pytest.mark.parametrize("nonce", [-1, None, True, "7", 2**63])
def test_paxg_malformed_rpc_nonce_never_registers_encrypted_binding(routes, nonce):
    routes.rpc["eth_get_transaction_count_at_url"].return_value = nonce
    result = _draft(routes, AMOUNT, draftPayloadCiphertext=CT, senderAddressLookupHash=LOOKUP)
    assert result.status_code == 200 and result.json()["status"] == "draft_unavailable", result.text
    assert routes.state.store._drafts == {}
