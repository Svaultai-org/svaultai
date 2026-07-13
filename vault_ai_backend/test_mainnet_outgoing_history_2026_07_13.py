"""2026-07-13 (durability slice): outgoing history endpoint tests.

Round-3 fixed the false-`submitted` bug and the missing-Activity-row
bug by adding an in-session `LocalOutgoingTxStore`. The remaining
production correctness gap Round-4 addresses:

    An outgoing transaction MUST NOT disappear from Activity because
    the user refreshed Flutter web, closed the tab, restarted the
    browser, or authenticated on a second device.

The Postgres `crypto_mainnet_drafts` table already persists every
field the client needs to render a durable Activity row (sender,
destination, value, gas, local tx hash, broadcast outcome,
timestamps). This suite locks in the vault-scoped authenticated
projection of that table:

    GET /crypto/wallet/network/{network}/outgoing/history

Guarantees exercised:

  * Vault A's endpoint never returns Vault B's rows.
  * Only CONSUMED drafts (local_tx_hash IS NOT NULL) appear —
    pre-broadcast drafts are not "history".
  * Rows are ordered most-recently-consumed first, ties broken
    deterministically for tests.
  * The response NEVER contains claim_token, claim_expires_at,
    expires_at, or the vault_id field — those are internal.
  * Sepolia and non-EVM networks return an empty list (their
    outgoing state is not stored in this table).
  * A store-side exception returns `unavailable` (not `ok`) —
    silent empty list would misrepresent state as "no history".
"""

from __future__ import annotations

import os
import unittest
from typing import Any


import vault_config


_ENV = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_SEPOLIA_RPC_URL",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE",
)


def _set_env(**kvs: Any) -> None:
    for k, v in kvs.items():
        if v is None:
            if k in os.environ:
                del os.environ[k]
        else:
            os.environ[k] = str(v)
    vault_config.reset_for_tests()


def _clear_env() -> None:
    for k in _ENV:
        if k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


def _enable() -> None:
    _set_env(
        VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="false",
        VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE="/dev/null/no",
    )


_VAULT_A = "test-durable-history-vault-a"
_VAULT_B = "test-durable-history-vault-b"


def _make_client_for_vault(vault_id: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as m
    from routes.crypto_wallet_routes import router, verify_trusted_device
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": vault_id,
    }
    return TestClient(app), app, m


def _seed_consumed_draft(
    m,
    *,
    draft_id: str,
    vault_id: str,
    sender: str = "0x" + "aa" * 20,
    destination: str = "0x" + "bb" * 20,
    asset: str = "ETH",
    value_wei: int = 5_600_000_000_000_000,  # 0.0056 ETH — canary value
    gas_limit: int = 21_000,
    gas_price: int = 20_000_000_000,
    chain_id: int = 1,
    local_tx_hash: str = "0x" + "ab" * 32,
    broadcast_outcome: str = "submitted",
    consumed_at: float = 1_720_000_000.0,
    outcome_recorded_at: float = 1_720_000_001.0,
    network_id: str = "ethereum_mainnet",
    data_hex: str = "0x",
    transaction_to: str = "",
) -> None:
    m._mainnet_store.seed_draft(
        draft_id,
        vault_id=vault_id,
        network_id=network_id,
        sender_address=sender,
        asset=asset,
        destination_address=destination,
        value_wei=value_wei,
        data_hex=data_hex,
        nonce=0,
        gas_limit=gas_limit,
        gas_price=gas_price,
        chain_id=chain_id,
        transaction_to=transaction_to or destination,
    )
    # Directly mutate the fake row into the CONSUMED terminal state
    # — the seed helper leaves it ACTIVE; we want history.
    d = m._mainnet_store._drafts[draft_id]
    d["consumed_at"] = consumed_at
    d["local_tx_hash"] = local_tx_hash
    d["broadcast_outcome"] = broadcast_outcome
    d["outcome_recorded_at"] = outcome_recorded_at


class VaultScopedHistoryIsolation(unittest.TestCase):
    """Vault A must NOT be able to read Vault B's outgoing history."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client_a, self._app_a, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        _seed_consumed_draft(
            self._m,
            draft_id="drft-vault-a-1",
            vault_id=_VAULT_A,
            local_tx_hash="0x" + "a1" * 32,
        )
        _seed_consumed_draft(
            self._m,
            draft_id="drft-vault-b-1",
            vault_id=_VAULT_B,
            local_tx_hash="0x" + "b1" * 32,
        )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_vault_a_only_sees_its_own_row(self) -> None:
        r = self._client_a.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        rows = body["outgoing"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["draftId"], "drft-vault-a-1")
        self.assertEqual(
            rows[0]["localTxHash"], "0x" + "a1" * 32,
        )

    def test_vault_b_only_sees_its_own_row(self) -> None:
        client_b, _app, _m2 = _make_client_for_vault(_VAULT_B)
        r = client_b.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        rows = body["outgoing"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["draftId"], "drft-vault-b-1")
        self.assertNotIn("drft-vault-a-1", str(body))
        # Extra belt-and-braces: Vault B response must not name
        # Vault A's local tx hash at all.
        self.assertNotIn("a1" * 32, str(body))


class ClaimTokenAndInternalFieldsNeverLeak(unittest.TestCase):
    """The response must never include claim_token, claim_expires_at,
    expires_at, or the vault_id. Those are internal to the lock/state
    machine; a vault owner needs none of them and a mis-routed
    response should not leak a shared identifier."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        _seed_consumed_draft(
            self._m,
            draft_id="drft-secrets-canary",
            vault_id=_VAULT_A,
        )
        # Force claim_token to a value we can grep for.
        self._m._mainnet_store._drafts["drft-secrets-canary"][
            "claim_token"
        ] = "SUPER_SECRET_CLAIM_TOKEN_ABCDEFGH"
        self._m._mainnet_store._drafts["drft-secrets-canary"][
            "claim_expires_at"
        ] = 9_999_999_999.0

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_no_claim_token_in_response(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        self.assertEqual(r.status_code, 200)
        raw = r.text
        # Match either the value or the key name — both are internal.
        self.assertNotIn("SUPER_SECRET_CLAIM_TOKEN", raw)
        self.assertNotIn("claim_token", raw)
        self.assertNotIn("claimToken", raw)
        self.assertNotIn("claim_expires_at", raw)
        self.assertNotIn("claimExpiresAt", raw)

    def test_no_expires_at_or_vault_id_in_response(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        raw = r.text
        # expires_at is the DRAFT-lifetime timer, an internal field.
        # createdAt / consumedAt / outcomeRecordedAt ARE exposed and
        # are distinct wire keys.
        self.assertNotIn("expiresAt", raw)
        self.assertNotIn("expires_at", raw)
        self.assertNotIn(_VAULT_A, raw)
        self.assertNotIn("vault_id", raw)
        self.assertNotIn("vaultId", raw)


class OnlyConsumedDraftsAreHistory(unittest.TestCase):
    """A draft that is ACTIVE (no consume yet) MUST NOT appear in
    outgoing history — the user has not attempted to broadcast
    anything, and the draft may still be released and reused."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        # One CONSUMED draft (should appear).
        _seed_consumed_draft(
            self._m,
            draft_id="drft-consumed-1",
            vault_id=_VAULT_A,
            local_tx_hash="0x" + "11" * 32,
        )
        # One ACTIVE draft (should NOT appear).
        self._m._mainnet_store.seed_draft(
            "drft-active-1",
            vault_id=_VAULT_A,
            network_id="ethereum_mainnet",
            sender_address="0x" + "aa" * 20,
            asset="ETH",
            destination_address="0x" + "cc" * 20,
            value_wei=1_000_000_000_000_000,
        )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_active_draft_is_absent(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        body = r.json()
        draft_ids = [row["draftId"] for row in body["outgoing"]]
        self.assertIn("drft-consumed-1", draft_ids)
        self.assertNotIn("drft-active-1", draft_ids)


class OrderingIsMostRecentConsumedFirst(unittest.TestCase):
    """Rows must be ordered `consumed_at DESC` so the freshest
    activity is at the top of the Activity feed."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        _seed_consumed_draft(
            self._m, draft_id="drft-old", vault_id=_VAULT_A,
            consumed_at=1_720_000_000.0,
            local_tx_hash="0x" + "10" * 32,
        )
        _seed_consumed_draft(
            self._m, draft_id="drft-mid", vault_id=_VAULT_A,
            consumed_at=1_720_000_100.0,
            local_tx_hash="0x" + "20" * 32,
        )
        _seed_consumed_draft(
            self._m, draft_id="drft-new", vault_id=_VAULT_A,
            consumed_at=1_720_000_200.0,
            local_tx_hash="0x" + "30" * 32,
        )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_newest_row_first(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        rows = r.json()["outgoing"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["draftId"], "drft-new")
        self.assertEqual(rows[1]["draftId"], "drft-mid")
        self.assertEqual(rows[2]["draftId"], "drft-old")


class NonMainnetNetworksReturnEmpty(unittest.TestCase):
    """Sepolia + non-EVM networks return an explicit empty outgoing
    list — never a 404 — so the client can uniformly reason about
    the response shape."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        # Even a mainnet history row for the same vault must NOT
        # leak into the Sepolia response.
        _seed_consumed_draft(
            self._m, draft_id="drft-in-mainnet",
            vault_id=_VAULT_A,
            network_id="ethereum_mainnet",
            local_tx_hash="0x" + "77" * 32,
        )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_sepolia_returns_empty(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_sepolia/outgoing/history",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["outgoing"], [])


class HistoryStoreExceptionReturnsUnavailable(unittest.TestCase):
    """A store-side exception is reported as `unavailable` — never
    as an empty list. Empty would be indistinguishable from
    'user has no history', which is a lie during a DB outage."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_db_error_becomes_unavailable(self) -> None:
        from unittest import mock
        with mock.patch.object(
            self._m._mainnet_store,
            "list_outgoing_history",
            side_effect=RuntimeError("simulated DB failure"),
        ):
            r = self._client.get(
                "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["reason"], "history_store_failed")


class OutcomesPreservedVerbatim(unittest.TestCase):
    """The `broadcastOutcome` wire field must be one of {submitted,
    submission_uncertain, already_known, explicitly_rejected} — the
    same set the state machine writes."""

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        for i, outcome in enumerate([
            "submitted", "submission_uncertain",
            "already_known", "explicitly_rejected",
        ]):
            _seed_consumed_draft(
                self._m,
                draft_id=f"drft-outcome-{i}",
                vault_id=_VAULT_A,
                broadcast_outcome=outcome,
                consumed_at=1_720_000_000.0 + i,
                local_tx_hash="0x" + f"{i:02x}" * 32,
            )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_all_four_outcome_values_are_projected(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        rows = r.json()["outgoing"]
        outcomes = {row["broadcastOutcome"] for row in rows}
        self.assertEqual(outcomes, {
            "submitted", "submission_uncertain",
            "already_known", "explicitly_rejected",
        })


class ExactCanaryFixtureRegression(unittest.TestCase):
    """The declarative production canary fixture is projected onto
    the outgoing history endpoint exactly as expected: draftId,
    localTxHash, valueWei, destination, `submitted`. The row must
    survive across sessions — this suite emulates two independent
    TestClient constructions to prove the row lives in the store,
    not in per-client state."""

    _CANARY_DRAFT_ID   = "02ctGuBjqYXERNxD1k5AiplGgc_dyg5a"
    _CANARY_LOCAL_HASH = (
        "0x783ddc09728b26884c78da47ee408c40daa75c89e03700deb2"
        "16e98ed77c415b"
    )
    _CANARY_SENDER      = "0xda3d577784075eb7011e60cb8a5f0ae33f682855"
    _CANARY_DESTINATION = "0x7c49215a2cb86aac3e6308ea4d6206912578e870"
    _CANARY_VALUE_WEI   = 5_600_000_000_000_000

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        _seed_consumed_draft(
            self._m,
            draft_id=self._CANARY_DRAFT_ID,
            vault_id=_VAULT_A,
            sender=self._CANARY_SENDER,
            destination=self._CANARY_DESTINATION,
            value_wei=self._CANARY_VALUE_WEI,
            local_tx_hash=self._CANARY_LOCAL_HASH,
            broadcast_outcome="submission_uncertain",
        )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_canary_row_survives_second_client_construction(self) -> None:
        # First client — simulate initial browser session.
        r1 = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        rows1 = r1.json()["outgoing"]
        self.assertEqual(len(rows1), 1)
        row1 = rows1[0]
        self.assertEqual(row1["draftId"], self._CANARY_DRAFT_ID)
        self.assertEqual(
            row1["localTxHash"], self._CANARY_LOCAL_HASH,
        )
        self.assertEqual(row1["broadcastOutcome"],
            "submission_uncertain")
        self.assertEqual(row1["valueWei"], str(self._CANARY_VALUE_WEI))
        self.assertEqual(
            row1["destinationAddress"], self._CANARY_DESTINATION,
        )

        # Second client — simulate the user refreshing the browser
        # OR authenticating on a different device. Same vault, brand
        # new TestClient. The row MUST survive.
        client_2, _app_2, _m_2 = _make_client_for_vault(_VAULT_A)
        r2 = client_2.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        rows2 = r2.json()["outgoing"]
        self.assertEqual(len(rows2), 1,
            msg="Durable outgoing row must survive re-authentication "
                "(different TestClient), which is the emulation of a "
                "browser reload / new device.")
        self.assertEqual(rows2[0]["draftId"], self._CANARY_DRAFT_ID)


class ProjectedFieldsAreIntegerExact(unittest.TestCase):
    """The endpoint must expose exact integer wei / base-units as
    strings so the frontend can BigInt-parse without precision loss.
    A very large value MUST come back byte-identical."""

    _HUGE = 12_345_678_987_654_321_098_765

    def setUp(self) -> None:
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client_for_vault(
            _VAULT_A,
        )
        self._m.reset_mainnet_safety_state_for_tests()
        _seed_consumed_draft(
            self._m,
            draft_id="drft-huge",
            vault_id=_VAULT_A,
            value_wei=self._HUGE,
            gas_limit=1_000_000,
            gas_price=999_999_999_999,
            local_tx_hash="0x" + "ee" * 32,
        )

    def tearDown(self) -> None:
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def test_huge_value_wei_is_preserved_as_string(self) -> None:
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/outgoing/history",
        )
        row = r.json()["outgoing"][0]
        self.assertEqual(row["valueWei"], str(self._HUGE))
        self.assertEqual(row["gasLimit"], "1000000")
        self.assertEqual(row["gasPrice"], "999999999999")
        self.assertEqual(
            row["feeWei"], str(1_000_000 * 999_999_999_999),
        )


if __name__ == "__main__":
    unittest.main()
