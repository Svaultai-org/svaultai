

from __future__ import annotations

import ast
import pathlib
import unittest
from dataclasses import fields as dataclass_fields

from billing import (
    DEFAULT_BLOCK_BYTES,
    DEFAULT_BLOCK_PRICE_CENTS_USD,
    DEFAULT_INCLUDED_BYTES,
    DEFAULT_SELF_SERVICE_MAX_BLOCKS,
    StorageEntitlement,
    _purchased_bytes_active,
    block_count_to_price_cents,
    blocks_to_bytes,
    compute_percent_used,
    is_within_self_service_ceiling,
)


_BASELINE_MIGRATION = "0001_baseline_vaultid.py"
MIGRATION_PATH = (
    pathlib.Path(__file__).parent
    / "migrations" / "versions" / _BASELINE_MIGRATION
)


class MigrationConstantsMatchBillingDefaults(unittest.TestCase):


    @classmethod
    def setUpClass(cls):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls.constants: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, int):
                        cls.constants[tgt.id] = node.value.value

    def test_included_bytes_matches(self):
        self.assertEqual(
            self.constants.get("INCLUDED_BYTES"),
            DEFAULT_INCLUDED_BYTES,
            "Migration 0026 INCLUDED_BYTES drifted from billing.py "
            "DEFAULT_INCLUDED_BYTES — update both together.",
        )

    def test_block_bytes_matches(self):
        self.assertEqual(
            self.constants.get("BLOCK_BYTES"),
            DEFAULT_BLOCK_BYTES,
            "Migration 0026 BLOCK_BYTES drifted from billing.py "
            "DEFAULT_BLOCK_BYTES.",
        )

    def test_block_price_cents_matches(self):
        self.assertEqual(
            self.constants.get("BLOCK_PRICE_CENTS_USD"),
            DEFAULT_BLOCK_PRICE_CENTS_USD,
            "Migration 0026 BLOCK_PRICE_CENTS_USD drifted.",
        )

    def test_self_service_max_blocks_matches(self):
        self.assertEqual(
            self.constants.get("SELF_SERVICE_MAX_BLOCKS"),
            DEFAULT_SELF_SERVICE_MAX_BLOCKS,
            "Migration 0026 SELF_SERVICE_MAX_BLOCKS drifted.",
        )

    def test_included_is_one_gigabyte(self):
                                                                    
                                                      
        self.assertEqual(DEFAULT_INCLUDED_BYTES, 1 * 1024 * 1024 * 1024)

    def test_block_is_fifty_gigabytes(self):
        self.assertEqual(DEFAULT_BLOCK_BYTES, 50 * 1024 * 1024 * 1024)

    def test_block_price_is_25_dollars(self):
        self.assertEqual(DEFAULT_BLOCK_PRICE_CENTS_USD, 2500)

    def test_self_service_ceiling_is_5tb(self):
                                              
        ceiling_bytes = DEFAULT_SELF_SERVICE_MAX_BLOCKS * DEFAULT_BLOCK_BYTES
        self.assertEqual(ceiling_bytes, 5000 * 1024 * 1024 * 1024)


class MigrationSkuLadderIsExact(unittest.TestCase):
    EXPECTED_LADDER = [
        ("storage_50gb_monthly",   1),
        ("storage_100gb_monthly",  2),
        ("storage_150gb_monthly",  3),
        ("storage_200gb_monthly",  4),
        ("storage_250gb_monthly",  5),
        ("storage_500gb_monthly",  10),
        ("storage_1tb_monthly",    20),
        ("storage_2tb_monthly",    40),
        ("storage_5tb_monthly",    100),
    ]

    def test_all_nine_skus_present_in_migration_source(self):
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        for sku_key, block_count in self.EXPECTED_LADDER:
            self.assertIn(
                sku_key, text,
                f"SKU {sku_key} not seeded in migration 0026.",
            )
                                                                  
                                                                          
        sku_block = text.split("INSERT INTO storage_skus", 1)[1]
        sku_block = sku_block.split("ON CONFLICT", 1)[0]
        monthly_count = sku_block.count("_monthly'")
        self.assertEqual(
            monthly_count, len(self.EXPECTED_LADDER),
            "SKU ladder length drift — expected 9 monthly SKUs.",
        )

    def test_ceiling_sku_blocks_equals_ceiling(self):
                                                                      
                                          
        biggest = max(b for _, b in self.EXPECTED_LADDER)
        self.assertEqual(biggest, DEFAULT_SELF_SERVICE_MAX_BLOCKS)


class BlocksToBytesTests(unittest.TestCase):
    def test_zero_blocks_is_zero_bytes(self):
        self.assertEqual(blocks_to_bytes(0), 0)

    def test_one_block_is_fifty_gigabytes(self):
        self.assertEqual(blocks_to_bytes(1), DEFAULT_BLOCK_BYTES)

    def test_max_self_service_is_five_terabytes(self):
        self.assertEqual(
            blocks_to_bytes(DEFAULT_SELF_SERVICE_MAX_BLOCKS),
            5000 * 1024 * 1024 * 1024,
        )

    def test_enterprise_can_exceed_self_service_ceiling(self):
                                                                      
        self.assertEqual(
            blocks_to_bytes(200), 200 * DEFAULT_BLOCK_BYTES,
        )
        self.assertEqual(
            blocks_to_bytes(2000), 2000 * DEFAULT_BLOCK_BYTES,
        )

    def test_negative_is_rejected(self):
        with self.assertRaises(ValueError):
            blocks_to_bytes(-1)


class BlockCountToPriceCentsTests(unittest.TestCase):
    def test_zero_blocks_is_zero_dollars(self):
        self.assertEqual(block_count_to_price_cents(0), 0)

    def test_one_block_is_twenty_five_dollars(self):
        self.assertEqual(block_count_to_price_cents(1), 2500)

    def test_three_blocks_is_seventy_five_dollars(self):
                                                 
        self.assertEqual(block_count_to_price_cents(3), 7500)

    def test_hundred_blocks_is_2500_dollars(self):
                                                            
        self.assertEqual(block_count_to_price_cents(100), 250_000)

    def test_negative_is_rejected(self):
        with self.assertRaises(ValueError):
            block_count_to_price_cents(-1)


class IsWithinSelfServiceCeilingTests(unittest.TestCase):
    def test_zero_is_within(self):
        self.assertTrue(is_within_self_service_ceiling(0))

    def test_one_is_within(self):
        self.assertTrue(is_within_self_service_ceiling(1))

    def test_ceiling_is_within(self):
                                                          
        self.assertTrue(is_within_self_service_ceiling(
            DEFAULT_SELF_SERVICE_MAX_BLOCKS,
        ))

    def test_one_over_is_enterprise(self):
                                          
        self.assertFalse(is_within_self_service_ceiling(
            DEFAULT_SELF_SERVICE_MAX_BLOCKS + 1,
        ))

    def test_arbitrary_enterprise_value_is_rejected(self):
                                                                    
                                        
        self.assertFalse(is_within_self_service_ceiling(200))


class PercentUsedTests(unittest.TestCase):
    def test_zero_used_zero_limit(self):
        self.assertEqual(compute_percent_used(0, 0), 0.0)

    def test_zero_used_positive_limit(self):
        self.assertEqual(compute_percent_used(0, 1024), 0.0)

    def test_half_used(self):
        self.assertEqual(compute_percent_used(500, 1000), 50.0)

    def test_exactly_at_limit(self):
        self.assertEqual(compute_percent_used(1000, 1000), 100.0)

    def test_over_limit_clamps_to_100(self):
                                                                  
                                                                   
        self.assertEqual(compute_percent_used(1370, 1000), 100.0)

    def test_zero_limit_with_used_returns_100(self):
                                                                      
                                                                    
        self.assertEqual(compute_percent_used(100, 0), 100.0)

    def test_zero_limit_zero_used_returns_zero(self):
        self.assertEqual(compute_percent_used(0, 0), 0.0)

    def test_rounds_to_one_decimal(self):
                                                              
        self.assertEqual(compute_percent_used(47, 110), 42.7)

    def test_user_example_42_9_percent(self):
                                                    
                                                      
        self.assertEqual(
            compute_percent_used(48_372_563_200, 112_742_891_520),
            42.9,
        )


class PurchasedBytesActiveTests(unittest.TestCase):
    def test_active_grants_storage(self):
        self.assertEqual(_purchased_bytes_active("active", 100), 100)

    def test_in_grace_grants_storage(self):
                                                             
        self.assertEqual(_purchased_bytes_active("in_grace", 100), 100)

    def test_canceled_pending_grants_storage(self):
                                                                           
        self.assertEqual(
            _purchased_bytes_active("canceled_pending", 100), 100,
        )

    def test_expired_zeroes_storage(self):
        self.assertEqual(_purchased_bytes_active("expired", 100), 0)

    def test_refunded_zeroes_storage(self):
        self.assertEqual(_purchased_bytes_active("refunded", 100), 0)

    def test_none_zeroes_storage(self):
        self.assertEqual(_purchased_bytes_active("none", 100), 0)

    def test_over_quota_grace_zeroes_storage(self):
                                                                        
                                                                        
        self.assertEqual(
            _purchased_bytes_active("over_quota_grace", 100), 0,
        )

    def test_over_quota_locked_zeroes_storage(self):
        self.assertEqual(
            _purchased_bytes_active("over_quota_locked", 100), 0,
        )

    def test_paused_zeroes_storage(self):
                                                           
        self.assertEqual(_purchased_bytes_active("paused", 100), 0)


class StorageEntitlementShape(unittest.TestCase):
    EXPECTED_FIELDS = frozenset({
        "account_id",
        "account_type",
        "sales_channel",
        "included_bytes",
        "purchased_bytes",
        "storage_bytes_grant",
        "effective_limit_bytes",
        "used_bytes",
        "percent_used",
        "block_count",
        "self_service_max_blocks",
        "status",
        "source",
        "current_period_end",
        "cancel_at_period_end",
        "block_price_cents_usd",
        "block_bytes",
                                                                     
                                                                    
        "has_active_subscription",
        # Provider-neutral ownership and product metadata are part of the
        # current public entitlement contract. Keep them locked here so a
        # future field addition still requires architecture review.
        "provider",
        "product_id",
        "base_plan_id",
        "billing_period",
        "storage_bytes",
        "display_tier",
        "subscription_status",
        "entitlement_family",
        "ownership_status",
        "conflict_reason_code",
        "current_provider",
        "target_provider",
        "migration_status",
        "web_card_purchase_allowed",
    })

    def test_field_set_matches_spec(self):
        actual = {f.name for f in dataclass_fields(StorageEntitlement)}
        missing = self.EXPECTED_FIELDS - actual
        extra = actual - self.EXPECTED_FIELDS
        self.assertFalse(
            missing,
            f"StorageEntitlement is missing locked fields: {sorted(missing)}",
        )
        self.assertFalse(
            extra,
            f"StorageEntitlement gained unlocked fields: {sorted(extra)}. "
            "Add them to EXPECTED_FIELDS after architecture review.",
        )


from unittest.mock import MagicMock, patch


class ReconciliationSql(unittest.TestCase):


    def setUp(self):
        self.fake_conn = MagicMock(name="conn")
        self.fake_cursor = MagicMock(name="cursor")
        self.fake_conn.cursor.return_value = self.fake_cursor
                                                                 
                                                    
        self.fake_cursor.fetchone.return_value = (7_948_721,)
        self.patch = patch("billing.get_db", return_value=self.fake_conn)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def _executed_sql(self) -> list[str]:
        return [
            args[0][0] for args in self.fake_cursor.execute.call_args_list
        ]

    def _executed_params(self) -> list[tuple]:
        return [
            (args[0][1] if len(args[0]) > 1 else ())
            for args in self.fake_cursor.execute.call_args_list
        ]

    def test_recomputes_account_storage_total_from_per_vault_sum(self):
        from billing import reconcile_account_storage_from_vaults
        reconcile_account_storage_from_vaults("acct-x")
        sql_seen = self._executed_sql()
                                                                  
                                                                     
        self.assertTrue(any(
            "UPDATE account_storage_totals" in s
            and "SUM(total_bytes)" in s
            and "FROM vaults" in s
            for s in sql_seen
        ), "missing SUM-based recompute of account_storage_totals")

    def test_sets_last_recomputed_to_now(self):
        from billing import reconcile_account_storage_from_vaults
        reconcile_account_storage_from_vaults("acct-x")
        sql_seen = self._executed_sql()
        self.assertTrue(any(
            "last_recomputed = NOW()" in s for s in sql_seen
        ), "reconcile must stamp last_recomputed = NOW()")

    def test_returns_the_recomputed_total(self):
        from billing import reconcile_account_storage_from_vaults
        result = reconcile_account_storage_from_vaults("acct-x")
        self.assertEqual(result, 7_948_721)

    def test_commits_on_success(self):
        from billing import reconcile_account_storage_from_vaults
        reconcile_account_storage_from_vaults("acct-x")
        self.fake_conn.commit.assert_called_once()

    def test_rolls_back_and_returns_zero_on_db_failure(self):
                                                                      
                                                        
        self.fake_cursor.execute.side_effect = [
            Exception("db hiccup"),
        ]
        from billing import reconcile_account_storage_from_vaults
        result = reconcile_account_storage_from_vaults("acct-x")
        self.assertEqual(result, 0)
        self.fake_conn.rollback.assert_called_once()

    def test_empty_account_id_returns_zero_without_db(self):
                                                                 
                                          
        from billing import reconcile_account_storage_from_vaults
        self.assertEqual(reconcile_account_storage_from_vaults(""), 0)
                          
        self.assertEqual(self._executed_sql(), [])


class EntitlementCalculationModelTests(unittest.TestCase):


    BLOCK = DEFAULT_BLOCK_BYTES                       
    INC   = DEFAULT_INCLUDED_BYTES                   

    def setUp(self) -> None:
                                                             
                                                              
        import billing
        billing._PRICING_CACHE.update({
            "included_bytes":          DEFAULT_INCLUDED_BYTES,
            "block_bytes":             DEFAULT_BLOCK_BYTES,
            "block_price_cents_usd":   DEFAULT_BLOCK_PRICE_CENTS_USD,
            "self_service_max_blocks": DEFAULT_SELF_SERVICE_MAX_BLOCKS,
        })

    def tearDown(self) -> None:
        import billing
        billing.reset_pricing_cache()

    def _patched_get_db(self, row: dict | None):


        from unittest.mock import MagicMock, patch

        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn = MagicMock()
        conn.cursor.return_value = cursor
                                                                      
                                                                 
        grant_cursor = MagicMock()
        grant_cursor.fetchone.return_value = (False,)
        grant_conn = MagicMock()
        grant_conn.cursor.return_value = grant_cursor
                                                               
                                                                     
        return patch(
            "billing.get_db",
            side_effect=[conn, grant_conn, grant_conn, grant_conn],
        )

    def _row(self, *, block_count: int, status: str = "active",
             grant: int = 0, used: int = 0,
             grant_expires=None) -> dict:
        return {
            "account_id":              "acct-test",
            "account_type":            "individual",
            "sales_channel":           "self_service",
            "status":                  status,
            "source":                  "stripe",
            "block_count":             block_count,
            "purchased_bytes":         block_count * self.BLOCK,
            "storage_bytes_grant":     grant,
            "storage_bytes_grant_expires_at": grant_expires,
            "current_period_end":      None,
            "cancel_at_period_end":    False,
            "used_bytes":              used,
        }

                                                                        
    def test_free_user_block_count_zero_returns_one_gigabyte(self):
        from billing import get_entitlement
        with self._patched_get_db(self._row(block_count=0, status="none")):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.block_count, 0)
        self.assertEqual(ent.effective_limit_bytes, self.INC)
        self.assertEqual(ent.effective_limit_bytes, 1_073_741_824)

    def test_paid_one_block_returns_exactly_fifty_gigabytes(self):
                                                                    
        from billing import get_entitlement
        with self._patched_get_db(self._row(block_count=1)):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.block_count, 1)
        self.assertEqual(ent.purchased_bytes, self.BLOCK)
        self.assertEqual(ent.effective_limit_bytes, self.BLOCK)
                                                                     
                                        
        self.assertEqual(ent.effective_limit_bytes, 53_687_091_200)
                                                                   
                                                     
        self.assertNotEqual(
            ent.effective_limit_bytes,
            self.INC + self.BLOCK,
            "effective_limit_bytes regressed to included+purchased "
            "stacking — paid plans must REPLACE the free tier.",
        )

    def test_paid_two_blocks_returns_exactly_one_hundred_gigabytes(self):
        from billing import get_entitlement
        with self._patched_get_db(self._row(block_count=2)):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.effective_limit_bytes, 2 * self.BLOCK)
        self.assertEqual(ent.effective_limit_bytes, 107_374_182_400)

    def test_paid_three_blocks_returns_exactly_one_hundred_fifty_gigabytes(self):
        from billing import get_entitlement
        with self._patched_get_db(self._row(block_count=3)):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.effective_limit_bytes, 3 * self.BLOCK)
        self.assertEqual(ent.effective_limit_bytes, 161_061_273_600)

                                                                        
    def test_expired_paid_subscription_falls_back_to_free_tier(self):
                                                             
                                                                    
        from billing import get_entitlement
        with self._patched_get_db(
            self._row(block_count=1, status="expired"),
        ):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.purchased_bytes, 0)
        self.assertEqual(ent.effective_limit_bytes, self.INC)

    def test_grandfather_grant_stacks_only_on_free_tier(self):
                                                                  
                                                                
        ten_gb = 10 * 1024 ** 3
        from billing import get_entitlement
        with self._patched_get_db(
            self._row(block_count=0, status="none", grant=ten_gb),
        ):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.effective_limit_bytes, self.INC + ten_gb)

    def test_paid_plus_grant_returns_purchased_only_not_stacked(self):
                                                                 
                                                                
        ten_gb = 10 * 1024 ** 3
        from billing import get_entitlement
        with self._patched_get_db(
            self._row(block_count=1, status="active", grant=ten_gb),
        ):
            ent = get_entitlement("acct-test")
                                                            
        self.assertEqual(ent.effective_limit_bytes, self.BLOCK)

    def test_included_bytes_field_still_reports_one_gigabyte_for_all(self):
                                                                      
                                                                
        from billing import get_entitlement
        with self._patched_get_db(self._row(block_count=1)):
            ent = get_entitlement("acct-test")
        self.assertEqual(ent.included_bytes, self.INC)


if __name__ == "__main__":
    unittest.main()
