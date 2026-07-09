

from __future__ import annotations

import os
import unittest
from pathlib import Path


def _wipe_env(*names: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for n in names:
        snap[n] = os.environ.get(n)
        os.environ.pop(n, None)
    return snap


def _restore_env(snap: dict[str, str | None]) -> None:
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


_ENV_TOKENS = ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV")


_PROD_MIN_ENV = {
    "VAULTAI_ENV":                          "production",
    "VAULT_SESSION_SECRET":                 "prod-session-secret",
    "CORS_ALLOWED_ORIGIN_REGEX":            "^https://app\\.example\\.com$",
    "STRIPE_WEBHOOK_SECRET":                "whsec_prod_stub",
    "VAULTAI_DEBUG_ENDPOINTS_ENABLED":      "false",
}


class ProductionRequiresStripeWebhookSecretTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(
            *_ENV_TOKENS,
            "VAULT_SESSION_SECRET",
            "CORS_ALLOWED_ORIGIN_REGEX",
            "CORS_ALLOWED_ORIGINS",
            "STRIPE_WEBHOOK_SECRET",
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
            "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST",
        )
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_production_boot_refuses_when_webhook_secret_missing(self):
        for k, v in _PROD_MIN_ENV.items():
            if k == "STRIPE_WEBHOOK_SECRET":
                continue
            os.environ[k] = v
        import vault_config
        with self.assertRaises(RuntimeError) as ctx:
            vault_config.get_config()
        msg = str(ctx.exception)
        self.assertIn("STRIPE_WEBHOOK_SECRET", msg)

    def test_production_boot_succeeds_with_webhook_secret_set(self):
        for k, v in _PROD_MIN_ENV.items():
            os.environ[k] = v
        import vault_config
        cfg = vault_config.get_config()
        self.assertTrue(cfg.is_production)

    def test_production_boot_refuses_when_dev_auto_trust_leaks(self):
        for k, v in _PROD_MIN_ENV.items():
            os.environ[k] = v
        os.environ["VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST"] = "true"
        import vault_config
        with self.assertRaises(RuntimeError) as ctx:
            vault_config.get_config()
        msg = str(ctx.exception)
        self.assertIn("VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST", msg)


class RedactStripeIdTests(unittest.TestCase):

    def test_none_returns_empty(self):
        from stripe_service import redact_stripe_id
        self.assertEqual(redact_stripe_id(None), "")

    def test_empty_string_returns_empty(self):
        from stripe_service import redact_stripe_id
        self.assertEqual(redact_stripe_id(""), "")

    def test_short_id_returned_verbatim(self):
        from stripe_service import redact_stripe_id
        self.assertEqual(redact_stripe_id("sub_1"), "sub_1")

    def test_long_id_truncated_with_ellipsis(self):
        from stripe_service import redact_stripe_id
        raw = "sub_1Nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        redacted = redact_stripe_id(raw)
        self.assertTrue(redacted.endswith("..."))
        self.assertLess(len(redacted), len(raw))
        self.assertTrue(raw.startswith(redacted[:-3]))

    def test_keep_parameter_respected(self):
        from stripe_service import redact_stripe_id
        raw = "cus_" + ("x" * 30)
        self.assertEqual(
            redact_stripe_id(raw, keep=4), "cus_...",
        )

    def test_non_string_returns_empty(self):
        from stripe_service import redact_stripe_id
        self.assertEqual(redact_stripe_id(12345), "")
        self.assertEqual(redact_stripe_id({"id": "x"}), "")


class StripeModeLabelTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env("STRIPE_API_KEY")

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_unconfigured_when_env_unset(self):
        from stripe_service import stripe_mode_label
        self.assertEqual(stripe_mode_label(), "unconfigured")

    def test_live_when_key_prefix_live(self):
        os.environ["STRIPE_API_KEY"] = "sk_live_ABCDEFabcdef"
        from stripe_service import stripe_mode_label
        self.assertEqual(stripe_mode_label(), "live")

    def test_test_when_key_prefix_test(self):
        os.environ["STRIPE_API_KEY"] = "sk_test_XYZxyz"
        from stripe_service import stripe_mode_label
        self.assertEqual(stripe_mode_label(), "test")

    def test_restricted_live_key_recognized(self):
        os.environ["STRIPE_API_KEY"] = "rk_live_xyz"
        from stripe_service import stripe_mode_label
        self.assertEqual(stripe_mode_label(), "live")

    def test_unknown_when_key_prefix_unrecognized(self):
        os.environ["STRIPE_API_KEY"] = "weird_key_value"
        from stripe_service import stripe_mode_label
        self.assertEqual(stripe_mode_label(), "unknown")


class BillingAdminHealthEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(
            "STRIPE_API_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_STORAGE_BLOCK_PRICE_ID",
        )

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_envelope_shape_v1_required_fields(self):
        from stripe_service import build_billing_admin_health_envelope
        env = build_billing_admin_health_envelope()
        for k in (
            "status", "schema", "stripeMode",
            "apiKeyConfigured", "webhookSecretConfigured",
            "storageBlockPriceConfigured",
            "recentWebhookCount", "recentWebhookWindowSeconds",
            "lastWebhookEvent", "recentOutcomeCounts",
            "activeSubscriptionCount",
            "duplicateActiveSubscriptionAccountIdPrefixes",
        ):
            self.assertIn(k, env, f"envelope missing field: {k}")

    def test_envelope_reports_unconfigured_by_default(self):
        from stripe_service import build_billing_admin_health_envelope
        env = build_billing_admin_health_envelope()
        self.assertFalse(env["apiKeyConfigured"])
        self.assertFalse(env["webhookSecretConfigured"])
        self.assertFalse(env["storageBlockPriceConfigured"])
        self.assertEqual(env["stripeMode"], "unconfigured")

    def test_envelope_reports_configured_when_env_set(self):
        os.environ["STRIPE_API_KEY"] = "sk_test_key"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_stub"
        os.environ["STRIPE_STORAGE_BLOCK_PRICE_ID"] = "price_stub"
        from stripe_service import build_billing_admin_health_envelope
        env = build_billing_admin_health_envelope()
        self.assertTrue(env["apiKeyConfigured"])
        self.assertTrue(env["webhookSecretConfigured"])
        self.assertTrue(env["storageBlockPriceConfigured"])
        self.assertEqual(env["stripeMode"], "test")

    def test_envelope_never_leaks_api_key_or_webhook_secret(self):
        os.environ["STRIPE_API_KEY"] = "sk_live_LEAKY-KEY-XXX"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_LEAKY-SECRET-YYY"
        os.environ["STRIPE_STORAGE_BLOCK_PRICE_ID"] = "price_stub"
        from stripe_service import build_billing_admin_health_envelope
        env = build_billing_admin_health_envelope()
        blob = repr(env)
        self.assertNotIn("LEAKY-KEY-XXX", blob)
        self.assertNotIn("LEAKY-SECRET-YYY", blob)
        self.assertNotIn("sk_live_LEAKY", blob)
        self.assertNotIn("whsec_LEAKY", blob)

    def test_envelope_never_contains_raw_stripe_ids(self):
        from stripe_service import build_billing_admin_health_envelope
        env = build_billing_admin_health_envelope()
        blob = repr(env).lower()
        self.assertNotIn("cus_full", blob)
        self.assertNotIn("sub_full", blob)


class BillingAdminHealthRouteTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(
            "VAULTAI_BILLING_HEALTH_ADMIN_TOKEN",
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
            *_ENV_TOKENS,
        )
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_billing_admin_health_route_registered(self):
        from routes.stripe_routes import router
        routes = [r.path for r in router.routes]
        self.assertIn("/billing/admin/health", routes)


class DevCleanupProductionGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = Path(
            "routes/stripe_routes.py",
        ).read_text(encoding="utf-8")

    def test_dev_cleanup_route_refuses_in_production_explicitly(self):
        idx = self._src.find("dev_cleanup_duplicate_subs")
        self.assertGreater(idx, -1)
        slice_ = self._src[idx:idx + 3000]
        self.assertIn("is_production()", slice_)
        self.assertIn(
            "dev_cleanup_disabled_in_production", slice_,
            "dev cleanup route must include the "
            "dev_cleanup_disabled_in_production error code branch",
        )


class WebhookSignatureVerificationSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = Path(
            "stripe_service.py",
        ).read_text(encoding="utf-8")

    def test_verify_webhook_signature_uses_stripe_construct_event(self):
        self.assertIn(
            "stripe.Webhook.construct_event", self._src,
        )

    def test_verify_webhook_signature_requires_secret(self):
        idx = self._src.find("def verify_webhook_signature")
        self.assertGreater(idx, -1)
        slice_ = self._src[idx:idx + 2000]
        self.assertIn("get_stripe_webhook_secret", slice_)
        self.assertIn("StripeUnconfiguredError", slice_)


class WebhookIdempotencySourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = Path(
            "stripe_service.py",
        ).read_text(encoding="utf-8")

    def test_idempotency_uses_provider_event_log_table(self):
        self.assertIn("provider_event_log", self._src)

    def test_duplicate_event_returns_ignored_duplicate_outcome(self):
        self.assertIn('"ignored_duplicate"', self._src)

    def test_unique_violation_caught_for_replay(self):
        self.assertIn("UniqueViolation", self._src)


class WebhookLoggingRestrictionsSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = Path(
            "stripe_service.py",
        ).read_text(encoding="utf-8")

    def test_no_raw_webhook_payload_in_logger_lines(self):
        for banned in ("logger.info(raw_body",
                       "logger.info(payload",
                       "logger.warning(raw_body"):
            self.assertNotIn(banned, self._src)

    def test_no_customer_email_logged_directly(self):
        for banned in (
            "logger.info(customer_email",
            "logger.warning(customer_email",
            'customer_email=%s',
        ):
            self.assertNotIn(banned, self._src,
                             f"stripe_service.py leaks: {banned}")


class NoExchangeSurfaceInBillingTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = Path(
            "routes/stripe_routes.py",
        ).read_text(encoding="utf-8")

    def test_no_buy_sell_swap_language_in_billing_routes(self):
        lower = self._src.lower()
        for banned in ("swap ", "stake ", "bridge ",
                       "trade crypto", "buy crypto", "sell crypto"):
            self.assertNotIn(
                banned, lower,
                f"stripe_routes.py contains banned exchange term: "
                f"{banned}",
            )


if __name__ == "__main__":
    unittest.main()
