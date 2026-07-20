# Single-active-device enforcement (2026-07-20).
#
# What this suite proves:
#   1. First signup trusts the current device immediately (no
#      'pending' row, no /device-pending redirect).
#   2. Login on device B revokes device A atomically.
#   3. Only one non-revoked device row ever exists per vault after
#      any successful trust operation.
#   4. Re-login on device A revokes device B (symmetric).
#   5. /devices/register never returns 'pending'.
#   6. The device gate emits `code: "device_revoked"` (not the legacy
#      `device_not_trusted`) once a device row is 'revoked', so the
#      client can drop the local session and route to /auth without
#      hitting the legacy pending-trust screen.
#
# We use an in-memory Postgres emulator scoped to just the SQL
# statements our device code issues. That's enough to run the trust
# primitive, the gate, and the /devices/register route end-to-end
# under unittest without any live database.

from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# In-memory DB fake
# ---------------------------------------------------------------------------

class _Row(dict):
    pass


class InMemoryTrustedDevicesDb:
    # Emulates just the columns and statements our device code issues.
    # `rows` is keyed by (vault_id, device_id).

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], _Row] = {}

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    # ---- introspection helpers used by tests -----------------------------

    def status(self, vault_id: str, device_id: str) -> Optional[str]:
        r = self.rows.get((vault_id, device_id))
        return None if r is None else r["status"]

    def rows_for_vault(self, vault_id: str) -> list[_Row]:
        return [r for k, r in self.rows.items() if k[0] == vault_id]

    def non_revoked_rows_for_vault(self, vault_id: str) -> list[_Row]:
        return [r for r in self.rows_for_vault(vault_id)
                if r["status"] != "revoked"]

    # ---- cursor / connection surface ------------------------------------

    def connect(self) -> "_FakeConnection":
        return _FakeConnection(self)


class _FakeConnection:
    def __init__(self, db: InMemoryTrustedDevicesDb) -> None:
        self.db = db
        self.committed = False
        self.rolled_back = False
        self._cursor = _FakeCursor(db)

    def cursor(self, *_args, **_kwargs) -> "_FakeCursor":
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


class _FakeCursor:
    def __init__(self, db: InMemoryTrustedDevicesDb) -> None:
        self.db = db
        self._pending: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Optional[tuple] = None) -> None:
        norm = re.sub(r"\s+", " ", sql).strip().lower()
        params = params or ()

        # ---- SELECT status FROM trusted_devices WHERE vid AND did ------
        if norm.startswith("select status from trusted_devices"):
            vault_id, device_id = params
            row = self.db.rows.get((vault_id, device_id))
            self._pending = [{"status": row["status"]}] if row else []
            return

        # ---- SELECT COUNT(*) trusted ------------------------------------
        if norm.startswith("select count(*) as n from trusted_devices"):
            vault_id, = params
            n = sum(1 for r in self.db.rows_for_vault(vault_id)
                    if r["status"] == "trusted")
            self._pending = [{"n": n}]
            return

        # ---- INSERT ... ON CONFLICT DO UPDATE (the trust upsert) ---------
        if norm.startswith("insert into trusted_devices") and "on conflict" in norm:
            (vault_id, device_id, label, ua_brand, ip_prefix) = params
            key = (vault_id, device_id)
            existing = self.db.rows.get(key)
            if existing is None:
                self.db.rows[key] = _Row(
                    vault_id=vault_id,
                    device_id=device_id,
                    label=label,
                    user_agent_brand=ua_brand,
                    last_ip_prefix=ip_prefix,
                    status="trusted",
                    cooldown_until=None,
                    created_at=self.db.now(),
                    approved_at=self.db.now(),
                    revoked_at=None,
                    last_seen_at=self.db.now(),
                )
            else:
                existing["status"] = "trusted"
                existing["approved_at"] = self.db.now()
                existing["last_seen_at"] = self.db.now()
                existing["revoked_at"] = None
                existing["cooldown_until"] = None
                if ip_prefix is not None:
                    existing["last_ip_prefix"] = ip_prefix
                if ua_brand is not None:
                    existing["user_agent_brand"] = ua_brand
                if label:
                    existing["label"] = label
            self._pending = []
            return

        # ---- UPDATE ... SET status='revoked' WHERE others RETURNING -----
        if (
            norm.startswith("update trusted_devices")
            and "set status = 'revoked'" in norm
            and "device_id <> %s" in norm
        ):
            vault_id, current_device_id = params
            revoked: list[dict[str, Any]] = []
            for (vid, did), r in self.db.rows.items():
                if vid != vault_id:
                    continue
                if did == current_device_id:
                    continue
                if r["status"] == "revoked":
                    continue
                r["status"] = "revoked"
                r["revoked_at"] = self.db.now()
                r["cooldown_until"] = None
                revoked.append({"device_id": did})
            self._pending = revoked
            return

        # ---- UPDATE last_seen_at metadata refresh (legacy path) ---------
        if (
            norm.startswith("update trusted_devices")
            and "last_seen_at = now()" in norm
            and "set status" not in norm
        ):
            # Older code path; not exercised by the new primitive.
            self._pending = []
            return

        raise AssertionError(
            f"unexpected SQL in fake cursor: {norm!r} params={params!r}",
        )

    def fetchone(self) -> Optional[dict[str, Any]]:
        return self._pending.pop(0) if self._pending else None

    def fetchall(self) -> list[dict[str, Any]]:
        rows = list(self._pending)
        self._pending.clear()
        return rows


def _install_fake_db(db: InMemoryTrustedDevicesDb):
    import device_gate
    import device_monitor
    original_dm = device_monitor.get_db
    original_dg = device_gate.get_db
    device_monitor.get_db = db.connect
    device_gate.get_db = db.connect
    return original_dm, original_dg


def _restore_get_db(originals) -> None:
    import device_gate
    import device_monitor
    device_monitor.get_db = originals[0]
    device_gate.get_db = originals[1]


# ---------------------------------------------------------------------------
# Primitive tests
# ---------------------------------------------------------------------------

class TrustCurrentAndRevokeOthersTests(unittest.TestCase):

    def setUp(self) -> None:
        import device_monitor
        self.device_monitor = device_monitor
        self.db = InMemoryTrustedDevicesDb()
        self._originals = _install_fake_db(self.db)
        self.vault_id = "00000000-0000-4000-8000-0000000000a1"

    def tearDown(self) -> None:
        _restore_get_db(self._originals)

    def test_first_signup_trusts_current_device(self):
        # Acceptance item 1: fresh vault + device A → device A is
        # trusted, no other rows.
        outcome = self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id,
            device_id="device-A_fresh_signup_aaaaaaaaaaaaa",
        )
        self.assertEqual(outcome["status"], "trusted")
        self.assertEqual(outcome["revoked_other_count"], 0)
        self.assertEqual(
            self.db.status(self.vault_id, "device-A_fresh_signup_aaaaaaaaaaaaa"),
            "trusted",
        )
        self.assertEqual(len(self.db.non_revoked_rows_for_vault(self.vault_id)), 1)

    def test_login_on_device_B_revokes_device_A(self):
        # Acceptance item 2: A trusted, B logs in → A revoked, B
        # trusted, exactly one live row.
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-A_aaaaaaaaaaaaaaaa",
        )
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-B_bbbbbbbbbbbbbbbb",
        )
        self.assertEqual(
            self.db.status(self.vault_id, "device-A_aaaaaaaaaaaaaaaa"),
            "revoked",
        )
        self.assertEqual(
            self.db.status(self.vault_id, "device-B_bbbbbbbbbbbbbbbb"),
            "trusted",
        )
        self.assertEqual(len(self.db.non_revoked_rows_for_vault(self.vault_id)), 1)

    def test_re_login_on_A_revokes_B(self):
        # Acceptance item 5: symmetric — user comes back to A, B is
        # revoked.
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-A_aaaaaaaaaaaaaaaa",
        )
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-B_bbbbbbbbbbbbbbbb",
        )
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-A_aaaaaaaaaaaaaaaa",
        )
        self.assertEqual(
            self.db.status(self.vault_id, "device-A_aaaaaaaaaaaaaaaa"),
            "trusted",
        )
        self.assertEqual(
            self.db.status(self.vault_id, "device-B_bbbbbbbbbbbbbbbb"),
            "revoked",
        )
        self.assertEqual(len(self.db.non_revoked_rows_for_vault(self.vault_id)), 1)

    def test_only_one_non_revoked_device_per_vault_ever(self):
        # Acceptance item 6: after ten alternating logins, at most
        # one non-revoked row exists at any observation point.
        devices = [f"device-{i:02d}_padding_padding_paddingpaddingpad" for i in range(10)]
        for did in devices:
            self.device_monitor.trust_current_and_revoke_others(
                vault_id=self.vault_id, device_id=did,
            )
            live = self.db.non_revoked_rows_for_vault(self.vault_id)
            self.assertEqual(
                len(live), 1,
                msg=f"after trusting {did!r}, expected exactly 1 live row",
            )
            self.assertEqual(live[0]["device_id"], did)

    def test_idempotent_on_same_device(self):
        # Calling twice with the same device is a no-op on revocation.
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-A_aaaaaaaaaaaaaaaa",
        )
        outcome = self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id, device_id="device-A_aaaaaaaaaaaaaaaa",
        )
        self.assertEqual(outcome["revoked_other_count"], 0)
        self.assertEqual(
            self.db.status(self.vault_id, "device-A_aaaaaaaaaaaaaaaa"),
            "trusted",
        )


# ---------------------------------------------------------------------------
# /devices/register never returns 'pending'
# ---------------------------------------------------------------------------

class DevicesRegisterNeverPendingTests(unittest.TestCase):

    def setUp(self) -> None:
        import device_monitor
        self.device_monitor = device_monitor
        self.db = InMemoryTrustedDevicesDb()
        self._originals = _install_fake_db(self.db)
        self.vault_id = "00000000-0000-4000-8000-0000000000c1"

    def tearDown(self) -> None:
        _restore_get_db(self._originals)

    def test_first_register_returns_trusted(self):
        result = self.device_monitor.register_or_refresh(
            vault_id=self.vault_id,
            device_id="device-fresh_paddingpaddingpaddingpad",
            label="this browser",
            user_agent_brand="Chrome",
            ip_prefix="203.0.113",
        )
        self.assertEqual(result["status"], "trusted")

    def test_second_register_revokes_first(self):
        self.device_monitor.register_or_refresh(
            vault_id=self.vault_id,
            device_id="device-A_paddingpaddingpaddingpaddingpad",
            label=None,
            user_agent_brand=None,
            ip_prefix=None,
        )
        result = self.device_monitor.register_or_refresh(
            vault_id=self.vault_id,
            device_id="device-B_paddingpaddingpaddingpaddingpad",
            label=None,
            user_agent_brand=None,
            ip_prefix=None,
        )
        self.assertEqual(result["status"], "trusted")
        self.assertEqual(
            self.db.status(self.vault_id, "device-A_paddingpaddingpaddingpaddingpad"),
            "revoked",
        )

    def test_register_never_returns_pending(self):
        # Regression guard: under any input shape, /devices/register
        # must never return 'pending' — that was the ed825aa dead
        # end where the client held a session but every subsequent
        # protected request 403'd waiting for older-device approval.
        for i in range(5):
            result = self.device_monitor.register_or_refresh(
                vault_id=self.vault_id,
                device_id=f"device-{i:02d}_paddingpaddingpaddingpaddingp",
                label=None,
                user_agent_brand=None,
                ip_prefix=None,
            )
            self.assertNotEqual(result["status"], "pending")
            self.assertEqual(result["status"], "trusted")


# ---------------------------------------------------------------------------
# device_gate emits device_revoked for revoked rows
# ---------------------------------------------------------------------------

class DeviceGateEmitsRevokedCodeTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        import device_gate
        import device_monitor
        import os
        self.device_gate = device_gate
        self.device_monitor = device_monitor
        self.db = InMemoryTrustedDevicesDb()
        self._originals = _install_fake_db(self.db)
        self.vault_id = "00000000-0000-4000-8000-0000000000d1"
        # Ensure the gate is enforced regardless of local env vars.
        self._saved_env = {
            "VAULTAI_DEVICE_GATE_ENFORCE": os.environ.get(
                "VAULTAI_DEVICE_GATE_ENFORCE"),
            "VAULTAI_DEVICE_GATE_DEV_DISABLE": os.environ.get(
                "VAULTAI_DEVICE_GATE_DEV_DISABLE"),
            "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST": os.environ.get(
                "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST"),
        }
        os.environ["VAULTAI_DEVICE_GATE_ENFORCE"] = "true"
        os.environ.pop("VAULTAI_DEVICE_GATE_DEV_DISABLE", None)
        os.environ.pop("VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST", None)

    def tearDown(self) -> None:
        import os
        _restore_get_db(self._originals)
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    async def test_revoked_device_receives_device_revoked_code(self):
        # Acceptance item 4: device A gets a clear device_revoked
        # response on its next protected request after B logs in.
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id,
            device_id="device-A_paddingpaddingpaddingpaddingpad",
        )
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id,
            device_id="device-B_paddingpaddingpaddingpaddingpad",
        )

        from fastapi import HTTPException, Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/some/protected/route",
            "headers": [
                (b"x-device-id",
                 b"device-A_paddingpaddingpaddingpaddingpad"),
            ],
        }
        request = Request(scope)
        principal = {
            "vault_id":   self.vault_id,
            "vault_name": "test",
            "token_id":   "00000000-0000-4000-8000-00000000eeee",
            "device_id":  None,
        }

        with self.assertRaises(HTTPException) as ctx:
            await self.device_gate.verify_trusted_device(request, principal)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(
            ctx.exception.detail["code"], "device_revoked",
            msg="revoked device must emit `device_revoked`, not the "
                "legacy `device_not_trusted` — the client uses this "
                "code to drop the session and route to /auth.",
        )
        self.assertEqual(ctx.exception.detail["status"], "revoked")

    async def test_missing_row_still_uses_legacy_code(self):
        # Backward compatibility: a request from a device with no row
        # (never registered) still uses the legacy code, so pre-fix
        # client code that handled `device_not_trusted` continues to
        # work for the missing-row edge case.
        from fastapi import HTTPException, Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/some/protected/route",
            "headers": [
                (b"x-device-id",
                 b"unknown-device_paddingpaddingpaddingpaddin"),
            ],
        }
        request = Request(scope)
        principal = {
            "vault_id":   self.vault_id,
            "vault_name": "test",
            "token_id":   "00000000-0000-4000-8000-00000000ffff",
            "device_id":  None,
        }
        with self.assertRaises(HTTPException) as ctx:
            await self.device_gate.verify_trusted_device(request, principal)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(
            ctx.exception.detail["code"], "device_not_trusted",
        )

    async def test_trusted_device_passes_gate(self):
        # Acceptance item 3: device B reaches Chat without the
        # pending-trust screen. Verified here at the gate layer:
        # a trusted device passes verify_trusted_device with no
        # exception raised.
        self.device_monitor.trust_current_and_revoke_others(
            vault_id=self.vault_id,
            device_id="device-B_paddingpaddingpaddingpaddingpad",
        )
        from fastapi import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/some/protected/route",
            "headers": [
                (b"x-device-id",
                 b"device-B_paddingpaddingpaddingpaddingpad"),
            ],
        }
        request = Request(scope)
        principal = {
            "vault_id":   self.vault_id,
            "vault_name": "test",
            "token_id":   "00000000-0000-4000-8000-00000000dead",
            "device_id":  None,
        }
        # Should not raise.
        returned = await self.device_gate.verify_trusted_device(request, principal)
        self.assertIs(returned, principal)


# ---------------------------------------------------------------------------
# ZK finalize wiring — the endpoints hook the primitive
# ---------------------------------------------------------------------------

class ZkFinalizeWiresPrimitiveTests(unittest.TestCase):
    # We assert the source of both zk_register_finalize and
    # zk_login_finalize invokes trust_current_and_revoke_others. This
    # is a shape check — the primitive is proven correct above; the
    # only remaining risk is "we forgot to call it here".

    def test_zk_register_finalize_calls_primitive(self):
        import inspect
        from routes import auth_zk_routes
        src = inspect.getsource(auth_zk_routes.zk_register_finalize)
        self.assertIn(
            "trust_current_and_revoke_others", src,
            msg="zk_register_finalize must call the single-active-device "
                "primitive so the newly-signed-up device is immediately "
                "trusted",
        )
        self.assertIn(
            "payload.device_id", src,
            msg="the primitive must be scoped to the caller's device_id",
        )

    def test_zk_login_finalize_calls_primitive(self):
        import inspect
        from routes import auth_zk_routes
        src = inspect.getsource(auth_zk_routes.zk_login_finalize)
        self.assertIn(
            "trust_current_and_revoke_others", src,
            msg="zk_login_finalize must call the single-active-device "
                "primitive so the newly-logged-in device is trusted and "
                "any other device is revoked",
        )
        self.assertIn(
            "payload.device_id", src,
            msg="the primitive must be scoped to the caller's device_id",
        )


if __name__ == "__main__":
    unittest.main()
