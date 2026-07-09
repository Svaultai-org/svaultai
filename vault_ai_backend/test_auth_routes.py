

from __future__ import annotations

import os
import unittest

                                                                       
_TEST_DB_URL = os.getenv("VAULTAI_TEST_DATABASE_URL", "").strip()
if _TEST_DB_URL:
    os.environ["DATABASE_URL"] = _TEST_DB_URL
    os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
    os.environ.setdefault("VAULTAI_ENV", "dev")
                                                                        
                 
    os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

requires_db = unittest.skipUnless(
    bool(_TEST_DB_URL),
    "VAULTAI_TEST_DATABASE_URL is not set; skipping integration tests",
)


if _TEST_DB_URL:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import auth_local
    from routes.auth_routes import router as auth_router
    from vault_core import MAX_PIN_ATTEMPTS, get_db


def _truncate_auth_state() -> None:

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            TRUNCATE TABLE
                auth_sessions,
                trusted_devices,
                account_storage_totals,
                account_subscriptions,
                account_members,
                vaults,
                accounts
            RESTART IDENTITY CASCADE
            """
        )
        conn.commit()
    finally:
        conn.close()


@requires_db
class AuthRouteIntegrationTests(unittest.TestCase):


    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()
        app.include_router(auth_router)
        cls.app = app
        cls.client = TestClient(app)

    def setUp(self) -> None:
        auth_local.reset_secret_for_tests()
        _truncate_auth_state()


@requires_db
class SignupTests(AuthRouteIntegrationTests):
    def _signup_payload(self, **overrides) -> dict:
        payload = {
            "vault_name": "alice-test",
            "pin": "123456",
            "confirm_pin": "123456",
            "display_username": "Alice",
            "acknowledged_irrecoverable": True,
        }
        payload.update(overrides)
        return payload

    def test_happy_path(self) -> None:
        response = self.client.post("/auth/signup", json=self._signup_payload())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["vault_name"], "alice-test")
        self.assertTrue(body["session_token"])
        self.assertTrue(body["vault_id"])
        self.assertIn("expires_at", body)

    def test_signup_returns_display_username(self) -> None:
                                                                      
                                                                    
        response = self.client.post("/auth/signup", json=self._signup_payload())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertIn("display_username", body)
        self.assertEqual(body["display_username"], "Alice")

    def test_signup_auto_generates_display_username_when_omitted(self) -> None:
                                                                       
                                                                      
        import re

        payload = self._signup_payload()
        payload.pop("display_username", None)
        response = self.client.post("/auth/signup", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        display = body["display_username"]
        self.assertIsNotNone(display, "auto-gen must populate display_username")
        self.assertRegex(
            display,
            r"^User [0-9a-f]{8}$",
            "fallback must be 'User <8 hex chars>' shape",
        )

    def test_signup_auto_display_username_does_not_contain_vault_name(self) -> None:
                                                                
                                                                 
        payload = self._signup_payload(vault_name="hunter2-private-vault")
        payload.pop("display_username", None)
        response = self.client.post("/auth/signup", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        display = response.json()["display_username"]
        self.assertIsNotNone(display)
        self.assertNotIn("hunter2", display)
        self.assertNotIn("private", display)
        self.assertNotIn("vault", display.lower())
        self.assertNotIn("hunter2-private-vault", display)

    def test_signup_auto_display_username_is_stable_for_same_vault(self) -> None:
                                                              
                                                                       
        payload = self._signup_payload()
        payload.pop("display_username", None)
        first = self.client.post("/auth/signup", json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        token = first.json()["session_token"]
        auto = first.json()["display_username"]

        me_resp = self.client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me_resp.status_code, 200, me_resp.text)
        self.assertEqual(me_resp.json()["display_username"], auto)

    def test_signup_explicit_display_username_overrides_auto_gen(self) -> None:
                                                                       
                                                                   
        response = self.client.post("/auth/signup", json=self._signup_payload())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["display_username"], "Alice")

    def test_signup_never_sets_new_device_trusted(self) -> None:
                                                                      
                                                                    
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(),
            headers={"X-Device-Id": "device-fresh-signup"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["new_device_trusted"], False)

    def test_creates_account_member_subscription_rows(self) -> None:
        response = self.client.post("/auth/signup", json=self._signup_payload())
        self.assertEqual(response.status_code, 201, response.text)
        vault_id = response.json()["vault_id"]
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT account_id FROM vaults WHERE vault_id = %s",
                (vault_id,),
            )
            row = cur.fetchone()
            self.assertIsNotNone(row, "vault row not found after signup")
            account_id = row[0]

            cur.execute(
                "SELECT vault_id, role FROM account_members WHERE account_id = %s",
                (account_id,),
            )
            members = cur.fetchall()
            self.assertEqual(len(members), 1)
            self.assertEqual(str(members[0][0]), vault_id)
            self.assertEqual(members[0][1], "owner")

            cur.execute(
                "SELECT status FROM account_subscriptions WHERE account_id = %s",
                (account_id,),
            )
            sub = cur.fetchone()
            self.assertEqual(sub[0], "none")

            cur.execute(
                "SELECT billing_owner_vault_id FROM accounts WHERE account_id = %s",
                (account_id,),
            )
            owner = cur.fetchone()
            self.assertEqual(str(owner[0]), vault_id)
        finally:
            conn.close()

    def test_duplicate_vault_name_returns_409(self) -> None:
        self.client.post("/auth/signup", json=self._signup_payload())
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(pin="654321", confirm_pin="654321"),
        )
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "vault_name_taken")

    def test_acknowledgement_required(self) -> None:
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(acknowledged_irrecoverable=False),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"]["code"], "acknowledgement_required",
        )

    def test_pin_confirm_must_match(self) -> None:
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(confirm_pin="999999"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "pin_mismatch")

    def test_pin_too_short(self) -> None:
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(pin="123", confirm_pin="123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_pin_non_numeric(self) -> None:
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(pin="abcdef", confirm_pin="abcdef"),
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_vault_name(self) -> None:
        for bad in ("", "A", "ab", "has spaces", "weird!", "x" * 200):
            with self.subTest(name=bad):
                response = self.client.post(
                    "/auth/signup", json=self._signup_payload(vault_name=bad),
                )
                self.assertGreaterEqual(response.status_code, 400)

    def test_vault_name_is_lowercased(self) -> None:
                                                                  
                                                        
        response = self.client.post(
            "/auth/signup",
            json=self._signup_payload(vault_name="Alice-Mixed"),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["vault_name"], "alice-mixed")

                                                         
        dup = self.client.post(
            "/auth/signup",
            json=self._signup_payload(vault_name="alice-MIXED"),
        )
        self.assertEqual(dup.status_code, 409)


@requires_db
class LoginTests(AuthRouteIntegrationTests):
    def _create_vault(
        self,
        vault_name: str = "bob-test",
        pin: str = "987654",
    ) -> str:
        response = self.client.post(
            "/auth/signup",
            json={
                "vault_name": vault_name,
                "pin": pin,
                "confirm_pin": pin,
                "acknowledged_irrecoverable": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["vault_id"]

    def test_happy_path(self) -> None:
        self._create_vault()
        response = self.client.post(
            "/auth/login",
            json={"vault_name": "bob-test", "pin": "987654"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["session_token"])
        self.assertEqual(response.json()["vault_name"], "bob-test")

    def test_login_returns_display_username(self) -> None:
                                                                     
                                                                        
        self.client.post(
            "/auth/signup",
            json={
                "vault_name": "dora-test",
                "pin": "987654",
                "confirm_pin": "987654",
                "display_username": "Dora",
                "acknowledged_irrecoverable": True,
            },
        )
        response = self.client.post(
            "/auth/login",
            json={"vault_name": "dora-test", "pin": "987654"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["display_username"], "Dora")

    def test_login_returns_auto_display_username_when_signup_omitted_it(self) -> None:
                                                              
                                                                 
        import re

        signup = self.client.post(
            "/auth/signup",
            json={
                "vault_name": "edgar-test",
                "pin": "987654",
                "confirm_pin": "987654",
                "acknowledged_irrecoverable": True,
            },
        )
        self.assertEqual(signup.status_code, 201, signup.text)
        auto = signup.json()["display_username"]
        self.assertIsNotNone(auto)
        self.assertRegex(auto, r"^User [0-9a-f]{8}$")

        response = self.client.post(
            "/auth/login",
            json={"vault_name": "edgar-test", "pin": "987654"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["display_username"], auto)
                                                                   
                                
        self.assertNotIn("edgar", response.json()["display_username"])

    def test_login_first_device_sets_new_device_trusted(self) -> None:
                                                                        
                                                                      
        self._create_vault(vault_name="newdev-test")
        response = self.client.post(
            "/auth/login",
            json={"vault_name": "newdev-test", "pin": "987654"},
            headers={"X-Device-Id": "device-X"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["new_device_trusted"], True)

    def test_login_repeat_same_device_clears_new_device_trusted(self) -> None:
                                                                    
                                                                    
        self._create_vault(vault_name="repeatdev-test")
        first = self.client.post(
            "/auth/login",
            json={"vault_name": "repeatdev-test", "pin": "987654"},
            headers={"X-Device-Id": "device-Y"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["new_device_trusted"], True)

        second = self.client.post(
            "/auth/login",
            json={"vault_name": "repeatdev-test", "pin": "987654"},
            headers={"X-Device-Id": "device-Y"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["new_device_trusted"], False)

    def test_login_different_device_sets_new_device_trusted(self) -> None:
                                                                    
                                                                    
        self._create_vault(vault_name="multidev-test")
        self.client.post(
            "/auth/login",
            json={"vault_name": "multidev-test", "pin": "987654"},
            headers={"X-Device-Id": "device-Y"},
        )
        z = self.client.post(
            "/auth/login",
            json={"vault_name": "multidev-test", "pin": "987654"},
            headers={"X-Device-Id": "device-Z"},
        )
        self.assertEqual(z.status_code, 200, z.text)
        self.assertEqual(z.json()["new_device_trusted"], True)

    def test_login_no_device_id_header_clears_new_device_trusted(self) -> None:
                                                                       
                                                                       
        self._create_vault(vault_name="noid-test")
        r = self.client.post(
            "/auth/login",
            json={"vault_name": "noid-test", "pin": "987654"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["new_device_trusted"], False)

    def test_wrong_pin_returns_generic_401(self) -> None:
        self._create_vault()
        response = self.client.post(
            "/auth/login",
            json={"vault_name": "bob-test", "pin": "111111"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Vault name or PIN is incorrect")

    def test_nonexistent_vault_returns_same_generic_401(self) -> None:
                                                                        
                                                                       
        response = self.client.post(
            "/auth/login",
            json={"vault_name": "does-not-exist", "pin": "111111"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Vault name or PIN is incorrect")

    def test_lockout_after_max_wrong_pin_attempts(self) -> None:
        self._create_vault(vault_name="lock-test", pin="424242")
        for _ in range(MAX_PIN_ATTEMPTS):
            r = self.client.post(
                "/auth/login",
                json={"vault_name": "lock-test", "pin": "000000"},
            )
            self.assertEqual(r.status_code, 401)
                                                                        
                                                                           
        r = self.client.post(
            "/auth/login",
            json={"vault_name": "lock-test", "pin": "424242"},
        )
        self.assertEqual(r.status_code, 423)
        self.assertEqual(r.json()["detail"]["code"], "pin_locked")

    def test_login_resets_failed_attempts(self) -> None:
        self._create_vault(vault_name="reset-test", pin="246810")
                                                
        self.client.post(
            "/auth/login",
            json={"vault_name": "reset-test", "pin": "000000"},
        )
                                                 
        r = self.client.post(
            "/auth/login",
            json={"vault_name": "reset-test", "pin": "246810"},
        )
        self.assertEqual(r.status_code, 200)
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT failed_pin_attempts FROM vaults WHERE vault_name = %s",
                ("reset-test",),
            )
            row = cur.fetchone()
            self.assertEqual(row[0], 0)
        finally:
            conn.close()


@requires_db
class MeAndLogoutTests(AuthRouteIntegrationTests):
    def _signup_and_get_token(self) -> str:
        response = self.client.post(
            "/auth/signup",
            json={
                "vault_name": "carol-test",
                "pin": "135790",
                "confirm_pin": "135790",
                "display_username": "Carol",
                "acknowledged_irrecoverable": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["session_token"]

    def test_me_returns_principal(self) -> None:
        token = self._signup_and_get_token()
        r = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["vault_name"], "carol-test")
        self.assertEqual(body["display_username"], "Carol")

    def test_me_rejects_missing_token(self) -> None:
        r = self.client.get("/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_me_rejects_garbage_token(self) -> None:
        r = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        self.assertEqual(r.status_code, 401)

    def test_logout_revokes_session(self) -> None:
        token = self._signup_and_get_token()
        r = self.client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r.status_code, 204)
                                         
        r2 = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r2.status_code, 401)


if __name__ == "__main__":
    unittest.main()
