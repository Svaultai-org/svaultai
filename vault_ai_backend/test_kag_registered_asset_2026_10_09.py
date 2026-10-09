"""Synthetic closed KAG integration: no external RPC, DB, accounts or funds."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import evm_rpc
import verified_assets as assets
from _test_fake_mainnet_store import make_signed_tx_and_matching_draft
from paxg_draft_binding import kag_intent_commitment, bind_decoded_kag_draft
from evm_signed_tx_verify import decode_and_recover, verify_signed_tx_against_draft
from test_verified_assets_2026_10_09 import enabled, routes, FROM, DEST, NETWORK, VAULT, GAS_PRICE, GAS_LIMIT, _indexer_row
from test_paxg_encrypted_draft_2026_10_09 import CT, LOOKUP, AMOUNT, UNITS
from routes import crypto_wallet_routes as wallet

ASSET = assets.KAG_ASSET
CONTRACT = assets.KAG_CONTRACT
PATH = f"/crypto/wallet/network/{NETWORK}/{ASSET}"
WORD = lambda n: "0x" + format(n, "064x")


@pytest.fixture
def kag(routes, monkeypatch):
    monkeypatch.setenv("VAULTAI_ASSETS_KAG_ENABLED", "true")
    code = "0x60016000"
    monkeypatch.setattr(assets, "KAG_CODE_SHA256", {
        a.lower(): hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()
        for a in (CONTRACT, assets.KAG_IMPLEMENTATION, assets.KAG_ACCESS_REGISTRY, assets.KAG_REGISTRY_IMPLEMENTATION)})
    state = SimpleNamespace(paused=False, registry_paused=False, denied=set(), change=None,
                            code=code, chain="0x1", malformed=None)

    def batch(_url, calls):
        values = []
        for method, params in calls:
            if method == "eth_chainId":
                value = state.chain
            elif method == "eth_blockNumber":
                value = "0x123456"
            elif method == "eth_getCode":
                value = state.code
            elif method == "eth_getStorageAt":
                expected = assets.KAG_IMPLEMENTATION if params[0] == CONTRACT else assets.KAG_REGISTRY_IMPLEMENTATION
                value = WORD(int(state.change or expected, 16))
            else:
                call = params[0]
                data = call["data"]
                if data == "0x313ce567":
                    value = WORD(18)
                elif data == "0xe6f29b05":
                    value = WORD(int(assets.KAG_ACCESS_REGISTRY, 16))
                elif data == "0x5c975abb":
                    value = WORD(int(state.paused if call["to"] == CONTRACT else state.registry_paused))
                elif data.startswith("0xeefb7e9a"):
                    account = "0x" + data[34:74]
                    value = WORD(int(account.lower() not in state.denied))
                else:
                    raise AssertionError("unexpected issuer ABI")
            values.append({"result": state.malformed if state.malformed is not None else value})
        return values

    probe = Mock(side_effect=batch)
    monkeypatch.setattr(evm_rpc, "emit_readonly_rpc_batch_at_url", probe)
    return SimpleNamespace(routes=routes, state=state, probe=probe)


def signed(**overrides):
    from eth_utils import to_checksum_address
    fields = dict(nonce=7, gas_price=GAS_PRICE, gas_limit=GAS_LIMIT, to_addr=CONTRACT,
                  value_wei=0, data=bytes.fromhex(evm_rpc.encode_erc20_transfer_calldata(
                      destination_address=DEST, amount_base_units=UNITS)[2:]), chain_id=1)
    fields.update(overrides)
    fields["to_addr"] = to_checksum_address(fields["to_addr"])
    return make_signed_tx_and_matching_draft(**fields)


def create(kag, **overrides):
    fixture = signed()
    kag.routes.record["publicAddress"] = fixture["sender_address"]
    payload = dict(fromAddress=fixture["sender_address"], destinationAddress=DEST, amountEth=AMOUNT,
                   draftPayloadCiphertext=CT, senderAddressLookupHash=LOOKUP)
    payload.update(overrides)
    return fixture, kag.routes.client.post(PATH + "/send/draft", json=payload)


def test_catalog_closed_tuple_and_unsupported_categories(kag, monkeypatch):
    monkeypatch.setenv("ETHEREUM_MAINNET_KAG_CONTRACT_ADDRESS", "0x" + "ff" * 20)
    monkeypatch.setenv("ETHEREUM_MAINNET_KAG_DECIMALS", "6")
    catalog = kag.routes.client.get("/crypto/wallet/asset-catalog").json()
    token = next(t for t in catalog["assets"] if t["id"] == ASSET)
    assert token["contractAddress"] == CONTRACT and token["decimals"] == 18
    assert token["name"] == "KMS Labs KAG Silver" and token["verified"]
    assert token["verificationSource"].startswith("https://kmslabs.money/")
    assert token["issuerTerms"] == "https://kmslabs.money/kms-labs-tcs/"
    assert "not buying" in token["eligibilityNote"]
    for name in ("tokenized_inventory_supply_chain", "tokenized_securities_equities"):
        category = next(c for c in catalog["categories"] if c["id"] == name)
        assert not category["available"] and category["reason"] == "no_verified_token_integration"
    from evm_networks import token_contract_for, networks_for_asset
    assert token_contract_for(NETWORK, ASSET) == CONTRACT
    assert token_contract_for("ethereum_sepolia", ASSET) == ""
    assert networks_for_asset(ASSET) == (NETWORK,)


@pytest.mark.parametrize("flag", [None, "false", "garbage"])
def test_disabled_default_never_calls_provider(kag, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("VAULTAI_ASSETS_KAG_ENABLED")
    else:
        monkeypatch.setenv("VAULTAI_ASSETS_KAG_ENABLED", flag)
    assert assets.verify_kag_integration()["reason"] == "asset_integration_disabled"
    kag.probe.assert_not_called()


@pytest.mark.parametrize("field,value,reason", [
    ("chain", "0xaa36a7", "chain_mismatch"),
    ("code", "0x60026000", "issuer_code_fingerprint_mismatch"),
    ("code", "0x", "verified_token_contract_missing"),
    ("change", "0x" + "ee" * 20, "issuer_implementation_changed"),
        ("malformed", "0x1", "verified_token_contract_missing"),
])
def test_unknown_chain_code_upgrade_or_response_fails_closed(kag, field, value, reason):
    setattr(kag.state, field, value)
    result = assets.verify_kag_integration()
    assert result["verified"] is False and result["reason"] == reason


def test_pause_disables_transfers_not_balance_or_history(kag):
    kag.state.paused = True
    capabilities = assets.kag_capabilities()
    assert capabilities["verified"] and capabilities["balanceEnabled"] and capabilities["activityConnected"]
    assert not capabilities["sendEnabled"] and not capabilities["receiveEnabled"]
    catalog = kag.routes.client.get("/crypto/wallet/asset-catalog").json()
    assert next(c for c in catalog["categories"] if c["id"] == "digital_silver")["available"]
    assert kag.routes.client.get(PATH).json()["wallet_engine"] == "account_ready"
    assert kag.routes.client.get(PATH + "/balance", params={"address": FROM}).json()["balanceStatus"] == "available"
    assert kag.routes.client.get(PATH + "/receive").json()["reason"] == "issuer_paused"


def test_same_block_snapshot_exact_access_abi_and_no_stale_cache(kag):
    data = evm_rpc.encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=UNITS)
    assert assets.verify_kag_integration(sender=FROM, recipient=DEST, data_hex=data)["transfersAllowed"]
    calls = kag.probe.call_args.args[1]
    assert len(calls) == 12
    assert all(params[-1] == "0x123456" for _, params in calls)
    access_calls = calls[-2:]
    assert all(params[0]["from"] == CONTRACT for _, params in access_calls)
    assert access_calls[0][1][0]["data"].endswith(data[2:] + "0" * 56)
    kag.state.denied.add(DEST.lower())
    assert assets.verify_kag_integration(sender=FROM, recipient=DEST, data_hex=data)["reason"] == "issuer_address_restricted"
    assert kag.probe.call_count == 4


def test_receive_denied_address_does_not_offer_receiving(kag):
    kag.state.denied.add(FROM.lower())
    body = kag.routes.client.get(PATH + "/receive").json()
    assert body["reason"] == "issuer_address_restricted"
    assert "publicAddress" not in body


@pytest.mark.parametrize("address", [None, "", "bad-address"])
def test_receive_missing_or_malformed_address_is_not_offered(kag, address):
    kag.routes.record["publicAddress"] = address
    body = kag.routes.client.get(PATH + "/receive").json()
    assert body["wallet_engine"] == "asset_integration_unavailable"
    assert "publicAddress" not in body


@pytest.mark.parametrize("amount", [None, "", "0", "1.0000000000000000001", "1e18"])
def test_quote_requires_exact_positive_amount_before_estimate(kag, amount):
    result = kag.routes.client.post(f"/crypto/wallet/network/{NETWORK}/send/fee_estimate",
        json=dict(asset=ASSET, fromAddress=FROM, destinationAddress=DEST, amountEth=amount)).json()
    assert result["reason"] == "exact_kag_amount_required"
    kag.routes.rpc["eth_estimate_gas_at_url"].assert_not_called()


def test_exact_fee_quote_and_fresh_denied_recipient_blocks(kag):
    path = f"/crypto/wallet/network/{NETWORK}/send/fee_estimate"
    payload = dict(asset=ASSET, fromAddress=FROM, destinationAddress=DEST, amountEth=AMOUNT)
    body = kag.routes.client.post(path, json=payload).json()
    assert body["status"] == "fee_estimate_ready" and body["amountBaseUnits"] == str(UNITS)
    assert kag.routes.rpc["eth_estimate_gas_at_url"].call_args.kwargs["to_address"] == CONTRACT
    kag.routes.rpc["eth_estimate_gas_at_url"].reset_mock()
    kag.state.denied.add(DEST.lower())
    body = kag.routes.client.post(path, json=payload).json()
    assert body["reason"] == "issuer_address_restricted"
    kag.routes.rpc["eth_estimate_gas_at_url"].assert_not_called()


def test_encrypted_draft_signature_replay_and_fresh_issuer_restriction(kag):
    fixture, response = create(kag)
    assert response.json()["status"] == "draft_ready", response.text
    draft_id = response.json()["draftId"]
    row = kag.routes.state.store._drafts[draft_id]
    assert row["asset"] is None and row["sender_address_lower"] is None and row["data_hex"] is None
    assert len(row["kag_intent_commitment"]) == 32 and row.get("paxg_intent_commitment") is None
    payload = dict(signedTransaction=fixture["signed_tx_hex"], draftId=draft_id, idempotencyKey="kag-synthetic-replay-01")
    claim = Mock(wraps=kag.routes.state.store.claim_draft)
    kag.routes.state.store.claim_draft = claim
    for other in ("ETH", "PAXG_ERC20"):
        result = kag.routes.client.post(PATH.replace(ASSET, other) + "/send/broadcast", json=payload)
        assert result.status_code == 400 and result.json()["detail"]["wallet_engine"] == "draft_asset_mismatch"
    claim.assert_not_called()
    kag.state.denied.add(DEST.lower())
    denied = kag.routes.client.post(PATH + "/send/broadcast", json=payload).json()
    assert denied["reason"] == "issuer_address_restricted"
    claim.assert_not_called()
    kag.routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()
    kag.state.denied.clear()
    kag.routes.rpc["eth_send_raw_transaction_at_url"].side_effect = None
    kag.routes.rpc["eth_send_raw_transaction_at_url"].return_value = fixture["local_tx_hash"]
    kag.routes.rpc["eth_get_transaction_by_hash_at_url"].side_effect = None
    kag.routes.rpc["eth_get_transaction_by_hash_at_url"].return_value = {"hash": fixture["local_tx_hash"]}
    for _ in range(2):
        result = kag.routes.client.post(PATH + "/send/broadcast", json=payload)
        assert result.status_code == 200 and result.json()["status"] == "submitted", result.text
    kag.routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    assert row["asset"] is None and row["data_hex"] is None
    for other in ("ETH", "PAXG_ERC20"):
        result = kag.routes.client.post(PATH.replace(ASSET, other) + "/send/broadcast", json=payload)
        assert result.status_code == 400 and result.json()["detail"]["wallet_engine"] == "draft_asset_mismatch"


@pytest.mark.parametrize("field,value", [
    ("nonce", 8), ("gas_price", GAS_PRICE+1), ("gas_limit", GAS_LIMIT+1),
    ("value_wei", 1), ("chain_id_from_v", 11155111),
    ("to_lower", assets.PAXG_CONTRACT.lower()), ("recovered_sender_lower", FROM),
    ("data_hex", evm_rpc.encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=UNITS+1)),
])
def test_complete_signed_tuple_bound_to_kag(field, value):
    fixture = signed()
    draft = dict(draft_id="kag-random-test-draft", vault_id=VAULT, network_id=NETWORK, asset=ASSET,
                 kag_ciphertext_bound=True, nonce=7, gas_limit=GAS_LIMIT, gas_price=GAS_PRICE, chain_id=1)
    draft["kag_intent_commitment"] = kag_intent_commitment(
        draft_id=draft["draft_id"], vault_id=VAULT, network_id=NETWORK, asset=ASSET,
        sender_address=fixture["sender_address"], destination_address=DEST, value_wei=0,
        data_hex=fixture["data_hex"], nonce=7, gas_limit=GAS_LIMIT, gas_price=GAS_PRICE,
        chain_id=1, transaction_to=CONTRACT)
    decoded = decode_and_recover(fixture["signed_tx_hex"])
    hydrated = bind_decoded_kag_draft(draft, decoded)
    assert verify_signed_tx_against_draft(raw_signed_tx_hex=fixture["signed_tx_hex"], draft=hydrated).ok
    with pytest.raises(ValueError, match="binding_failed"):
        bind_decoded_kag_draft(draft, replace(decoded, **{field: value}))


@pytest.mark.parametrize("body", [
    {"status": "0", "message": "NOTOK", "result": "Invalid API Key synthetic-secret"},
    {"status": "1", "message": "OK", "result": [{**_indexer_row(contract=CONTRACT), "value": -1}]},
])
def test_kag_history_provider_failures_are_not_empty_success(kag, body):
    kag.routes.indexer.side_effect = None
    kag.routes.indexer.return_value = body
    result = kag.routes.client.get(PATH + "/transactions").json()
    assert result["transactionsStatus"] == "unavailable" and result["transactions"] == []
    assert "synthetic-secret" not in str(result)


def test_kag_real_empty_and_exact_token_history(kag):
    kag.routes.indexer.side_effect = None
    kag.routes.indexer.return_value = {"status": "0", "message": "No transactions found", "result": []}
    assert kag.routes.client.get(PATH + "/transactions").json()["transactionsStatus"] == "available"
    kag.routes.indexer.return_value = {"status": "1", "message": "OK", "result": [_indexer_row(contract=CONTRACT)]}
    body = kag.routes.client.get(PATH + "/transactions").json()
    assert body["transactions"][0]["asset"] == ASSET and body["transactions"][0]["amount"] == AMOUNT


@pytest.mark.parametrize("overrides", [
    {"nonce": 8}, {"gas_price": GAS_PRICE+1}, {"gas_limit": GAS_LIMIT+1}, {"chain_id": 11155111},
    {"value_wei": 1}, {"to_addr": assets.PAXG_CONTRACT}, {"priv_key_hex": "0x"+"45"*32},
    {"data": bytes.fromhex(evm_rpc.encode_erc20_transfer_calldata(destination_address=DEST, amount_base_units=UNITS+1)[2:])},
])
def test_actual_altered_signature_rejected_before_claim(kag, overrides):
    _, response = create(kag)
    draft_id = response.json()["draftId"]
    claim = Mock(wraps=kag.routes.state.store.claim_draft)
    kag.routes.state.store.claim_draft = claim
    fixture = signed(**overrides)
    result = kag.routes.client.post(PATH + "/send/broadcast", json=dict(
        signedTransaction=fixture["signed_tx_hex"], draftId=draft_id))
    assert result.status_code == 400 and result.json()["detail"]["wallet_engine"] == "kag_encrypted_draft_binding_failed"
    claim.assert_not_called()
    kag.routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("draft_id", "another-draft"), ("vault_id", "another-vault"),
    ("network_id", "ethereum_sepolia"), ("asset", assets.PAXG_ASSET),
    ("kag_intent_commitment", b"x"*32),
])
def test_bound_identity_cannot_be_reassigned(kag, field, value):
    fixture, response = create(kag)
    draft, error = kag.routes.state.store.load_draft_readonly(
        draft_id=response.json()["draftId"], vault_id=VAULT, network_id=NETWORK)
    assert error is None
    with pytest.raises(ValueError, match="binding_failed"):
        bind_decoded_kag_draft({**draft, field: value}, decode_and_recover(fixture["signed_tx_hex"]))


@pytest.mark.parametrize("bad", [None, b"", b"x"*31, b"x"*33, "x"*32])
def test_missing_binding_fails_closed(kag, bad):
    fixture, response = create(kag)
    draft, error = kag.routes.state.store.load_draft_readonly(
        draft_id=response.json()["draftId"], vault_id=VAULT, network_id=NETWORK)
    assert error is None
    with pytest.raises(ValueError, match="binding_missing"):
        bind_decoded_kag_draft({**draft, "kag_intent_commitment": bad}, decode_and_recover(fixture["signed_tx_hex"]))


def test_registry_pause_and_post_draft_upgrade_never_claim(kag):
    fixture, response = create(kag)
    draft_id = response.json()["draftId"]
    claim = Mock(wraps=kag.routes.state.store.claim_draft)
    kag.routes.state.store.claim_draft = claim
    kag.state.registry_paused = True
    assert kag.routes.client.post(PATH + "/send/broadcast", json=dict(
        signedTransaction=fixture["signed_tx_hex"], draftId=draft_id)).json()["reason"] == "issuer_paused"
    kag.state.registry_paused = False
    kag.state.change = "0x"+"ef"*20
    assert kag.routes.client.post(PATH + "/send/broadcast", json=dict(
        signedTransaction=fixture["signed_tx_hex"], draftId=draft_id)).json()["reason"] == "issuer_implementation_changed"
    claim.assert_not_called()
    kag.routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


@pytest.mark.parametrize("condition", ["paused", "upgrade", "disabled", "missing_rpc", "network_disabled", "engine_disabled", "global_paused"])
@pytest.mark.parametrize("outcome", ["submitted", "submission_uncertain"])
@pytest.mark.parametrize("cached", [True, False])
def test_exact_previous_outcome_survives_new_restrictions_and_unsigned_ttl(kag, monkeypatch, condition, outcome, cached):
    import time
    fixture, response = create(kag)
    draft_id = response.json()["draftId"]
    raw = kag.routes.rpc["eth_send_raw_transaction_at_url"]
    raw.side_effect = evm_rpc.EvmRpcError("upstream_timeout") if outcome == "submission_uncertain" else None
    raw.return_value = fixture["local_tx_hash"]
    kag.routes.rpc["eth_get_transaction_by_hash_at_url"].side_effect = None
    kag.routes.rpc["eth_get_transaction_by_hash_at_url"].return_value = {"hash": fixture["local_tx_hash"]}
    payload = dict(signedTransaction=fixture["signed_tx_hex"], draftId=draft_id, idempotencyKey="kag-persisted-proof-01")
    first = kag.routes.client.post(PATH + "/send/broadcast", json=payload)
    assert first.status_code == 200 and first.json()["status"] == outcome, first.text
    row = kag.routes.state.store._drafts[draft_id]
    row["expires_at"] = time.time()-600
    claim = Mock(wraps=kag.routes.state.store.claim_draft)
    kag.routes.state.store.claim_draft = claim
    kag.probe.reset_mock()
    if condition == "paused":
        kag.state.paused = True
    elif condition == "upgrade":
        kag.state.change = "0x"+"ef"*20
    elif condition == "disabled":
        monkeypatch.setenv("VAULTAI_ASSETS_KAG_ENABLED", "false")
    elif condition == "missing_rpc":
        monkeypatch.delenv("ETHEREUM_MAINNET_RPC_URL")
    elif condition == "network_disabled":
        monkeypatch.setenv("VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED", "false")
    elif condition == "engine_disabled":
        monkeypatch.setenv("VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED", "false")
        import vault_config
        vault_config.reset_for_tests()
    else:
        monkeypatch.setenv("VAULTAI_CRYPTO_MAINNET_SEND_PAUSED", "true")
    if not cached:
        payload.pop("idempotencyKey")
    replay = kag.routes.client.post(PATH + "/send/broadcast", json=payload)
    assert replay.status_code == 200, replay.text
    expected = "already_submitted" if outcome == "submitted" and not cached else outcome
    assert replay.json()["status"] == expected and replay.json()["txHash"] == fixture["local_tx_hash"]
    claim.assert_not_called()
    kag.probe.assert_not_called()
    raw.assert_called_once()


def test_expired_unsigned_kag_is_not_a_replay(kag):
    import time
    fixture, response = create(kag)
    draft_id = response.json()["draftId"]
    kag.routes.state.store._drafts[draft_id]["expires_at"] = time.time()-600
    result = kag.routes.client.post(PATH + "/send/broadcast", json=dict(signedTransaction=fixture["signed_tx_hex"], draftId=draft_id))
    assert result.status_code == 400 and result.json()["detail"]["wallet_engine"] == "unknown_or_expired_draft"
    kag.routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()
