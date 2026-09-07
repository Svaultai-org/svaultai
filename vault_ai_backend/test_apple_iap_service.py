from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

import apple_iap_service as apple


class AppleIAPSecurityTests(unittest.TestCase):
    def _transaction(self, **overrides):
        values = {
            "productId": "com.svaultai.app.storage.50gb.monthly.v2",
            "transactionId": "200000000000001",
            "originalTransactionId": "200000000000000",
            "appAccountToken": "9dfe2e84-65e4-4a92-a991-617b24c10546",
            "expiresDate": int(
                (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
                * 1000
            ),
            "revocationDate": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_product_catalog_matches_50gb_through_5tb_ladder(self):
        self.assertEqual(sorted(apple.PRODUCT_BLOCKS.values()), [1, 2, 3, 4, 5, 10, 20, 40, 100])
        self.assertTrue(all(not value.startswith("svaultai.storage.") for value in apple.PRODUCT_BLOCKS))

    def test_unknown_product_is_rejected_before_database_write(self):
        with self.assertRaises(apple.AppleIAPVerificationError):
            apple.apply_verified_transaction(
                account_id="9dfe2e84-65e4-4a92-a991-617b24c10546",
                transaction=self._transaction(productId="attacker.product"),
                environment="sandbox",
            )

    def test_cross_account_purchase_is_rejected_before_database_write(self):
        with self.assertRaises(apple.AppleIAPVerificationError):
            apple.apply_verified_transaction(
                account_id="1bc1c1c7-44c5-4648-a373-f6dc7be8d8fc",
                transaction=self._transaction(),
                environment="sandbox",
            )

    def test_expired_and_revoked_transactions_are_rejected(self):
        expired = int(
            (datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp() * 1000
        )
        for transaction in (
            self._transaction(expiresDate=expired),
            self._transaction(revocationDate=expired),
        ):
            with self.assertRaises(apple.AppleIAPVerificationError):
                apple.apply_verified_transaction(
                    account_id="9dfe2e84-65e4-4a92-a991-617b24c10546",
                    transaction=transaction,
                    environment="sandbox",
                )


if __name__ == "__main__":
    unittest.main()
