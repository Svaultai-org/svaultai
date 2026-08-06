"""QA Crypto Vault entitlement hardening.

The Sepolia canary needs a legitimate, reversible entitlement for one
dedicated QA account. These tests make sure the QA admin-grant path
uses the normal billing/entitlement model instead of adding a client
bypass or a wallet-specific testing route.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import billing
from crypto_entitlement import ENTITLEMENT_CODE_UPGRADE_REQUIRED
from device_gate import verify_trusted_device
from fastapi import FastAPI
from fastapi.testclient import TestClient


TEST_VAULT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_VAULT_ID = "33333333-3333-3333-3333-333333333333"
TEST_ACCOUNT_ID = "22222222-2222-2222-2222-222222222222"
BLOCK_BYTES = 53_687_091_200


def _principal(vault_id: str = TEST_VAULT_ID) -> dict:
    return {
        "vault_id": vault_id,
        "vault_name": "qa-vault-redacted",
        "token_id": "tok-redacted",
        "device_id": "dev-redacted",
    }


def _client_for(vault_id: str = TEST_VAULT_ID) -> TestClient:
    from routes.crypto_wallet_routes import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = (
        lambda: _principal(vault_id)
    )
    return TestClient(app)


def _entitlement_row(*, admin_grant_expired: bool) -> dict:
    return {
        "account_id": TEST_ACCOUNT_ID,
        "account_type": "individual",
        "sales_channel": "self_service",
        "status": "active",
        "source": "admin_grant",
        "block_count": 1,
        "purchased_bytes": BLOCK_BYTES,
        "storage_bytes_grant": 0,
        "storage_bytes_grant_expires_at": None,
        "current_period_end": datetime.now(timezone.utc),
        "admin_grant_expired": admin_grant_expired,
        "cancel_at_period_end": False,
        "used_bytes": 0,
    }


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return self.row


class _FakeConn:
    def __init__(self, row):
        self.row = row

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.row)

    def close(self):
        return None


class AdminGrantExpiryTests(unittest.TestCase):

    def setUp(self):
        self._pricing = dict(billing._PRICING_CACHE)
        billing._PRICING_CACHE.clear()
        billing._PRICING_CACHE.update({
            "included_bytes": 1_073_741_824,
            "block_bytes": BLOCK_BYTES,
            "block_price_cents_usd": 2500,
            "self_service_max_blocks": 100,
        })

    def tearDown(self):
        billing._PRICING_CACHE.clear()
        billing._PRICING_CACHE.update(self._pricing)

    def test_live_admin_grant_satisfies_crypto_entitlement_shape(self):
        with patch("billing.get_db",
                   return_value=_FakeConn(
                       _entitlement_row(admin_grant_expired=False))):
            ent = billing.get_entitlement(TEST_ACCOUNT_ID)

        self.assertEqual(ent.source, "admin_grant")
        self.assertEqual(ent.status, "active")
        self.assertEqual(ent.block_count, 1)
        self.assertEqual(ent.purchased_bytes, BLOCK_BYTES)

    def test_expired_admin_grant_fails_closed(self):
        with patch("billing.get_db",
                   return_value=_FakeConn(
                       _entitlement_row(admin_grant_expired=True))):
            ent = billing.get_entitlement(TEST_ACCOUNT_ID)

        self.assertEqual(ent.source, "admin_grant")
        self.assertEqual(ent.status, "expired")
        self.assertEqual(ent.block_count, 0)
        self.assertEqual(ent.purchased_bytes, 0)


class QaEntitlementOperatorGateTests(unittest.TestCase):

    def test_production_apply_requires_cli_and_environment_ack(self):
        import scripts.grant_qa_crypto_entitlement as grant_script

        with patch.object(grant_script, "is_production", return_value=True):
            with patch.dict(os.environ, {
                grant_script.PRODUCTION_ACK_ENV: "true",
            }, clear=False):
                grant_script._check_operator_gate(
                    apply=True,
                    production_ack=True,
                )

            with patch.dict(os.environ, {
                grant_script.PRODUCTION_ACK_ENV: "false",
            }, clear=False):
                with self.assertRaises(PermissionError):
                    grant_script._check_operator_gate(
                        apply=True,
                        production_ack=True,
                    )

            with patch.dict(os.environ, {
                grant_script.PRODUCTION_ACK_ENV: "true",
            }, clear=False):
                with self.assertRaises(PermissionError):
                    grant_script._check_operator_gate(
                        apply=True,
                        production_ack=False,
                    )

    def test_dry_run_does_not_require_production_ack(self):
        import scripts.grant_qa_crypto_entitlement as grant_script

        with patch.object(grant_script, "is_production", return_value=True):
            with patch.dict(os.environ, {
                grant_script.PRODUCTION_ACK_ENV: "false",
            }, clear=False):
                grant_script._check_operator_gate(
                    apply=False,
                    production_ack=False,
                )


class EntitlementForgeryAndIsolationTests(unittest.TestCase):

    def test_frontend_header_cannot_forge_crypto_entitlement(self):
        client = _client_for()
        with patch("crypto_entitlement._resolve_upgraded_flag",
                   return_value=False):
            response = client.get(
                "/crypto/wallet/ETH/receive",
                headers={"X-Crypto-Entitled": "true"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"]["code"],
            ENTITLEMENT_CODE_UPGRADE_REQUIRED,
        )

    def test_request_payload_cannot_bypass_crypto_entitlement(self):
        client = _client_for()
        with patch("crypto_entitlement._resolve_upgraded_flag",
                   return_value=False):
            response = client.post(
                "/crypto/wallet/network/ethereum_sepolia/ETH/send/draft",
                json={
                    "fromAddress": "0x0000000000000000000000000000000000000001",
                    "destinationAddress": (
                        "0x0000000000000000000000000000000000000002"
                    ),
                    "amountEth": "0.00001",
                    "entitled": True,
                    "account_id": TEST_ACCOUNT_ID,
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_other_vault_cannot_use_qa_account_entitlement(self):
        client = _client_for(OTHER_VAULT_ID)

        def entitled_only_for_qa(vault_id):
            return vault_id == TEST_VAULT_ID

        with patch("crypto_entitlement._resolve_upgraded_flag",
                   side_effect=entitled_only_for_qa):
            response = client.get("/crypto/wallet/accounts")

        self.assertEqual(response.status_code, 403)

    def test_revoked_entitlement_state_restores_403(self):
        client = _client_for()
        # Keep the route body DB-free: this test proves the dependency gate,
        # not wallet-account listing. The dependency still runs before the
        # deliberately disabled engine response.
        with patch(
            "routes.crypto_wallet_routes.crypto_wallet_engine_enabled",
            return_value=False,
        ):
            with patch("crypto_entitlement._resolve_upgraded_flag",
                       return_value=True):
                granted = client.get("/crypto/wallet/accounts")
            with patch("crypto_entitlement._resolve_upgraded_flag",
                       return_value=False):
                revoked = client.get("/crypto/wallet/accounts")

        self.assertNotEqual(granted.status_code, 403)
        self.assertEqual(revoked.status_code, 403)


if __name__ == "__main__":
    unittest.main()
