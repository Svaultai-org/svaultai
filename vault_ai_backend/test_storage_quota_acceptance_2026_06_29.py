

from __future__ import annotations

import inspect
import logging
import os
import unittest
from typing import Optional
from unittest import mock


os.environ.setdefault("DATABASE_URL", "postgresql://noop:noop@localhost/noop")
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

import billing              
from billing import (              
    DEFAULT_FREE_STORAGE_BYTES,
    DEFAULT_INCLUDED_BYTES,
    StorageEntitlement,
    get_effective_storage_limit,
    get_storage_used_bytes,
    included_bytes,
)


def _free_tier_entitlement(account_id: str, used: int = 0) -> StorageEntitlement:
    inc = included_bytes()
    return StorageEntitlement(
        account_id=account_id,
        account_type="individual",
        sales_channel="self_service",
        included_bytes=inc,
        purchased_bytes=0,
        storage_bytes_grant=0,
        effective_limit_bytes=inc,
        used_bytes=used,
        percent_used=0.0,
        block_count=0,
        self_service_max_blocks=100,
        status="none",
        source="none",
        current_period_end=None,
        cancel_at_period_end=False,
        block_price_cents_usd=2500,
        block_bytes=53_687_091_200,
        has_active_subscription=False,
    )


def _paid_entitlement(
    account_id: str, block_count: int = 1, used: int = 0,
) -> StorageEntitlement:
    inc = included_bytes()
    block = 53_687_091_200
    purchased = block_count * block
    return StorageEntitlement(
        account_id=account_id,
        account_type="individual",
        sales_channel="self_service",
        included_bytes=inc,
        purchased_bytes=purchased,
        storage_bytes_grant=0,
        effective_limit_bytes=purchased,
        used_bytes=used,
        percent_used=0.0,
        block_count=block_count,
        self_service_max_blocks=100,
        status="active",
        source="stripe",
        current_period_end=None,
        cancel_at_period_end=False,
        block_price_cents_usd=2500,
        block_bytes=block,
        has_active_subscription=True,
    )


def _canceled_entitlement(account_id: str) -> StorageEntitlement:


    inc = included_bytes()
    return StorageEntitlement(
        account_id=account_id,
        account_type="individual",
        sales_channel="self_service",
        included_bytes=inc,
        purchased_bytes=0,
        storage_bytes_grant=0,
        effective_limit_bytes=inc,
        used_bytes=0,
        percent_used=0.0,
        block_count=2,
        self_service_max_blocks=100,
        status="expired",
        source="stripe",
        current_period_end=None,
        cancel_at_period_end=True,
        block_price_cents_usd=2500,
        block_bytes=53_687_091_200,
        has_active_subscription=False,
    )


class TestFreeTierDefaultIsExactly1GB(unittest.TestCase):

    def test_default_free_storage_bytes_constant_is_1gib(self) -> None:
                                                                      
                                                     
        self.assertEqual(DEFAULT_FREE_STORAGE_BYTES, 1_073_741_824)
                                                                    
                                                    
        self.assertEqual(
            DEFAULT_FREE_STORAGE_BYTES, DEFAULT_INCLUDED_BYTES,
            msg=(
                "DEFAULT_FREE_STORAGE_BYTES must equal "
                "DEFAULT_INCLUDED_BYTES — same number, two names."
            ),
        )

    def test_included_bytes_runtime_returns_positive(self) -> None:
                                                                    
                                                         
        val = included_bytes()
        self.assertGreater(val, 0)

    def test_no_subscription_row_returns_free_tier_limit(self) -> None:
                                                                  
                                                                    
        with mock.patch.object(
            billing, "get_entitlement",
            return_value=_free_tier_entitlement("acct-1"),
        ):
            limit = get_effective_storage_limit("acct-1")
        self.assertEqual(limit, DEFAULT_FREE_STORAGE_BYTES)

    def test_none_account_id_returns_free_tier_limit(self) -> None:
                                                                   
                                                                
        self.assertEqual(
            get_effective_storage_limit(None), DEFAULT_FREE_STORAGE_BYTES,
        )
        self.assertEqual(
            get_effective_storage_limit(""), DEFAULT_FREE_STORAGE_BYTES,
        )

    def test_entitlement_errored_lookup_returns_free_tier_limit(self) -> None:
                                                                    
                                       
        with mock.patch.object(
            billing, "get_entitlement",
            side_effect=RuntimeError("transient DB error"),
        ):
            limit = get_effective_storage_limit("acct-x")
        self.assertEqual(limit, DEFAULT_FREE_STORAGE_BYTES)

    def test_get_entitlement_missing_account_returns_free_tier(self) -> None:
                                                                  
                                                                     
        src = inspect.getsource(billing.get_entitlement)
        self.assertIn("included_bytes=inc", src)
        self.assertIn("effective_limit_bytes=inc", src)
        self.assertIn("used_bytes=0", src)
        self.assertIn("has_active_subscription=False", src)

    def test_free_user_does_not_need_stripe(self) -> None:
                                                                     
                                                           
        src = inspect.getsource(billing.get_entitlement)
        self.assertIn(
            "if block_count_val > 0 and purchased_active > 0:",
            src,
            msg=(
                "Free-tier branch must be gated only by block_count + "
                "purchased — Stripe presence/absence must not gate "
                "the free 1 GB."
            ),
        )


class TestUsedBytesStartsAtZero(unittest.TestCase):

    def test_get_storage_used_bytes_zero_for_new_account(self) -> None:
        with mock.patch.object(
            billing, "get_entitlement",
            return_value=_free_tier_entitlement("acct-new", used=0),
        ):
            self.assertEqual(get_storage_used_bytes("acct-new"), 0)

    def test_get_storage_used_bytes_none_account_id_returns_zero(self) -> None:
        self.assertEqual(get_storage_used_bytes(None), 0)
        self.assertEqual(get_storage_used_bytes(""), 0)

    def test_get_storage_used_bytes_errored_lookup_returns_zero(self) -> None:
                                                                    
        with mock.patch.object(
            billing, "get_entitlement",
            side_effect=RuntimeError("transient DB error"),
        ):
            self.assertEqual(get_storage_used_bytes("acct-x"), 0)

    def test_get_storage_used_bytes_negative_clamps_to_zero(self) -> None:
                                                                      
                                                           
        ent = _free_tier_entitlement("acct-corrupt", used=-42)
        ent = ent.__class__(                                    
            **{**ent.__dict__, "used_bytes": -42}
        )
        with mock.patch.object(
            billing, "get_entitlement", return_value=ent,
        ):
            self.assertEqual(get_storage_used_bytes("acct-corrupt"), 0)


class TestSavePathsReachCounter(unittest.TestCase):


    def test_save_secret_tool_calls_bump_on_write(self) -> None:
                                                                     
                                                                    
        import main
        src = inspect.getsource(main.save_secret_tool)
        self.assertIn(
            "bump_vault_total_bytes", src,
            msg=(
                "save_secret_tool must call bump_vault_total_bytes "
                "after every persisted secret — the closed-set name "
                "that account accounting depends on."
            ),
        )
                                                               
                                                         
        self.assertRegex(
            src, r"previous_size",
            msg="save_secret_tool must read previous_size to compute delta",
        )

    def test_secure_item_save_module_calls_bump(self) -> None:
                                                                        
                                                                     
        import vault_secure_item_save as vsi
        src = inspect.getsource(vsi)
        self.assertIn("bump_vault_total_bytes", src)

    def test_update_secure_item_route_bumps_by_delta(self) -> None:
                                                                      
                                                                     
        from routes import login_routes
        src = inspect.getsource(login_routes)
        self.assertIn("bump_vault_total_bytes", src)
                                                                     
                                                                
        self.assertRegex(
            src,
            r"delta\s*=\s*[^=\n]*new_blob_size[^=\n]*-\s*"
            r"[^=\n]*existing_blob_size",
            msg=(
                "/update-secure-item must compute delta = new_blob_size "
                "- existing_blob_size and pass the signed delta to "
                "bump_vault_total_bytes."
            ),
        )

    def test_delete_secure_item_route_debits_freed_bytes(self) -> None:
                                                                      
                                                                      
        from routes import login_routes
        src = inspect.getsource(login_routes)
                                                             
        self.assertRegex(
            src, r"bump_vault_total_bytes\([^)]*-\s*",
            msg=(
                "/delete-secure-item must call bump_vault_total_bytes "
                "with a negative delta to debit the freed bytes."
            ),
        )

    def test_save_uploaded_file_calls_bump(self) -> None:
                                                                    
                      
        import main
        src = inspect.getsource(main.save_uploaded_file)
        self.assertIn("bump_vault_total_bytes", src)


class TestQuotaGatesBeforeWrite(unittest.TestCase):


    def test_save_secret_tool_blocks_when_over_quota(self) -> None:
                                                                     
                                                                 
        import main
        src = inspect.getsource(main.save_secret_tool)
                                                                 
        self.assertIn("get_entitlement", src)
                                                                  
        self.assertRegex(
            src, r"projected_total\s*>\s*_billing_limit",
            msg=(
                "save_secret_tool must raise on projected_total > "
                "_billing_limit before encrypting / writing the row."
            ),
        )
                                                                      
        self.assertIn("SaveSecretStorageLimitError", src)

    def test_save_uploaded_file_blocks_when_over_quota(self) -> None:
                                                                  
        import main
        src = inspect.getsource(main.save_uploaded_file)
        self.assertIn("get_entitlement", src)
                                                
        self.assertIn("vault_storage_limit_exceeded", src)

    def test_chunked_upload_route_gates_quota(self) -> None:
                                                                     
                                                                      
        from routes import chunked_upload_routes
        src = inspect.getsource(chunked_upload_routes)
        self.assertIn("get_entitlement", src)


class TestLegacyRoutesUseBillingLimit(unittest.TestCase):


    def test_vault_stats_route_uses_billing_helper(self) -> None:
                                                                    
                                                                        
        import main
        src = inspect.getsource(main.vault_stats_endpoint)
        self.assertIn(
            "get_effective_storage_limit", src,
            msg=(
                "/vault-stats must consult the billing helper for "
                "storage_limit_bytes; surfacing MAX_VAULT_BYTES "
                "directly is the flash bug a paid user sees."
            ),
        )
                                                                  
                                                                
        executable = _strip_python_comments(src)
        self.assertNotIn(
            '"storage_limit_bytes": MAX_VAULT_BYTES', executable,
            msg=(
                "/vault-stats must not surface MAX_VAULT_BYTES as "
                "storage_limit_bytes."
            ),
        )

    def test_security_center_summary_uses_billing_helper(self) -> None:
                                                                
                                                    
        from routes import security_center_routes
        src = inspect.getsource(security_center_routes)
        self.assertIn(
            "_effective_storage_limit_for_vault", src,
            msg=(
                "Security center summary must call the billing-driven "
                "helper for storage.limit_bytes, not MAX_VAULT_BYTES."
            ),
        )
                                                                   
                                                                   
        executable = _strip_python_comments(src)
        self.assertNotIn(
            '"limit_bytes": MAX_VAULT_BYTES,', executable,
            msg=(
                "Security center storage card must not bind "
                "limit_bytes directly to MAX_VAULT_BYTES."
            ),
        )

    def test_security_center_empty_state_uses_billing_helper(self) -> None:
                                                                     
                                                                     
        from routes import security_center_routes
        src = inspect.getsource(
            security_center_routes._empty_security_center_summary,
        )
                                                                 
                                                 
        self.assertRegex(
            src, r"def _empty_security_center_summary\(\s*vault_id",
        )
        self.assertIn(
            "_effective_storage_limit_for_vault", src,
            msg=(
                "Empty-state security-center summary must consult the "
                "billing helper for limit_bytes — never surface 0 as "
                "the storage limit."
            ),
        )


def _strip_python_comments(src: str) -> str:


    import re
                                                            
    src = re.sub(r'"""[\s\S]*?"""', "", src)
                                   
    src = re.sub(r"'''[\s\S]*?'''", "", src)
                                       
    src = re.sub(r"#[^\n]*", "", src)
    return src


class TestPaidAndExpiredEntitlements(unittest.TestCase):

    def test_active_paid_subscription_overrides_default(self) -> None:
                                                           
        with mock.patch.object(
            billing, "get_entitlement",
            return_value=_paid_entitlement("acct-paid", block_count=1),
        ):
            limit = get_effective_storage_limit("acct-paid")
                                                                      
        self.assertEqual(limit, 53_687_091_200)
        self.assertGreater(limit, DEFAULT_FREE_STORAGE_BYTES)

    def test_canceled_subscription_falls_back_to_free_tier(self) -> None:
                                                                    
                                                                     
        with mock.patch.object(
            billing, "get_entitlement",
            return_value=_canceled_entitlement("acct-canceled"),
        ):
            limit = get_effective_storage_limit("acct-canceled")
        self.assertEqual(limit, DEFAULT_FREE_STORAGE_BYTES)

    def test_entitlement_zero_limit_snaps_to_free_floor(self) -> None:
                                                          
                                                                   
        ent = _free_tier_entitlement("acct-broken")
        ent_zero = ent.__class__(
            **{**ent.__dict__, "effective_limit_bytes": 0}
        )
        with mock.patch.object(
            billing, "get_entitlement", return_value=ent_zero,
        ):
            self.assertEqual(
                get_effective_storage_limit("acct-broken"),
                DEFAULT_FREE_STORAGE_BYTES,
            )


class TestNoSecretsInLogs(unittest.TestCase):

    def test_helpers_emit_no_secrets_into_logs(self) -> None:
                                                                    
                                                                  
        sink = _CapturingHandler()
        billing_logger = logging.getLogger("billing")
        root_logger = logging.getLogger()
        billing_logger.addHandler(sink)
        root_logger.addHandler(sink)
        prior_b = billing_logger.level
        prior_r = root_logger.level
        billing_logger.setLevel(logging.DEBUG)
        root_logger.setLevel(logging.DEBUG)
        try:
                                                            
            get_effective_storage_limit(None)
            get_storage_used_bytes(None)
            with mock.patch.object(
                billing, "get_entitlement",
                side_effect=RuntimeError("simulated"),
            ):
                get_effective_storage_limit("acct-secret-value-zzz")
                get_storage_used_bytes("acct-secret-value-zzz")
                                                                  
                                                                    
            for rec in sink.records:
                body = rec.getMessage()
                self.assertNotIn(
                    "secret-value-zzz", body,
                    msg=(
                        "Quota helper leaked account-id suffix into log "
                        f"line: {body!r}"
                    ),
                )
        finally:
            billing_logger.removeHandler(sink)
            root_logger.removeHandler(sink)
            billing_logger.setLevel(prior_b)
            root_logger.setLevel(prior_r)


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:              
        self.records.append(record)


if __name__ == "__main__":                    
    unittest.main()
