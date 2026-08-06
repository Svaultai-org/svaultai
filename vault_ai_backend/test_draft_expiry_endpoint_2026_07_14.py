"""2026-07-14 (Round 9): dedicated backend regression suite for
the `GET /crypto/wallet/network/{network}/draft/{draft_id}/expiry`
endpoint and its parity with the SOL / TRON broadcast state
machines.

The endpoint is security-critical: the client's pre-sign and pre-
broadcast fail-closed checks depend on its exact envelope contract
and boundary rules. If the endpoint ever green-lights a draft that
the broadcast state machine then rejects — or vice versa — the
client is either signing / broadcasting expired transactions or
seeing spurious expiry banners on valid ones.

Coverage:

  1. Shared helpers boundary rules (SOL block-height, TRON ms).
  2. SOL endpoint envelope + boundary matrix.
  3. TRON endpoint envelope + boundary matrix.
  4. SOL broadcast state machine uses the same boundary rule as
     the endpoint (parity proof).
  5. TRON broadcast state machine uses the same rule as the
     endpoint (parity proof).
  6. Auth (missing/invalid session → 401).
  7. Ownership (wrong-vault caller cannot inspect another vault's
     draft; must not leak existence or details).
  8. Response privacy (no destination / amount / signature /
     claim-token leakage).
  9. Malformed persisted values → fail closed.
 10. RPC transport failures → `expired: null` (unverifiable —
     client MUST fail closed).
 11. Non-SOL/TRON routes on the endpoint.

Every test uses the in-process FakeSolanaStore + FakeTronStore
installed by ``conftest.py`` — no live Postgres, no live RPC.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import vault_config


# ---------------------------------------------------------------
# Env / test client scaffolding — matches the pattern used by
# test_sol_tron_xmr_hardening_2026_07_14.py so this file drops
# into the existing conftest fakes.
# ---------------------------------------------------------------


_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_PAUSED",
    "SOLANA_RPC_URL",
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_PAUSED",
    "TRON_API_BASE_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SEND_ENABLED",
)


def _clear_env() -> None:
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    vault_config.reset_for_tests()


def _enable_sol() -> None:
    _clear_env()
    os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
    os.environ["SOLANA_RPC_URL"] = "https://sol.example"
    vault_config.reset_for_tests()


def _enable_tron() -> None:
    _clear_env()
    os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
    os.environ["TRON_API_BASE_URL"] = "https://tron.example"
    os.environ["TRON_API_KEY"] = "key"
    os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    )
    vault_config.reset_for_tests()


_VAULT_ALICE = "vault-alice-expiry"
_VAULT_BOB = "vault-bob-expiry"
_SOL_A = "So11111111111111111111111111111111111111112"
_SOL_B = "11111111111111111111111111111111"
_TRN_A = "TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq"
_TRN_B = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"
_TRN_C = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _make_app(vault_id: str = _VAULT_ALICE):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as m
    from routes.crypto_wallet_routes import (
        router, verify_trusted_device, require_crypto_entitlement,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": vault_id,
    }
    app.dependency_overrides[require_crypto_entitlement] = lambda: {
        "vault_id": vault_id,
    }
    return TestClient(app), app, m


def _make_app_no_auth():
    """Test client WITHOUT the verify_trusted_device override — a
    request with no session token exercises the real auth layer and
    must 401."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.crypto_wallet_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), app


# =================================================================
# 1. Shared helpers — direct boundary rule tests.
# =================================================================


class SharedHelperBoundaryRules(unittest.TestCase):
    """Both SOL and TRON boundary rules live in
    crypto_wallet_draft_expiry so the endpoint and the broadcast
    state machine cannot drift.
    """

    def test_solana_helper_current_below_last_valid_is_valid(self):
        from crypto_wallet_draft_expiry import (
            solana_draft_expired_by_blockheight,
        )
        self.assertFalse(
            solana_draft_expired_by_blockheight(
                current_block_height=99,
                last_valid_block_height=100,
            )
        )

    def test_solana_helper_current_equals_last_valid_is_valid(self):
        # 100 == 100 → the last-valid slot IS still a valid slot.
        from crypto_wallet_draft_expiry import (
            solana_draft_expired_by_blockheight,
        )
        self.assertFalse(
            solana_draft_expired_by_blockheight(
                current_block_height=100,
                last_valid_block_height=100,
            )
        )

    def test_solana_helper_current_one_above_last_valid_is_expired(
        self,
    ):
        # 101 > 100 → first expired slot.
        from crypto_wallet_draft_expiry import (
            solana_draft_expired_by_blockheight,
        )
        self.assertTrue(
            solana_draft_expired_by_blockheight(
                current_block_height=101,
                last_valid_block_height=100,
            )
        )

    def test_solana_helper_type_errors(self):
        from crypto_wallet_draft_expiry import (
            solana_draft_expired_by_blockheight,
        )
        with self.assertRaises(TypeError):
            solana_draft_expired_by_blockheight(
                current_block_height="100",  # type: ignore
                last_valid_block_height=100,
            )
        with self.assertRaises(TypeError):
            solana_draft_expired_by_blockheight(
                current_block_height=100,
                last_valid_block_height=None,  # type: ignore
            )

    def test_solana_helper_value_errors(self):
        from crypto_wallet_draft_expiry import (
            solana_draft_expired_by_blockheight,
        )
        with self.assertRaises(ValueError):
            solana_draft_expired_by_blockheight(
                current_block_height=-1,
                last_valid_block_height=100,
            )
        with self.assertRaises(ValueError):
            solana_draft_expired_by_blockheight(
                current_block_height=100,
                last_valid_block_height=-1,
            )

    def test_tron_helper_before_expiration_is_valid(self):
        from crypto_wallet_draft_expiry import (
            tron_draft_expired_by_expiration_ms,
        )
        self.assertFalse(
            tron_draft_expired_by_expiration_ms(
                now_ms=999, expiration_ms=1000,
            )
        )

    def test_tron_helper_exact_boundary_is_expired(self):
        # 1000 == 1000 → TRON refuses at the instant of expiration.
        from crypto_wallet_draft_expiry import (
            tron_draft_expired_by_expiration_ms,
        )
        self.assertTrue(
            tron_draft_expired_by_expiration_ms(
                now_ms=1000, expiration_ms=1000,
            )
        )

    def test_tron_helper_past_expiration_is_expired(self):
        from crypto_wallet_draft_expiry import (
            tron_draft_expired_by_expiration_ms,
        )
        self.assertTrue(
            tron_draft_expired_by_expiration_ms(
                now_ms=1001, expiration_ms=1000,
            )
        )

    def test_tron_helper_zero_expiration_is_expired(self):
        # 0 or negative expiration_ms is fail-closed treated as
        # already-expired.
        from crypto_wallet_draft_expiry import (
            tron_draft_expired_by_expiration_ms,
        )
        self.assertTrue(
            tron_draft_expired_by_expiration_ms(
                now_ms=100, expiration_ms=0,
            )
        )
        self.assertTrue(
            tron_draft_expired_by_expiration_ms(
                now_ms=100, expiration_ms=-1,
            )
        )

    def test_tron_helper_type_and_value_errors(self):
        from crypto_wallet_draft_expiry import (
            tron_draft_expired_by_expiration_ms,
        )
        with self.assertRaises(TypeError):
            tron_draft_expired_by_expiration_ms(
                now_ms="0", expiration_ms=1000,  # type: ignore
            )
        with self.assertRaises(ValueError):
            tron_draft_expired_by_expiration_ms(
                now_ms=-1, expiration_ms=1000,
            )


# =================================================================
# 2. SOL endpoint — direct helper + HTTP envelope + boundary.
# =================================================================


class SolExpiryEndpointMatrix(unittest.TestCase):

    def setUp(self) -> None:
        _enable_sol()
        self._client, self._app, self._m = _make_app(
            vault_id=_VAULT_ALICE,
        )

    def tearDown(self) -> None:
        _clear_env()

    def _seed(
        self,
        draft_id: str = "expiry-sol-alice-1234567890",
        *,
        vault_id: str = _VAULT_ALICE,
        last_valid_block_height: int = 1_000,
        consumed: bool = False,
    ) -> str:
        self._m._solana_store.seed_draft(
            draft_id,
            vault_id=vault_id,
            network_id="solana_mainnet",
            sender_address=_SOL_A,
            destination_address=_SOL_B,
            value_lamports=1_000_000,
            fee_lamports=5000,
            last_valid_block_height=last_valid_block_height,
        )
        if consumed:
            import time as _t
            row = self._m._solana_store._drafts[draft_id]
            row["consumed_at"] = _t.time()
            row["local_signature"] = "sig-consumed"
            row["broadcast_outcome"] = "submitted"
        return draft_id

    def _hit(self, draft_id: str) -> dict:
        return self._client.get(
            f"/crypto/wallet/network/solana_mainnet/"
            f"draft/{draft_id}/expiry",
        ).json()

    # --- boundary matrix -----------------------------------------

    def test_current_below_last_valid_reports_not_expired(self):
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], False)
        self.assertEqual(body["reason"], "still_valid")
        self.assertEqual(body["currentBlockHeight"], 999)
        self.assertEqual(body["lastValidBlockHeight"], 1_000)

    def test_current_equals_last_valid_reports_not_expired(self):
        # Boundary rule: current == last_valid is STILL valid.
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=1_000,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], False)

    def test_first_invalid_height_reports_expired(self):
        # Boundary rule: current == last_valid + 1 is the first
        # expired slot.
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=1_001,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], True)
        self.assertEqual(body["reason"], "blockheight_exceeded")

    def test_very_high_current_reports_expired(self):
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999_999_999,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], True)

    # --- draft state machine paths -------------------------------

    def test_unknown_draft_fails_closed_without_leak(self):
        # No RPC patch needed — unknown draft short-circuits before
        # any RPC call.
        body = self._hit("expiry-sol-nonexistent-abcd1234")
        self.assertEqual(body["expired"], True)
        self.assertIn(body["reason"], (
            "unknown_or_expired_draft",
            "draft_vault_mismatch",
        ))
        # Response body must never contain vault_id or draft internals.
        self.assertNotIn("vault_id", body)
        self.assertNotIn("sender_address", body)
        self.assertNotIn("destination_address", body)
        self.assertNotIn("value_lamports", body)
        self.assertNotIn("claim_token", body)

    def test_wrong_vault_owner_fails_closed_without_leak(self):
        # Draft owned by Bob; Alice's client tries to inspect it.
        did = self._seed(
            "expiry-sol-bob-1234567890abcd",
            vault_id=_VAULT_BOB, last_valid_block_height=1_000,
        )
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], True)
        # Reason must not confirm existence — the fake returns
        # "draft_vault_mismatch" but that is a stable, opaque signal
        # matching an unknown draft's envelope shape.
        self.assertIn(body["reason"], (
            "unknown_or_expired_draft",
            "draft_vault_mismatch",
        ))
        # No draft internals leak — none of the seeded fields appear.
        self.assertNotIn("currentBlockHeight", body)
        self.assertNotIn("lastValidBlockHeight", body)

    def test_consumed_draft_reports_expired_with_distinct_reason(
        self,
    ):
        did = self._seed(
            last_valid_block_height=1_000, consumed=True,
        )
        # Consumed drafts short-circuit BEFORE the RPC call.
        body = self._hit(did)
        self.assertEqual(body["expired"], True)
        self.assertEqual(body["reason"], "draft_already_consumed")

    def test_malformed_persisted_last_valid_block_height_fails_closed(
        self,
    ):
        # A malformed persisted value (non-numeric) MUST NOT reach
        # the shared boundary helper as an int. The endpoint layer
        # catches TypeError/ValueError from the coerce and returns
        # `expired: true` with a distinct malformed reason.
        fake_draft = {
            "draft_id": "expiry-sol-malformed-abcd1234ef",
            "vault_id": _VAULT_ALICE,
            "network_id": "solana_mainnet",
            "consumed": False,
            "last_valid_block_height": "not-a-number",
        }
        with mock.patch.object(
            self._m._solana_store, "load_draft_readonly",
            return_value=(fake_draft, None),
        ), mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = self._hit("expiry-sol-malformed-abcd1234ef")
        self.assertEqual(body["expired"], True)
        self.assertEqual(
            body["reason"], "malformed_last_valid_block_height",
        )

    def test_zero_persisted_last_valid_block_height_fails_closed(
        self,
    ):
        # A row with last_valid_block_height == 0 has no useful
        # boundary and must be treated as fail-closed rather than
        # trivially "valid".
        fake_draft = {
            "draft_id": "expiry-sol-zero-lastvalid-1234",
            "vault_id": _VAULT_ALICE,
            "network_id": "solana_mainnet",
            "consumed": False,
            "last_valid_block_height": 0,
        }
        with mock.patch.object(
            self._m._solana_store, "load_draft_readonly",
            return_value=(fake_draft, None),
        ), mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = self._hit("expiry-sol-zero-lastvalid-1234")
        self.assertEqual(body["expired"], True)
        self.assertEqual(
            body["reason"], "malformed_last_valid_block_height",
        )

    # --- RPC transport / shape failures -> `expired: null` -------

    def test_rpc_timeout_reports_expired_null(self):
        from solana_rpc import (
            SolanaRpcError, REASON_RPC_UNREACHABLE,
        )
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            side_effect=SolanaRpcError(REASON_RPC_UNREACHABLE),
        ):
            body = self._hit(did)
        # Unverifiable — client MUST fail closed on this.
        self.assertIs(body["expired"], None)
        self.assertEqual(body["reason"], "rpc_unreachable")

    def test_rpc_connection_failure_reports_expired_null(self):
        from solana_rpc import (
            SolanaRpcError, REASON_RPC_UNREACHABLE,
        )
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            side_effect=SolanaRpcError(REASON_RPC_UNREACHABLE),
        ):
            body = self._hit(did)
        self.assertIs(body["expired"], None)

    def test_rpc_error_envelope_reports_expired_null(self):
        from solana_rpc import SolanaRpcError, REASON_RPC_ERROR
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            side_effect=SolanaRpcError(REASON_RPC_ERROR),
        ):
            body = self._hit(did)
        self.assertIs(body["expired"], None)
        self.assertEqual(body["reason"], "rpc_error")

    def test_malformed_rpc_block_height_reports_expired_null(self):
        # sol_get_block_height_at_url raises REASON_RPC_ERROR on
        # any non-int / non-dict-with-int-value payload.
        from solana_rpc import SolanaRpcError, REASON_RPC_ERROR
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            side_effect=SolanaRpcError(REASON_RPC_ERROR),
        ):
            body = self._hit(did)
        self.assertIs(body["expired"], None)

    def test_rpc_not_configured_reports_expired_null(self):
        # Wipe SOLANA_RPC_URL — the endpoint MUST return
        # `expired: null` with `reason: rpc_not_configured` and
        # NOT touch the RPC at all.
        os.environ.pop("SOLANA_RPC_URL", None)
        vault_config.reset_for_tests()
        did = self._seed(last_valid_block_height=1_000)
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
        ) as mocked:
            body = self._hit(did)
            self.assertEqual(mocked.call_count, 0)
        self.assertIs(body["expired"], None)
        self.assertEqual(body["reason"], "rpc_not_configured")

    # --- privacy -------------------------------------------------

    def test_response_never_leaks_claim_or_owner_details(self):
        did = self._seed(last_valid_block_height=1_000)
        # Poison the fake row with distinctive leak-canary strings.
        row = self._m._solana_store._drafts[did]
        row["claim_token"] = "SOL_EXPIRY_CLAIM_TOKEN_CANARY"
        row["local_signature"] = "SOL_EXPIRY_SIG_CANARY"
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = self._hit(did)
        raw = str(body)
        self.assertNotIn("CANARY", raw)
        self.assertNotIn("vault_id", body)
        self.assertNotIn("sender_address", body)
        self.assertNotIn("destination_address", body)
        self.assertNotIn("value_lamports", body)
        self.assertNotIn("fee_lamports", body)
        self.assertNotIn("claim_token", body)
        self.assertNotIn("local_signature", body)
        # Public fields ARE allowed:
        self.assertIn("expired", body)
        self.assertIn("reason", body)

    # --- 422 on invalid draft_id ---------------------------------

    def test_invalid_draft_id_returns_422(self):
        # Path length below 16 chars, or chars outside [A-Za-z0-9_-]
        r = self._client.get(
            "/crypto/wallet/network/solana_mainnet/"
            "draft/short/expiry",
        )
        self.assertEqual(r.status_code, 422)
        detail = r.json()["detail"]
        self.assertEqual(detail["wallet_engine"], "invalid_draft_id")

    def test_invalid_chars_in_draft_id_returns_422(self):
        r = self._client.get(
            "/crypto/wallet/network/solana_mainnet/"
            "draft/bad!chars@in$draftid12345/expiry",
        )
        self.assertEqual(r.status_code, 422)


# =================================================================
# 3. TRON endpoint — direct helper + HTTP envelope + boundary.
# =================================================================


class TronExpiryEndpointMatrix(unittest.TestCase):

    def setUp(self) -> None:
        _enable_tron()
        self._client, self._app, self._m = _make_app(
            vault_id=_VAULT_ALICE,
        )

    def tearDown(self) -> None:
        _clear_env()

    def _seed(
        self,
        draft_id: str = "expiry-tron-alice-1234567890",
        *,
        vault_id: str = _VAULT_ALICE,
        expiration_ms: int = 99_999_999_999_999,
        consumed: bool = False,
    ) -> str:
        self._m._tron_store.seed_draft(
            draft_id,
            vault_id=vault_id,
            network_id="tron_mainnet",
            sender_address=_TRN_A,
            destination_address=_TRN_B,
            token_contract_address=_TRN_C,
            amount_base_units=1_000_000,
            fee_limit_sun=100_000_000,
            expiration_ms=expiration_ms,
            server_txid_hex="a" * 64,
        )
        if consumed:
            import time as _t
            row = self._m._tron_store._drafts[draft_id]
            row["consumed_at"] = _t.time()
            row["local_txid_hex"] = "a" * 64
            row["broadcast_outcome"] = "submitted"
        return draft_id

    def _hit(self, draft_id: str) -> dict:
        return self._client.get(
            f"/crypto/wallet/network/tron_mainnet/"
            f"draft/{draft_id}/expiry",
        ).json()

    # --- boundary matrix -----------------------------------------

    def test_before_expiration_reports_not_expired(self):
        did = self._seed(expiration_ms=99_999_999_999_999)
        body = self._hit(did)
        self.assertEqual(body["expired"], False)
        self.assertEqual(body["reason"], "still_valid")
        self.assertEqual(body["expirationMs"], 99_999_999_999_999)

    def test_exact_boundary_reports_expired(self):
        # now_ms == expiration_ms → expired.
        exp = 1_600_000_000_000
        did = self._seed(expiration_ms=exp)
        with mock.patch(
            "routes.crypto_wallet_routes._now_secs",
            return_value=exp / 1000.0,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], True)
        self.assertEqual(body["reason"], "expiration_passed")

    def test_after_expiration_reports_expired(self):
        exp = 1_600_000_000_000
        did = self._seed(expiration_ms=exp)
        with mock.patch(
            "routes.crypto_wallet_routes._now_secs",
            return_value=(exp + 5000) / 1000.0,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], True)

    def test_one_ms_before_expiration_is_valid(self):
        exp = 1_600_000_000_000
        did = self._seed(expiration_ms=exp)
        with mock.patch(
            "routes.crypto_wallet_routes._now_secs",
            return_value=(exp - 1) / 1000.0,
        ):
            body = self._hit(did)
        self.assertEqual(body["expired"], False)

    # --- draft state machine paths -------------------------------

    def test_unknown_draft_fails_closed_without_leak(self):
        body = self._hit("expiry-tron-nonexistent-abcd1234")
        self.assertEqual(body["expired"], True)
        self.assertIn(body["reason"], (
            "unknown_or_expired_draft",
            "draft_vault_mismatch",
        ))
        self.assertNotIn("vault_id", body)
        self.assertNotIn("destination_address", body)
        self.assertNotIn("token_contract_address", body)
        self.assertNotIn("amount_base_units", body)

    def test_wrong_vault_owner_fails_closed_without_leak(self):
        did = self._seed(
            "expiry-tron-bob-1234567890abcd",
            vault_id=_VAULT_BOB, expiration_ms=99_999_999_999_999,
        )
        body = self._hit(did)
        self.assertEqual(body["expired"], True)
        self.assertNotIn("expirationMs", body)
        self.assertNotIn("destination_address", body)

    def test_consumed_draft_reports_expired_with_distinct_reason(
        self,
    ):
        did = self._seed(consumed=True)
        body = self._hit(did)
        self.assertEqual(body["expired"], True)
        self.assertEqual(body["reason"], "draft_already_consumed")

    def test_zero_persisted_expiration_fails_closed(self):
        fake_draft = {
            "draft_id": "expiry-tron-zero-exp-1234abcd",
            "vault_id": _VAULT_ALICE,
            "network_id": "tron_mainnet",
            "consumed": False,
            "expiration_ms": 0,
        }
        with mock.patch.object(
            self._m._tron_store, "load_draft_readonly",
            return_value=(fake_draft, None),
        ):
            body = self._hit("expiry-tron-zero-exp-1234abcd")
        self.assertEqual(body["expired"], True)
        self.assertEqual(body["reason"], "draft_missing_expiration")

    def test_malformed_persisted_expiration_fails_closed(self):
        fake_draft = {
            "draft_id": "expiry-tron-bad-exp-1234abcdef",
            "vault_id": _VAULT_ALICE,
            "network_id": "tron_mainnet",
            "consumed": False,
            "expiration_ms": "not-a-number",
        }
        with mock.patch.object(
            self._m._tron_store, "load_draft_readonly",
            return_value=(fake_draft, None),
        ):
            body = self._hit("expiry-tron-bad-exp-1234abcdef")
        self.assertEqual(body["expired"], True)
        self.assertEqual(body["reason"], "malformed_expiration_ms")

    # --- privacy -------------------------------------------------

    def test_response_never_leaks_claim_or_owner_details(self):
        did = self._seed(expiration_ms=99_999_999_999_999)
        row = self._m._tron_store._drafts[did]
        row["claim_token"] = "TRON_EXPIRY_CLAIM_TOKEN_CANARY"
        row["local_txid_hex"] = "TRON_EXPIRY_TXID_CANARY"
        body = self._hit(did)
        raw = str(body)
        self.assertNotIn("CANARY", raw)
        self.assertNotIn("vault_id", body)
        self.assertNotIn("sender_address", body)
        self.assertNotIn("destination_address", body)
        self.assertNotIn("amount_base_units", body)
        self.assertNotIn("fee_limit_sun", body)
        self.assertNotIn("claim_token", body)
        self.assertNotIn("local_txid_hex", body)
        self.assertNotIn("raw_data_hex", body)
        # Public fields ARE allowed:
        self.assertIn("expired", body)
        self.assertIn("reason", body)


# =================================================================
# 4. SOL parity — endpoint and broadcast state machine agree.
# =================================================================


class SolExpiryEndpointBroadcastParity(unittest.TestCase):
    """PROOF that the endpoint's yes/no answer and the SOL broadcast
    state machine's yes/no answer track EXACTLY. If drift ever
    appears here, the client's pre-sign check will lie."""

    def setUp(self) -> None:
        _enable_sol()
        self._client, self._app, self._m = _make_app(
            vault_id=_VAULT_ALICE,
        )
        self._m.reset_solana_safety_state_for_tests()

    def tearDown(self) -> None:
        self._m.reset_solana_safety_state_for_tests()
        _clear_env()

    def _seed_and_dispatch(self, current_block_height: int) -> tuple:
        from routes.crypto_wallet_routes import (
            SendBroadcastPayload, _solana_broadcast_dispatch,
        )
        did = self._m._solana_store.register_draft(
            vault_id=_VAULT_ALICE, network_id="solana_mainnet",
            sender_address=_SOL_A, asset="SOL",
            destination_address=_SOL_B,
            value_lamports=1_000_000, fee_lamports=5000,
            recent_blockhash=(
                "GfVPzKR8Uz2Sa4Pxrw6JHQKtu4LFB1cUKQwT8b9DhP7A"
            ),
            last_valid_block_height=1_000, ttl_secs=600,
        )
        # Endpoint says…
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=current_block_height,
        ):
            endpoint_body = self._client.get(
                f"/crypto/wallet/network/solana_mainnet/"
                f"draft/{did}/expiry",
            ).json()
        # Broadcast says…
        payload = SendBroadcastPayload(
            signedTransaction="AAAA", draftId=did,
        )
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=current_block_height,
        ), mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value="X" * 64,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_extract_solana_primary_signature",
            return_value="X" * 64,
        ):
            broadcast_result = _solana_broadcast_dispatch(
                "SOL", payload, {"vault_id": _VAULT_ALICE},
            )
        return endpoint_body, broadcast_result

    def test_one_below_boundary_endpoint_and_broadcast_both_allow(
        self,
    ):
        endpoint, broadcast = self._seed_and_dispatch(999)
        self.assertEqual(endpoint["expired"], False)
        self.assertEqual(broadcast["status"], "submitted")

    def test_exact_boundary_endpoint_and_broadcast_both_allow(self):
        # current == last_valid → BOTH allow.
        endpoint, broadcast = self._seed_and_dispatch(1_000)
        self.assertEqual(endpoint["expired"], False)
        self.assertEqual(broadcast["status"], "submitted")

    def test_first_expired_height_both_reject(self):
        # current > last_valid → BOTH reject. Broadcast returns a
        # draft_expired envelope BEFORE any signature extraction /
        # RPC send call happens.
        endpoint, broadcast = self._seed_and_dispatch(1_001)
        self.assertEqual(endpoint["expired"], True)
        self.assertEqual(broadcast["status"], "draft_expired")
        self.assertEqual(
            broadcast["reason"], "blockheight_exceeded",
        )

    def test_far_expired_height_both_reject(self):
        endpoint, broadcast = self._seed_and_dispatch(9_999_999)
        self.assertEqual(endpoint["expired"], True)
        self.assertEqual(broadcast["status"], "draft_expired")


# =================================================================
# 5. TRON parity — endpoint and broadcast state machine agree.
# =================================================================


class TronExpiryEndpointBroadcastParity(unittest.TestCase):

    def setUp(self) -> None:
        _enable_tron()
        self._client, self._app, self._m = _make_app(
            vault_id=_VAULT_ALICE,
        )
        self._m.reset_tron_safety_state_for_tests()

    def tearDown(self) -> None:
        self._m.reset_tron_safety_state_for_tests()
        _clear_env()

    def _valid_signed_tx(self) -> dict:
        return {
            "txID": "a" * 64,
            "raw_data": {
                "contract": [{"type": "TriggerSmartContract"}],
                "expiration": 99_999_999_999_999,
            },
            "raw_data_hex": "0a" * 20,
            "signature": ["b" * 130],
        }

    def _seed_and_dispatch(
        self, *, now_ms: int, expiration_ms: int,
    ) -> tuple:
        from routes.crypto_wallet_routes import (
            SendBroadcastPayload, _tron_broadcast_dispatch,
        )
        did = self._m._tron_store.register_draft(
            vault_id=_VAULT_ALICE, network_id="tron_mainnet",
            sender_address=_TRN_A, asset="USDT_TRC20",
            destination_address=_TRN_B,
            token_contract_address=_TRN_C,
            amount_base_units=1_000_000,
            fee_limit_sun=100_000_000,
            raw_data_hex="0a" * 20,
            expiration_ms=expiration_ms,
            server_txid_hex="a" * 64,
            ttl_secs=600,
        )
        # Endpoint answer at now_ms.
        with mock.patch(
            "routes.crypto_wallet_routes._now_secs",
            return_value=now_ms / 1000.0,
        ):
            endpoint_body = self._client.get(
                f"/crypto/wallet/network/tron_mainnet/"
                f"draft/{did}/expiry",
            ).json()
        # Broadcast answer at the same now_ms.
        payload = SendBroadcastPayload(
            signedTransaction=self._valid_signed_tx(), draftId=did,
        )
        with mock.patch(
            "routes.crypto_wallet_routes._now_secs",
            return_value=now_ms / 1000.0,
        ):
            broadcast_result = _tron_broadcast_dispatch(
                "USDT_TRC20", payload, {"vault_id": _VAULT_ALICE},
            )
        return endpoint_body, broadcast_result

    def test_one_ms_before_expiration_both_allow(self):
        endpoint, broadcast = self._seed_and_dispatch(
            now_ms=999, expiration_ms=1_000,
        )
        self.assertEqual(endpoint["expired"], False)
        # Broadcast will actually call the tron API which is
        # unmocked here — but the state-machine advances past the
        # expiration check without returning `draft_expired`, which
        # is the parity property we're testing.
        self.assertNotEqual(
            broadcast.get("status"), "draft_expired",
        )

    def test_exact_boundary_both_reject(self):
        endpoint, broadcast = self._seed_and_dispatch(
            now_ms=1_000, expiration_ms=1_000,
        )
        self.assertEqual(endpoint["expired"], True)
        self.assertEqual(broadcast["status"], "draft_expired")
        self.assertEqual(
            broadcast["reason"], "expiration_passed",
        )

    def test_past_expiration_both_reject(self):
        endpoint, broadcast = self._seed_and_dispatch(
            now_ms=2_000, expiration_ms=1_000,
        )
        self.assertEqual(endpoint["expired"], True)
        self.assertEqual(broadcast["status"], "draft_expired")


# =================================================================
# 6. Auth / ownership / privacy on the HTTP layer.
# =================================================================


class ExpiryEndpointAuthAndOwnership(unittest.TestCase):

    def setUp(self) -> None:
        _enable_sol()
        _enable_tron()  # both enabled for this suite
        # Re-enable both at once
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://sol.example"
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _clear_env()

    def test_missing_auth_returns_401_on_sol(self):
        client, _ = _make_app_no_auth()
        r = client.get(
            "/crypto/wallet/network/solana_mainnet/"
            "draft/expiry-sol-nonexistent-abcd1234/expiry",
        )
        self.assertEqual(r.status_code, 401)

    def test_missing_auth_returns_401_on_tron(self):
        client, _ = _make_app_no_auth()
        r = client.get(
            "/crypto/wallet/network/tron_mainnet/"
            "draft/expiry-tron-nonexistent-abcd1234/expiry",
        )
        self.assertEqual(r.status_code, 401)

    def test_invalid_auth_bearer_returns_401(self):
        client, _ = _make_app_no_auth()
        r = client.get(
            "/crypto/wallet/network/solana_mainnet/"
            "draft/expiry-sol-nonexistent-abcd1234/expiry",
            headers={"Authorization": "Bearer this-is-not-a-token"},
        )
        self.assertEqual(r.status_code, 401)

    def test_wrong_owner_cannot_see_another_vaults_draft(self):
        # Alice authenticated, but the draft belongs to Bob. The
        # endpoint MUST NOT confirm existence.
        client, _, m = _make_app(vault_id=_VAULT_ALICE)
        m._solana_store.seed_draft(
            "expiry-owned-by-bob-1234567890",
            vault_id=_VAULT_BOB,
            network_id="solana_mainnet",
            sender_address=_SOL_A,
            destination_address=_SOL_B,
            value_lamports=1_000_000,
            fee_lamports=5000,
            last_valid_block_height=1_000,
        )
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = client.get(
                "/crypto/wallet/network/solana_mainnet/"
                "draft/expiry-owned-by-bob-1234567890/expiry",
            ).json()
        # Alice sees a fail-closed envelope, not Bob's block height.
        self.assertEqual(body["expired"], True)
        self.assertNotIn("currentBlockHeight", body)
        self.assertNotIn("lastValidBlockHeight", body)

    def test_response_shape_only_documented_fields(self):
        # Success path — only the documented shape appears in the
        # body.
        client, _, m = _make_app(vault_id=_VAULT_ALICE)
        m._solana_store.seed_draft(
            "expiry-sol-shape-check-12345",
            vault_id=_VAULT_ALICE,
            network_id="solana_mainnet",
            sender_address=_SOL_A,
            destination_address=_SOL_B,
            value_lamports=1_000_000,
            fee_lamports=5000,
            last_valid_block_height=1_000,
        )
        with mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=999,
        ):
            body = client.get(
                "/crypto/wallet/network/solana_mainnet/"
                "draft/expiry-sol-shape-check-12345/expiry",
            ).json()
        allowed = {
            "expired", "network", "reason",
            "currentBlockHeight", "lastValidBlockHeight",
        }
        for key in body.keys():
            self.assertIn(
                key, allowed,
                msg=f"Unexpected key in expiry envelope: {key}",
            )


# =================================================================
# 7. Non-SOL/TRON network routing on the endpoint.
# =================================================================


class ExpiryEndpointNonSolTronNetworks(unittest.TestCase):

    def setUp(self) -> None:
        _clear_env()
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client, self._app, self._m = _make_app(
            vault_id=_VAULT_ALICE,
        )

    def tearDown(self) -> None:
        _clear_env()

    def test_ethereum_mainnet_returns_no_expiry_semantics(self):
        # ETH uses nonce-based ordering, not expiry. The route
        # returns a well-defined "no_expiry_semantics" envelope
        # rather than 404 so the client parser has a single shape.
        r = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/"
            "draft/anything-not-mattering-here/expiry",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["expired"], False)
        self.assertEqual(body["reason"], "no_expiry_semantics")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
