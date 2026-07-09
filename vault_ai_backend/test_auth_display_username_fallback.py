

from __future__ import annotations

import re
import unittest

from routes.auth_routes import (
    _default_display_username,
    _DISPLAY_USERNAME_FALLBACK_PREFIX_LEN,
)


class DefaultDisplayUsernameFallbackTests(unittest.TestCase):
    def test_shape_is_user_plus_eight_hex_chars(self) -> None:
        name = _default_display_username("11111111-2222-3333-4444-555555555555")
        self.assertRegex(name, r"^User [0-9a-f]{8}$")

    def test_prefix_length_constant_matches_format(self) -> None:
                                                                     
                                                                      
        self.assertEqual(_DISPLAY_USERNAME_FALLBACK_PREFIX_LEN, 8)
        name = _default_display_username("aabbccdd-eeff-1122-3344-556677889900")
        prefix = name.removeprefix("User ")
        self.assertEqual(len(prefix), _DISPLAY_USERNAME_FALLBACK_PREFIX_LEN)

    def test_is_deterministic_for_same_vault_id(self) -> None:
                                                                    
                                                                       
        vid = "aabbccdd-eeff-1122-3344-556677889900"
        self.assertEqual(
            _default_display_username(vid),
            _default_display_username(vid),
        )

    def test_strips_uuid_hyphens(self) -> None:
                                                                      
                                                                   
        name = _default_display_username("11111111-2222-3333-4444-555555555555")
        self.assertEqual(name, "User 11111111")

    def test_never_contains_vault_name_input(self) -> None:
                                                                      
                                                                   
        import inspect
        sig = inspect.signature(_default_display_username)
        param_names = list(sig.parameters.keys())
        self.assertEqual(
            param_names,
            ["vault_id"],
            "fallback must only accept vault_id, never vault_name",
        )

    def test_does_not_leak_user_chosen_strings(self) -> None:
                                                                   
                                                                
        leaks = ["hunter2", "private", "brain", "secret", "password"]
        for vid in [
            "00000000-0000-0000-0000-000000000000",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "deadbeef-dead-beef-dead-beefdeadbeef",
        ]:
            name = _default_display_username(vid)
            for leak in leaks:
                self.assertNotIn(
                    leak,
                    name.lower(),
                    f"fallback leaked '{leak}' for vault_id={vid}",
                )

    def test_output_fits_db_check_constraint(self) -> None:
                                                                 
                                                                   
        name = _default_display_username("11111111-2222-3333-4444-555555555555")
        self.assertGreaterEqual(len(name), 1)
        self.assertLessEqual(len(name), 200)


if __name__ == "__main__":
    unittest.main()
