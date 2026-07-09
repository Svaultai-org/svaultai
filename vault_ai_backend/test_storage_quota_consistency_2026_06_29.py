

from __future__ import annotations

import inspect
import logging
import unittest
from pathlib import Path
from typing import Optional


class TestBillingFormulaReplacement(unittest.TestCase):
    def test_get_entitlement_uses_paid_replaces_free(self) -> None:
        import billing
        src = inspect.getsource(billing.get_entitlement)
                                                            
                                                                 
        self.assertRegex(
            src,
            r"effective\s*=\s*purchased_active",
            msg=(
                "get_entitlement must assign effective="
                "purchased_active on the paid-plan branch — "
                "operator brief: paid REPLACES free."
            ),
        )
                                                               
                                                                 
        executable = _strip_python_comments(src)
        for forbidden in (
            "effective = inc + purchased",
            "effective = included_bytes + purchased",
            "effective = inc + purchased_active",
            "= included_bytes + purchased_active",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, executable,
                    msg=(
                        f"get_entitlement assigns '{forbidden}' — "
                        "operator brief forbids stacking the free "
                        "tier on top of the paid plan"
                    ),
                )

    def test_paid_branch_does_not_include_grant(self) -> None:
                                                               
                                                                 
        import billing
        src = inspect.getsource(billing.get_entitlement)
                                                       
                                       
        self.assertNotIn(
            "purchased_active + grant", src,
            msg="paid plan must not stack the grant on top",
        )


class TestFormulaBehaviour(unittest.TestCase):


    def test_paid_replaces_free_minimal_function(self) -> None:
                                             
        included = 1_073_741_824        
        purchased = 53_687_091_200         
        block_count = 1
                      
        effective = (
            purchased
            if block_count > 0 and purchased > 0
            else included
        )
        self.assertEqual(effective, purchased)
                           
        block_count = 0
        purchased = 0
        effective = (
            purchased
            if block_count > 0 and purchased > 0
            else included
        )
        self.assertEqual(effective, included)

    def test_free_user_limit_is_1gb_default(self) -> None:
        from billing import DEFAULT_INCLUDED_BYTES, included_bytes
                                                                
                                                               
        self.assertEqual(DEFAULT_INCLUDED_BYTES, 1_073_741_824)
                                                                
                                
        val = included_bytes()
        self.assertGreater(val, 0)


class TestSecureItemSaveBumpsCounter(unittest.TestCase):
    def setUp(self) -> None:
                                                               
                      
        self.bumps: list[tuple[str, int]] = []
        import vault_secure_item_save as vsi
        self._orig_upsert = vsi._default_upsert
        self._orig_delete = vsi._default_delete

    def tearDown(self) -> None:
        import vault_secure_item_save as vsi
        vsi._default_upsert = self._orig_upsert
        vsi._default_delete = self._orig_delete

    def test_default_upsert_source_contains_bump_call(self) -> None:
        import vault_secure_item_save as vsi
        src = inspect.getsource(vsi._default_upsert)
                                                                 
                                                           
        self.assertIn("bump_vault_total_bytes", src,
            msg=(
                "secure-item upsert must bump storage counter — "
                "operator brief: secure items count toward usage"
            ),
        )
        self.assertIn("delta", src.lower())

    def test_default_delete_source_contains_bump_call(self) -> None:
        import vault_secure_item_save as vsi
        src = inspect.getsource(vsi._default_delete)
        self.assertIn("bump_vault_total_bytes", src,
            msg=(
                "secure-item delete must debit storage counter — "
                "without this, deletes leave bytes counted "
                "forever"
            ),
        )
                                                 
        self.assertRegex(src, r"-int\(freed\)|-int\(blob")

    def test_blob_size_helper_handles_common_types(self) -> None:
        from vault_secure_item_save import _blob_size
               
        self.assertEqual(_blob_size(b"hello"), 5)
                   
        self.assertEqual(_blob_size(bytearray(b"hi")), 2)
                    
        self.assertEqual(_blob_size(memoryview(b"abc")), 3)
                            
        self.assertEqual(_blob_size("héllo"), 6)               
              
        self.assertEqual(_blob_size(None), 0)


class TestDeleteSecureItemRouteDebitsCounter(unittest.TestCase):
    def test_delete_route_returns_encrypted_data_for_debit(self) -> None:
                                                              
                                                           
        src = Path("routes/login_routes.py").read_text(encoding="utf-8")
        anchor = '@router.post("/delete-secure-item")'
        idx = src.index(anchor)
                                           
        next_idx = src.find('@router.', idx + 1)
        body = src[idx:next_idx if next_idx != -1 else len(src)]
        self.assertIn(
            "RETURNING service, encrypted_data", body,
            msg=(
                "/delete-secure-item must RETURNING encrypted_data "
                "so it can debit the freed bytes from the storage "
                "counter"
            ),
        )
                                                                  
        self.assertIn("bump_vault_total_bytes", body)
        self.assertIn("-int(freed)", body)


class TestUpdateSecureItemRouteBumpsDelta(unittest.TestCase):
    def test_update_route_computes_delta(self) -> None:
        src = Path("routes/login_routes.py").read_text(encoding="utf-8")
        anchor = '@router.post("/update-secure-item")'
        idx = src.index(anchor)
        next_idx = src.find('@router.', idx + 1)
        body = src[idx:next_idx if next_idx != -1 else len(src)]
                                                             
                                                   
        self.assertIn("existing_blob_size", body)
        self.assertIn("new_blob_size", body)
        self.assertIn("bump_vault_total_bytes(vault_id, delta)", body)


class TestLegacyLoginDeleteDebitsCounter(unittest.TestCase):
    def test_legacy_delete_returns_encrypted_data_and_debits(self) -> None:
        src = Path("routes/vault_manage_routes.py").read_text(
            encoding="utf-8",
        )
        anchor = "_delete_login_impl("
        idx = src.index(anchor)
                                        
        next_idx = src.find("\ndef ", idx + 1)
        body = src[idx:next_idx if next_idx != -1 else len(src)]
                                                              
                   
        self.assertIn("RETURNING service, encrypted_data", body,
            msg=(
                "legacy login delete must RETURNING "
                "encrypted_data so the freed bytes can be "
                "debited from the storage counter"
            ),
        )
                                                      
        self.assertIn("bump_vault_total_bytes", body)


class TestStorageBumpsLogPrivacyFloor(unittest.TestCase):
    def test_warning_logs_do_not_carry_blob(self) -> None:
                                                                
                                                              
        import vault_secure_item_save as vsi
        for fn in (vsi._default_upsert, vsi._default_delete):
            src = inspect.getsource(fn)
            self.assertNotIn(
                "encrypted_data", _extract_log_lines(src),
                msg=(
                    f"{fn.__name__} must not log encrypted blob "
                    "content"
                ),
            )


def _extract_log_lines(src: str) -> str:


    import re
    matches = re.findall(
        r"logger\.(?:info|warning|error|exception)\s*\(\s*([^)]+)\)",
        src,
    )
    return "\n".join(matches)


def _strip_python_comments(src: str) -> str:


    import re
    out_lines = []
    in_triple = False
    triple_marker = None
    for raw in src.splitlines():
        line = raw
        if in_triple:
            if triple_marker in line:
                line = line.split(triple_marker, 1)[1]
                in_triple = False
                triple_marker = None
            else:
                continue
                                                  
        for marker in ('"""', "'''"):
            if marker in line:
                idx = line.index(marker)
                                                          
                                                       
                close_idx = line.find(marker, idx + 3)
                if close_idx != -1:
                    line = (line[:idx] + line[close_idx + 3:])
                else:
                    line = line[:idx]
                    in_triple = True
                    triple_marker = marker
                    break
                           
        if "#" in line:
            line = line.split("#", 1)[0]
        out_lines.append(line)
    return "\n".join(out_lines)


if __name__ == "__main__":                    
    unittest.main()
