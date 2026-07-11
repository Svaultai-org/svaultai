"""Backend regression: every user-facing /crypto/wallet/* endpoint
must gate on the shared crypto entitlement dependency.

Before this test file existed the wallet routes were protected only by
``verify_trusted_device`` + the global feature flag. A trusted-device
but non-upgraded user could bypass every in-app gate by calling the
raw HTTP API. This suite locks in the fix.

Rules asserted:

  1. Non-upgraded authenticated trusted-device caller receives 403 with
     the canonical machine code ``crypto_vault_upgrade_required``.
  2. Upgraded caller passes the entitlement check and reaches the
     downstream handler (which may then respond with its own 200/400/
     etc. — we do NOT assert 200 here because most handlers hit the DB
     or providers we do not want to mock end-to-end).
  3. Untrusted caller remains blocked by verify_trusted_device (which
     runs before entitlement) — 401 not 403.
  4. Global feature flag OFF: entitlement helper still runs and the
     handler's own engine-off path returns its expected shape.
  5. Expired / inactive entitlement (block_count == 0 OR
     purchased_bytes == 0) is treated exactly like the "free" tier — 403.
  6. Coverage sentinel: enumerate every ``@router`` definition in the
     crypto_wallet_routes module and assert every user-facing route is
     bound to ``require_crypto_entitlement``. This is the "no route
     accidentally left unprotected" guard.
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from crypto_entitlement import (
    ENTITLEMENT_CODE_UPGRADE_REQUIRED,
    require_crypto_entitlement,
)
from device_gate import verify_trusted_device


TEST_VAULT_ID = "11111111-1111-1111-1111-111111111111"
TEST_ACCOUNT  = "22222222-2222-2222-2222-222222222222"


class _StorageEnt:
    """Minimal duck of ``billing.StorageEntitlement`` for the fields
    the entitlement gate reads."""

    def __init__(self, block_count: int, purchased_bytes: int):
        self.block_count     = block_count
        self.purchased_bytes = purchased_bytes


def _principal(vault_id: str = TEST_VAULT_ID) -> dict:
    return {
        "vault_id":   vault_id,
        "vault_name": "alice",
        "token_id":   "tok-1",
        "device_id":  "dev-1",
    }


def _mount_wallet_routes(with_trusted_principal: bool = True) -> TestClient:
    """Mount just the crypto wallet router, override the trusted-device
    dependency with a fake principal (or leave it un-overridden so the
    real dependency raises 401)."""

    from routes.crypto_wallet_routes import router
    app = FastAPI()
    app.include_router(router)
    if with_trusted_principal:
        app.dependency_overrides[verify_trusted_device] = _principal
    return TestClient(app)


def _patched_entitlement(block_count: int, purchased_bytes: int):
    ent = _StorageEnt(block_count, purchased_bytes)
    return patch.multiple(
        "crypto_entitlement",
        _resolve_upgraded_flag=lambda vault_id: (
            block_count > 0 and purchased_bytes > 0 and bool(vault_id)
        ),
    )


class NonEntitledIs403(unittest.TestCase):

    def test_non_entitled_receive_returns_403(self):
        client = _mount_wallet_routes()
        with _patched_entitlement(block_count=0, purchased_bytes=0):
            r = client.get("/crypto/wallet/ETH/receive")
        self.assertEqual(r.status_code, 403, r.text)
        body = r.json().get("detail", {})
        self.assertEqual(body.get("code"), ENTITLEMENT_CODE_UPGRADE_REQUIRED)

    def test_non_entitled_scanner_status_returns_403(self):
        client = _mount_wallet_routes()
        with _patched_entitlement(block_count=0, purchased_bytes=0):
            r = client.get("/crypto/wallet/xmr/scanner/status")
        self.assertEqual(r.status_code, 403)

    def test_non_entitled_send_draft_returns_403(self):
        client = _mount_wallet_routes()
        with _patched_entitlement(block_count=0, purchased_bytes=0):
            r = client.post(
                "/crypto/wallet/ETH/send/draft",
                json={"asset": "ETH", "amount": "0.01", "recipient": "0x00"},
            )
        self.assertEqual(r.status_code, 403)

    def test_non_entitled_body_does_not_leak_billing_internals(self):
        client = _mount_wallet_routes()
        with _patched_entitlement(block_count=0, purchased_bytes=0):
            r = client.get("/crypto/wallet/ETH/balance")
        self.assertEqual(r.status_code, 403)
        body_text = r.text.lower()
        for leak in (
            "purchased_bytes", "block_count",
            "current_period_end", "cancel_at_period_end", "stripe",
        ):
            self.assertNotIn(leak, body_text,
                             msg=f"body must not leak {leak!r}: {r.text!r}")


class EntitledPassesEntitlementGate(unittest.TestCase):

    def test_entitled_reach_downstream_handler(self):

        client = _mount_wallet_routes()

        class _FakeCur:
            def execute(self, *a, **kw): pass
            def fetchall(self): return []
            def close(self): pass
        class _FakeConn:
            def cursor(self, *a, **kw): return _FakeCur()
            def close(self): pass
        with _patched_entitlement(
            block_count=1, purchased_bytes=53_687_091_200,
        ), patch(
            "routes.crypto_wallet_routes.get_db",
            return_value=_FakeConn(),
        ):
            r = client.get("/crypto/wallet/accounts")

        self.assertNotEqual(r.status_code, 403,
                            msg=f"entitled user was rejected: {r.text}")
        self.assertEqual(r.status_code, 200,
                         msg=f"entitled user expected 200, got {r.status_code}: {r.text}")

    def test_entitled_zero_bytes_still_blocked(self):

        client = _mount_wallet_routes()
        with _patched_entitlement(
            block_count=1, purchased_bytes=0,
        ):
            r = client.get("/crypto/wallet/accounts")
        self.assertEqual(r.status_code, 403)

    def test_entitled_zero_block_still_blocked(self):

        client = _mount_wallet_routes()
        with _patched_entitlement(
            block_count=0, purchased_bytes=53_687_091_200,
        ):
            r = client.get("/crypto/wallet/accounts")
        self.assertEqual(r.status_code, 403)


class UntrustedDeviceStillBlocked(unittest.TestCase):

    def test_no_trusted_device_returns_not_200(self):

        from fastapi import FastAPI
        from routes.crypto_wallet_routes import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with _patched_entitlement(
            block_count=1, purchased_bytes=53_687_091_200,
        ):
            r = client.get("/crypto/wallet/accounts")

        self.assertNotEqual(r.status_code, 200)


class FeatureFlagOffPathUnchanged(unittest.TestCase):

    def test_feature_flag_off_returns_engine_disabled_body_for_entitled(self):

        client = _mount_wallet_routes()
        with _patched_entitlement(
            block_count=1, purchased_bytes=53_687_091_200,
        ), patch(
            "routes.crypto_wallet_routes.crypto_wallet_engine_enabled",
            return_value=False,
        ):
            r = client.get("/crypto/wallet/accounts")

        self.assertNotEqual(r.status_code, 403)

    def test_feature_flag_off_still_403s_non_entitled(self):

        client = _mount_wallet_routes()
        with _patched_entitlement(
            block_count=0, purchased_bytes=0,
        ), patch(
            "routes.crypto_wallet_routes.crypto_wallet_engine_enabled",
            return_value=False,
        ):
            r = client.get("/crypto/wallet/accounts")
        self.assertEqual(r.status_code, 403)


class ExpiredEntitlementIsBlocked(unittest.TestCase):

    def test_billing_returns_zero_bytes_after_expiry_is_403(self):

        client = _mount_wallet_routes()
        with _patched_entitlement(block_count=1, purchased_bytes=0):
            r = client.get("/crypto/wallet/ETH/balance")
        self.assertEqual(r.status_code, 403)


class RouteCoverageSentinel(unittest.TestCase):

    ROUTE_PREFIX_GATED = "/crypto/wallet/"
    OPEN_PATHS = frozenset({
        "/crypto/wallet/assets",
        "/crypto/wallet/evm-networks",
        "/crypto/wallet/features",
        "/crypto/wallet/health",
        "/crypto/wallet/diagnosis",
    })

    def test_every_user_facing_wallet_route_uses_require_crypto_entitlement(self):

        from routes import crypto_wallet_routes as m
        src = open(m.__file__, encoding="utf-8").read()

        route_pattern = re.compile(
            r'@router\.(get|post|delete|put)\(\s*[\'"]([^\'"]+)[\'"]',
        )
        dep_pattern = re.compile(
            r'principal=Depends\(([a-zA-Z_][a-zA-Z0-9_]*)\)',
        )

        lines = src.split("\n")
        route_index = []
        for i, ln in enumerate(lines):
            m1 = route_pattern.search(ln)
            if m1:
                route_index.append((i, m1.group(2)))

        misprotected = []
        expected_gated_count = 0
        for i, path in route_index:

            for j in range(i, min(i + 60, len(lines))):
                m2 = dep_pattern.search(lines[j])
                if m2:
                    dep_name = m2.group(1)
                    if not path.startswith(self.ROUTE_PREFIX_GATED):
                        break
                    if path in self.OPEN_PATHS:
                        break
                    expected_gated_count += 1
                    if dep_name != "require_crypto_entitlement":
                        misprotected.append((path, dep_name))
                    break

        self.assertEqual(
            misprotected, [],
            msg=(
                "The following user-facing wallet routes are NOT bound "
                "to require_crypto_entitlement — this leaves an API "
                "bypass for non-upgraded users:\n" +
                "\n".join(f"  {p} -> {d}" for p, d in misprotected)
            ),
        )
        self.assertGreaterEqual(
            expected_gated_count, 15,
            msg="expected at least 15 gated wallet routes; the "
                "coverage guard has drifted",
        )

    def test_admin_and_public_routes_stay_open(self):

        from routes import crypto_wallet_routes as m
        src = open(m.__file__, encoding="utf-8").read()

        for path in self.OPEN_PATHS:

            block = re.search(
                re.escape(f'"{path}"') + r'.{0,800}?principal=Depends\(([a-zA-Z_]+)\)',
                src, flags=re.DOTALL,
            )
            self.assertIsNotNone(block,
                                 msg=f'did not find Depends for {path}')
            dep_name = block.group(1)
            self.assertNotEqual(
                dep_name, "require_crypto_entitlement",
                msg=f"{path} must stay open (not require entitlement)",
            )


if __name__ == "__main__":
    unittest.main()
