

import unittest

from device_gate import ROUTES_EXEMPT_FROM_DEVICE_GATE


class DeviceGateExemptionTests(unittest.TestCase):

                                                                        
    def test_auth_signup_is_exempt(self):
        self.assertIn("/auth/signup", ROUTES_EXEMPT_FROM_DEVICE_GATE)

    def test_auth_login_is_exempt(self):
        self.assertIn("/auth/login", ROUTES_EXEMPT_FROM_DEVICE_GATE)

    def test_auth_me_is_exempt(self):
                                                                       
                                                                       
        self.assertIn("/auth/me", ROUTES_EXEMPT_FROM_DEVICE_GATE)

    def test_auth_logout_is_exempt(self):
                                                                    
                                                                  
        self.assertIn("/auth/logout", ROUTES_EXEMPT_FROM_DEVICE_GATE)

                                                                        
    def test_device_register_is_exempt(self):
                                                                  
                                                                 
        self.assertIn("/devices/register", ROUTES_EXEMPT_FROM_DEVICE_GATE)

    def test_devices_me_is_exempt(self):
                                                                      
                                                                        
        self.assertIn("/devices/me", ROUTES_EXEMPT_FROM_DEVICE_GATE)

    def test_diagnose_trust_is_exempt(self):
                                                               
                                                                     
        self.assertIn(
            "/devices/diagnose-trust", ROUTES_EXEMPT_FROM_DEVICE_GATE,
        )

    def test_dev_cleanup_pending_is_exempt(self):
                                                                   
                                                                      
        self.assertIn(
            "/devices/dev/cleanup-pending", ROUTES_EXEMPT_FROM_DEVICE_GATE,
        )

    def test_dev_reset_trust_state_is_exempt(self):
                                                                 
                                                                     
        self.assertIn(
            "/devices/dev/reset-trust-state",
            ROUTES_EXEMPT_FROM_DEVICE_GATE,
        )

                                                                        
    def test_stripe_webhook_is_exempt(self):
                                                                     
                                                                      
        self.assertIn(
            "/billing/stripe/webhook", ROUTES_EXEMPT_FROM_DEVICE_GATE,
        )

                                                                         
    def test_legacy_verify_pin_route_is_NOT_exempt(self):
                                                                   
                                                                      
        self.assertNotIn("/verify-pin", ROUTES_EXEMPT_FROM_DEVICE_GATE)

    def test_legacy_my_vault_route_is_NOT_exempt(self):
                                                                  
        self.assertNotIn("/my-vault", ROUTES_EXEMPT_FROM_DEVICE_GATE)

                                                                        
    def test_sensitive_vault_routes_are_NOT_exempt(self):
                                                                   
                                                                 
        for path in (
            "/chat",
            "/save-data",
            "/retrieve-data",
            "/upload-file",
            "/retrieve-file",
            "/list-secrets",
        ):
            with self.subTest(path=path):
                self.assertNotIn(path, ROUTES_EXEMPT_FROM_DEVICE_GATE)

                                                                        
    def test_exempt_set_matches_locked_inventory(self):
                                                                    
                                                               
        self.assertEqual(
            ROUTES_EXEMPT_FROM_DEVICE_GATE,
            frozenset({
                "/auth/signup",
                "/auth/login",
                "/auth/me",
                "/auth/logout",
                "/devices/register",
                "/devices/me",
                "/devices/diagnose-trust",
                "/devices/dev/cleanup-pending",
                "/devices/dev/reset-trust-state",
                "/billing/stripe/webhook",
            }),
        )


if __name__ == "__main__":
    unittest.main()
