"""Opt-in migrated PostgreSQL KAG fixture; exact disposable DB guard reused.

No production data, real wallet secret, network relay, or migration execution.
Cleanup is restricted to random tagged fixture rows by the shared PG fixture.
"""
import hashlib
import os

import psycopg2
import pytest

import crypto_mainnet_control_store as store
from test_paxg_encrypted_draft_postgres_2026_10_09 import pg
from test_kag_registered_asset_2026_10_09 import kag, enabled, routes, signed, PATH, CT, LOOKUP, AMOUNT, DEST, NETWORK

pytestmark = pytest.mark.skipif(not os.getenv("VAULTAI_PAXG_TEST_DATABASE_URL"),
                               reason="Explicit exact isolated PostgreSQL DSN required")


def create(pg, kag):
    routes, _, vault, _ = pg
    fixture = signed(priv_key_hex="0x" + hashlib.sha256(vault.encode()).hexdigest())
    routes.record["publicAddress"] = fixture["sender_address"]
    routes.rpc["eth_send_raw_transaction_at_url"].return_value = fixture["local_tx_hash"]
    routes.rpc["eth_get_transaction_by_hash_at_url"].return_value = {"hash": fixture["local_tx_hash"]}
    response = routes.client.post(PATH + "/send/draft", json={
        "fromAddress": fixture["sender_address"], "destinationAddress": DEST, "amountEth": AMOUNT,
        "draftPayloadCiphertext": CT, "senderAddressLookupHash": LOOKUP})
    assert response.status_code == 200 and response.json()["status"] == "draft_ready", response.text
    return fixture, response.json()["draftId"]


def row(pg, draft_id):
    _, connect, _, _ = pg
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT sender_address_lower, asset, destination_address, value_wei_str,
              data_hex, transaction_to, draft_payload_ciphertext, paxg_intent_commitment,
              kag_intent_commitment, consumed_at, broadcast_outcome
              FROM crypto_mainnet_drafts WHERE draft_id=%s""", (draft_id,))
            return cur.fetchone()


def test_real_pg_kag_ciphertext_load_verified_consume_replay_and_projection(pg, kag):
    routes, _, vault, _ = pg
    fixture, draft_id = create(pg, kag)
    before = row(pg, draft_id)
    assert before[:6] == (None,)*6 and before[7] is None and len(bytes(before[8])) == 32
    loaded, error = store.load_draft_readonly(draft_id=draft_id, vault_id=vault, network_id=NETWORK)
    assert error is None and loaded["asset"] == "KAG_ERC20" and loaded["kag_ciphertext_bound"]
    payload = dict(signedTransaction=fixture["signed_tx_hex"], draftId=draft_id, idempotencyKey="pg-kag-synthetic-01")
    for other in ("ETH", "PAXG_ERC20"):
        response = routes.client.post(PATH.replace("KAG_ERC20", other) + "/send/broadcast", json=payload)
        assert response.status_code == 400 and response.json()["detail"]["wallet_engine"] == "draft_asset_mismatch"
    for _ in range(2):
        response = routes.client.post(PATH + "/send/broadcast", json=payload)
        assert response.status_code == 200 and response.json()["status"] == "submitted", response.text
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    after = row(pg, draft_id)
    assert after[:6] == (None,)*6 and bytes(after[6]) == bytes(before[6]) and bytes(after[8]) == bytes(before[8])
    assert after[9] is not None and after[10] == "submitted"
    assert store.list_outgoing_history(vault_id=vault, network_id=NETWORK) == []
    # Consumed exact outcomes survive unsigned TTL and later issuer restrictions.
    with pg[1]() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crypto_mainnet_drafts SET expires_at=NOW()-INTERVAL '10 minutes' WHERE draft_id=%s", (draft_id,))
    kag.state.paused = True
    payload.pop("idempotencyKey")
    replay = routes.client.post(PATH + "/send/broadcast", json=payload)
    assert replay.status_code == 200 and replay.json()["status"] == "already_submitted", replay.text
    assert replay.json()["txHash"] == fixture["local_tx_hash"]
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()
    altered = signed(priv_key_hex="0x" + hashlib.sha256(vault.encode()).hexdigest(), nonce=8)
    replay = routes.client.post(PATH + "/send/broadcast", json={**payload, "signedTransaction": altered["signed_tx_hex"]})
    assert replay.status_code == 400 and replay.json()["detail"]["wallet_engine"] == "kag_encrypted_draft_binding_failed"
    routes.rpc["eth_send_raw_transaction_at_url"].assert_called_once()


@pytest.mark.parametrize("bad", [b"x"*31, b"x"*33])
def test_real_pg_kag_length_constraint_and_ciphertext_unchanged(pg, kag, bad):
    _, draft_id = create(pg, kag)
    before = row(pg, draft_id)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with pg[1]() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE crypto_mainnet_drafts SET kag_intent_commitment=%s WHERE draft_id=%s", (bad, draft_id))
    after = row(pg, draft_id)
    assert bytes(after[6]) == bytes(before[6]) and bytes(after[8]) == bytes(before[8])


def test_real_pg_paxg_kag_bindings_cannot_both_exist(pg, kag):
    _, draft_id = create(pg, kag)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with pg[1]() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE crypto_mainnet_drafts SET paxg_intent_commitment=%s WHERE draft_id=%s", (b"x"*32, draft_id))


def test_real_pg_missing_kag_binding_requires_redraft_without_null_cast(pg, kag):
    fixture, draft_id = create(pg, kag)
    with pg[1]() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crypto_mainnet_drafts SET kag_intent_commitment=NULL WHERE draft_id=%s", (draft_id,))
    loaded, error = store.load_draft_readonly(draft_id=draft_id, vault_id=pg[2], network_id=NETWORK)
    assert loaded is None and error == "paxg_encrypted_draft_binding_missing"
    response = pg[0].client.post(PATH + "/send/broadcast", json=dict(signedTransaction=fixture["signed_tx_hex"], draftId=draft_id))
    assert response.status_code == 400 and row(pg, draft_id)[9] is None
    pg[0].rpc["eth_send_raw_transaction_at_url"].assert_not_called()
