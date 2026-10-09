"""Opt-in real, migrated PostgreSQL tests with synthetic transactions only.

Requires VAULTAI_PAXG_TEST_DATABASE_URL to point to the exact disposable QA DB.
Every connection checks DB/user/loopback/port and migration head before writes.
There is no migration execution here, no real RPC, no account creation, and
cleanup deletes only this fixture's random vault-tagged drafts and wallet lock.
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest

import crypto_mainnet_control_store as real_store
from crypto_entitlement import require_crypto_entitlement
from device_gate import verify_trusted_device
from routes import crypto_wallet_routes as wallet_routes
from test_paxg_encrypted_draft_2026_10_09 import AMOUNT, CT, LOOKUP, UNITS, signed
from test_verified_assets_2026_10_09 import ASSET, CONTRACT, DEST, NETWORK, ROOT_PATH, enabled, routes

_DSN = os.getenv("VAULTAI_PAXG_TEST_DATABASE_URL", "")
_IDENTITY = ("svaultai_paxg_transaction_qa", "svaultai_concierge_tests", "127.0.0.1", 55438)
pytestmark = pytest.mark.skipif(not _DSN, reason="Explicit isolated PAXG PostgreSQL DSN not supplied")


@pytest.fixture
def pg(routes, monkeypatch):
    parsed = urlparse(_DSN)
    if (parsed.scheme not in ("postgresql", "postgres") or parsed.hostname != "127.0.0.1"
            or parsed.port != 55438 or parsed.path != "/svaultai_paxg_transaction_qa"
            or parsed.username != "svaultai_concierge_tests"):
        pytest.fail("Refusing any non-isolated PAXG test database")
    vault = "paxg-qa-fixture-" + uuid4().hex
    fixture = signed(priv_key_hex="0x" + hashlib.sha256(vault.encode()).hexdigest())
    routes.record["publicAddress"] = fixture["sender_address"]
    routes.loader.side_effect = lambda supplied_vault, service: routes.record if supplied_vault == vault and service == f"ETH:{NETWORK}" else None
    routes.app.dependency_overrides[verify_trusted_device] = lambda: {"vault_id": vault}
    routes.app.dependency_overrides[require_crypto_entitlement] = lambda: {"vault_id": vault}

    def connect():
        conn = psycopg2.connect(_DSN)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()")
                assert cur.fetchone() == _IDENTITY
                cur.execute("SELECT version_num FROM alembic_version")
                assert cur.fetchone() == ("0049_kag_encrypted_draft_binding",)
            conn.commit()
            return conn
        except Exception:
            conn.close()
            raise

    probe = connect()
    probe.close()
    monkeypatch.setattr(real_store, "get_db", connect)
    monkeypatch.setattr(wallet_routes, "_mainnet_store", real_store)
    routes.rpc["eth_send_raw_transaction_at_url"].side_effect = None
    routes.rpc["eth_send_raw_transaction_at_url"].return_value = fixture["local_tx_hash"]
    routes.rpc["eth_get_transaction_by_hash_at_url"].side_effect = None
    routes.rpc["eth_get_transaction_by_hash_at_url"].return_value = {"hash": fixture["local_tx_hash"]}
    routes.rpc["eth_get_transaction_receipt_at_url"].side_effect = None
    routes.rpc["eth_get_transaction_receipt_at_url"].return_value = None
    try:
        yield routes, connect, vault, fixture
    finally:
        # Narrow fixture-only cleanup, rechecked through the same identity guard.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM crypto_mainnet_drafts WHERE vault_id=%s", (vault,))
                cur.execute("DELETE FROM crypto_mainnet_wallet_locks WHERE network_id=%s AND sender_address_lower=%s",
                            (NETWORK, fixture["sender_address"].lower()))


def create(pg):
    routes, _, _, fixture = pg
    result = routes.client.post(ROOT_PATH + "/send/draft", json={
        "fromAddress": fixture["sender_address"], "destinationAddress": DEST, "amountEth": AMOUNT,
        "draftPayloadCiphertext": CT, "senderAddressLookupHash": LOOKUP})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "draft_ready", result.text
    return result.json()["draftId"]


def post(pg, draft_id, *, raw=None, asset=ASSET, key=None):
    routes, _, _, fixture = pg
    payload = {"signedTransaction": raw or fixture["signed_tx_hex"], "draftId": draft_id}
    if key:
        payload["idempotencyKey"] = key
    return routes.client.post(f"/crypto/wallet/network/{NETWORK}/{asset}/send/broadcast", json=payload)


def row(pg, draft_id):
    _, connect, _, _ = pg
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT sender_address_lower,asset,destination_address,value_wei_str,
                 data_hex,transaction_to,draft_payload_ciphertext,paxg_intent_commitment,
                 consumed_at,broadcast_outcome FROM crypto_mainnet_drafts WHERE draft_id=%s""", (draft_id,))
            return cur.fetchone()


def test_migrated_encrypted_create_load_signed_broadcast_replay_and_receipt(pg):
    routes, _, vault, fixture = pg
    draft_id = create(pg)
    before = row(pg, draft_id)
    assert before[:6] == (None,) * 6
    assert len(bytes(before[7])) == 32
    loaded, error = real_store.load_draft_readonly(draft_id=draft_id, vault_id=vault, network_id=NETWORK)
    assert error is None and loaded["paxg_ciphertext_bound"]
    first = post(pg, draft_id, key="pg-paxg-native-binding-01")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "submitted"
    for key in ("pg-paxg-native-binding-01", "pg-paxg-native-binding-02"):
        replay = post(pg, draft_id, key=key)
        assert replay.status_code == 200, replay.text
        assert replay.json()["txHash"] == fixture["local_tx_hash"]
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    after = row(pg, draft_id)
    assert after[:6] == (None,) * 6
    assert bytes(after[6]) == bytes(before[6]) and bytes(after[7]) == bytes(before[7])
    assert after[8] is not None and after[9] == "submitted"
    status_path = ROOT_PATH + "/transaction/" + fixture["local_tx_hash"]
    assert routes.client.get(status_path).json()["status"] == "pending"
    routes.rpc["eth_get_transaction_receipt_at_url"].return_value = {"status": "0x1", "blockNumber": "0x123"}
    assert routes.client.get(status_path).json()["status"] == "confirmed"
    routes.rpc["eth_get_transaction_receipt_at_url"].return_value = {"status": "0x0", "blockNumber": "0x123"}
    assert routes.client.get(status_path).json()["status"] == "failed"


def test_real_pg_unbound_existing_ct_row_fails_without_cast_or_consume(pg):
    _, connect, vault, _ = pg
    draft_id = create(pg)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crypto_mainnet_drafts SET paxg_intent_commitment=NULL WHERE draft_id=%s", (draft_id,))
    loaded, error = real_store.load_draft_readonly(draft_id=draft_id, vault_id=vault, network_id=NETWORK)
    assert loaded is None and error == "paxg_encrypted_draft_binding_missing"
    result = post(pg, draft_id)
    assert result.status_code == 400 and row(pg, draft_id)[8] is None
    pg[0].rpc["eth_send_raw_transaction_at_url"].assert_not_called()


@pytest.mark.parametrize("bad_binding", [b"x" * 31, b"x" * 33])
def test_real_pg_binding_constraint_rejects_bad_length_without_changing_ciphertext(pg, bad_binding):
    _, connect, _, _ = pg
    draft_id = create(pg)
    before = row(pg, draft_id)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE crypto_mainnet_drafts SET paxg_intent_commitment=%s WHERE draft_id=%s", (bad_binding, draft_id))
    assert row(pg, draft_id) == before


def test_real_pg_tampered_digest_rejects_before_state_change(pg):
    routes, connect, _, _ = pg
    draft_id = create(pg)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crypto_mainnet_drafts SET paxg_intent_commitment=%s WHERE draft_id=%s", (b"x" * 32, draft_id))
    result = post(pg, draft_id)
    assert result.status_code == 400, result.text
    assert row(pg, draft_id)[8] is None
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


def test_real_pg_cross_asset_replay_and_expired_binding_never_relay(pg):
    routes, connect, _, _ = pg
    draft_id = create(pg)
    assert post(pg, draft_id, asset="ETH").status_code == 400
    assert post(pg, draft_id, key="pg-cross-asset-proof-01").status_code == 200
    for asset in ("ETH", "USDT_ERC20", "USDC_ERC20"):
        assert post(pg, draft_id, asset=asset, key="pg-cross-asset-proof-01").status_code == 400
        assert post(pg, draft_id, asset=asset).status_code == 400
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crypto_mainnet_drafts SET expires_at=NOW() WHERE draft_id=%s", (draft_id,))
    replay = post(pg, draft_id)
    assert replay.status_code == 200 and replay.json()["status"] == "already_submitted"
    assert replay.json()["txHash"] == pg[3]["local_tx_hash"]
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()


def test_real_pg_expired_unsigned_paxg_never_becomes_replay(pg):
    routes, connect, _, _ = pg
    draft_id = create(pg)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crypto_mainnet_drafts SET expires_at=NOW() WHERE draft_id=%s", (draft_id,))
    assert post(pg, draft_id).status_code == 400
    routes.rpc["eth_send_raw_transaction_at_url"].assert_not_called()


def test_real_pg_two_workers_can_only_claim_and_relay_once(pg):
    routes, _, _, _ = pg
    draft_id = create(pg)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _i: post(pg, draft_id), [1, 2]))
    assert all(result.status_code in (200, 400, 409) for result in results)
    assert any(result.status_code == 200 for result in results)
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    assert row(pg, draft_id)[9] == "submitted"


def test_real_pg_plaintext_legacy_draft_load_unchanged(pg):
    _, _, vault, fixture = pg
    draft_id = real_store.register_draft(
        vault_id=vault, network_id=NETWORK, sender_address=fixture["sender_address"],
        asset="ETH", destination_address=DEST, value_wei=123, data_hex="0x",
        nonce=7, gas_limit=21000, gas_price=10**9, chain_id=1, transaction_to=DEST)
    loaded, error = real_store.load_draft_readonly(draft_id=draft_id, vault_id=vault, network_id=NETWORK)
    assert error is None
    assert loaded["asset"] == "ETH" and loaded["value_wei"] == 123
    assert loaded["sender_address"] == fixture["sender_address"]
    assert loaded["data_hex"] == "0x" and "paxg_ciphertext_bound" not in loaded


def test_real_pg_bound_ct_does_not_break_or_fabricate_plaintext_outgoing_history(pg):
    routes, _, vault, fixture = pg
    bound_id = create(pg)
    assert post(pg, bound_id).status_code == 200
    legacy_id = real_store.register_draft(
        vault_id=vault, network_id=NETWORK, sender_address="0x" + "33" * 20,
        asset="ETH", destination_address=DEST, value_wei=321, data_hex="0x",
        nonce=8, gas_limit=21000, gas_price=10**9, chain_id=1, transaction_to=DEST)
    claim, error = real_store.claim_draft(draft_id=legacy_id, vault_id=vault, network_id=NETWORK)
    assert error is None
    assert real_store.consume_claimed_draft(draft_id=legacy_id, claim_token=claim,
                                          local_tx_hash="0x" + "55" * 32)
    assert real_store.record_broadcast_outcome(draft_id=legacy_id, claim_token=claim, outcome="submitted")
    history = real_store.list_outgoing_history(vault_id=vault, network_id=NETWORK)
    assert len(history) == 1 and history[0]["draft_id"] == legacy_id and history[0]["value_wei"] == 321
    response = routes.client.get(f"/crypto/wallet/network/{NETWORK}/outgoing/history")
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert len(response.json()["outgoing"]) == 1
    assert response.json()["outgoing"][0]["asset"] == "ETH"
    assert row(pg, bound_id)[:6] == (None,) * 6
