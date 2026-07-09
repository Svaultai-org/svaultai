"""VaultAI security hardening — regression tests.

Groups map to Parts A-N in the operator brief. Each group locks in a
specific invariant; a broken invariant should surface a small, clear
test failure rather than a whole-suite meltdown.

Part A — threat-model + hardening docs shipped
Part B — rate-limit modules exist + wired into sensitive routes
Part C — PIN brute-force protection still lives in vault_core
Part D — delete-vault revokes sessions + uses HMAC challenge
Part E — body-size middleware + upload caps present
Part F — mass-action burst limits exist
Part G — path traversal + upload safety helpers exist
Part H — security-headers middleware wired
Part I — SQL uses parameterized queries; user text not concatenated
Part J — crypto vault safety invariants (source scan)
Part K — Stripe webhook signature verify + idempotency
Part L — security event logger closed-set + refuses secrets
Part M — env-var + docs present
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient


_BACKEND_ROOT = Path(__file__).parent
_REPO_ROOT = _BACKEND_ROOT.parent


def _route_files() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in (_BACKEND_ROOT / "routes").glob("*.py"):
        out[p.name] = p.read_text(encoding="utf-8")
    return out


class TestPartA_DocsShipped(unittest.TestCase):

    _REQUIRED_DOCS = (
        _REPO_ROOT / "docs" / "security_threat_model.md",
        _REPO_ROOT / "docs" / "security_hardening.md",
        _REPO_ROOT / "docs" / "rate_limits.md",
        _REPO_ROOT / "docs" / "incident_response.md",
    )

    def test_all_four_docs_exist_and_are_non_trivial(self):
        for p in self._REQUIRED_DOCS:
            with self.subTest(doc=p.name):
                self.assertTrue(
                    p.exists(),
                    msg=f"required doc missing: {p}",
                )
                text = p.read_text(encoding="utf-8")
                self.assertGreater(len(text), 500)

    def test_threat_model_covers_required_sections(self):
        text = (
            self._REQUIRED_DOCS[0].read_text(encoding="utf-8").lower()
        )
        for section in (
            "assets", "attacker", "trust boundar",
            "existing protection", "gap",
        ):
            with self.subTest(section=section):
                self.assertIn(section, text)

    def test_threat_model_does_not_claim_unhackable(self):

        text = (
            self._REQUIRED_DOCS[0].read_text(encoding="utf-8").lower()
        )
        for forbidden in (
            "impossible to hack",
            "unhackable",
            "cannot be attacked",
            "no system can attack",
            "perfectly safe",
            "guaranteed safe",
            "perfect security",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


class TestPartB_RateLimitModules(unittest.TestCase):

    def test_rate_limit_sensitive_module_present_with_expected_buckets(
        self,
    ):
        from rate_limit_sensitive import ALL_BUCKETS
        for b in (
            "pin_verify", "chat", "delete_vault",
            "upload_burst", "delete_burst", "export",
        ):
            with self.subTest(bucket=b):
                self.assertIn(b, ALL_BUCKETS)

    def test_generic_429_message_does_not_leak_info(self):
        from rate_limit_sensitive import _GENERIC_429_MESSAGE
        low = _GENERIC_429_MESSAGE.lower()

        for banned in (
            "account", "user", "vault", "does not exist",
            "limit is", "attempts remaining",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, low)

    def test_delete_vault_routes_call_enforce_delete_rate_limit(self):
        src = (
            _BACKEND_ROOT / "routes" / "vault_delete_routes.py"
        ).read_text(encoding="utf-8")
        self.assertIn("enforce_delete_vault_rate_limit", src)

        for endpoint in (
            "def get_delete_status",
            "def request_delete",
            "def confirm_delete",
        ):
            with self.subTest(endpoint=endpoint):
                idx = src.index(endpoint)
                next_def = src.find("\n@router", idx + 1)
                if next_def < 0:
                    next_def = len(src)
                body = src[idx:next_def]
                self.assertIn(
                    "enforce_delete_vault_rate_limit", body,
                    msg=f"{endpoint} does not call the delete rate limit",
                )

    def test_verify_pin_endpoint_uses_pin_verify_rate_limit(self):
        src = (_BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
        idx = src.index("async def verify_pin_endpoint")
        window = src[idx: idx + 3000]
        self.assertIn("enforce_pin_verify_rate_limit", window)

    def test_chat_endpoint_uses_chat_rate_limit(self):
        src = (_BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
        idx = src.index("async def chat_endpoint")
        window = src[idx: idx + 3000]
        self.assertIn("enforce_chat_rate_limit", window)

    def test_rate_limit_backend_has_redis_implementation(self):

        src = (
            _BACKEND_ROOT / "rate_limit_backend.py"
        ).read_text(encoding="utf-8")
        self.assertIn("RedisRateLimitBackend", src)

        self.assertIn("ZREMRANGEBYSCORE", src)
        self.assertIn("ZADD", src)
        self.assertIn("PEXPIRE", src)

        self.assertIn("script_load", src)


class TestPartC_PinBruteForceProtection(unittest.TestCase):

    def test_max_pin_attempts_is_finite_and_small(self):
        from vault_core import MAX_PIN_ATTEMPTS, PIN_LOCKOUT_HOURS
        self.assertLessEqual(MAX_PIN_ATTEMPTS, 10)
        self.assertGreaterEqual(PIN_LOCKOUT_HOURS, 1)

    def test_login_route_still_writes_lockout_columns(self):
        src = (
            _BACKEND_ROOT / "routes" / "auth_routes.py"
        ).read_text(encoding="utf-8")
        self.assertIn("failed_pin_attempts", src)
        self.assertIn("locked_until", src)


class TestPartD_DeleteVaultAndSession(unittest.TestCase):

    def test_delete_confirm_revokes_all_sessions_after_delete(self):
        src = (
            _BACKEND_ROOT / "routes" / "vault_delete_routes.py"
        ).read_text(encoding="utf-8")
        confirm_start = src.index("def confirm_delete")
        end = src.find("\n\n\n", confirm_start)
        if end < 0:
            end = len(src)
        body = src[confirm_start:end]
        self.assertIn("delete_vault_and_all_data", body)
        self.assertIn("revoke_all_sessions_for_vault", body)

        delete_idx = body.index("delete_vault_and_all_data")
        revoke_idx = body.index("revoke_all_sessions_for_vault")
        self.assertLess(delete_idx, revoke_idx)

    def test_challenge_token_is_vault_bound_and_expiry_checked(self):




        from routes.vault_delete_routes import (
            _sign_challenge, _verify_challenge,
        )
        from unittest import mock

        stable_secret = "stable-challenge-secret-for-this-test-" + "x" * 24
        frozen_now_ts = 1_800_000_000

        with mock.patch.dict(
            os.environ,
            {"VAULT_SESSION_SECRET": stable_secret},
            clear=False,
        ):

            good = _sign_challenge("v-a", frozen_now_ts + 300)
            self.assertTrue(
                _verify_challenge(good, "v-a", now_ts=frozen_now_ts),
                msg="a freshly-signed token for vault v-a should "
                    "verify against v-a inside its 300-second window",
            )


            self.assertFalse(
                _verify_challenge(good, "v-b", now_ts=frozen_now_ts),
                msg="a challenge signed for v-a must NEVER verify "
                    "against v-b — vault binding is load-bearing "
                    "for delete-vault safety",
            )


            expired = _sign_challenge("v-a", frozen_now_ts - 10)
            self.assertFalse(
                _verify_challenge(expired, "v-a", now_ts=frozen_now_ts),
                msg="an expired challenge for v-a must NOT verify — "
                    "the 10-minute TTL prevents a captured challenge "
                    "from being replayed indefinitely",
            )


            raw = _sign_challenge("v-a", frozen_now_ts + 300)
            tampered = raw[:-4] + ("A" if raw[-4] != "A" else "B") + raw[-3:]
            self.assertFalse(
                _verify_challenge(tampered, "v-a", now_ts=frozen_now_ts),
                msg="a challenge with a mutated signature byte must "
                    "NOT verify — the HMAC binding must reject any "
                    "bit-flip",
            )


class TestPartE_BodySizeCaps(unittest.TestCase):

    def test_main_has_limit_request_body_size_middleware(self):
        src = (_BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            "async def limit_request_body_size", src,
            msg="body-size middleware must remain in main.py",
        )
        self.assertIn("MAX_UPLOAD_BYTES", src)
        self.assertIn("MAX_JSON_BODY_BYTES", src)
        self.assertIn("CHUNK_UPLOAD_MAX_FRAME_BYTES", src)


class TestPartF_MassActionBurstGuards(unittest.TestCase):

    def test_upload_and_delete_burst_functions_exist(self):
        from rate_limit_sensitive import (
            enforce_upload_burst_rate_limit,
            enforce_delete_burst_rate_limit,
        )
        self.assertTrue(callable(enforce_upload_burst_rate_limit))
        self.assertTrue(callable(enforce_delete_burst_rate_limit))

    def test_burst_windows_are_short(self):
        from rate_limit_sensitive import (
            UPLOAD_BURST_WINDOW_SECONDS,
            DELETE_BURST_WINDOW_SECONDS,
        )
        self.assertLessEqual(UPLOAD_BURST_WINDOW_SECONDS, 300)
        self.assertLessEqual(DELETE_BURST_WINDOW_SECONDS, 300)


class TestPartG_UploadSafetyHelpers(unittest.TestCase):

    def test_main_still_defines_path_traversal_sanitizer(self):
        src = (_BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("_sanitize_relative_path", src)


class TestPartH_SecurityHeadersMiddleware(unittest.TestCase):

    def _mk_app(self):
        from security_headers import SecurityHeadersMiddleware
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/hello")
        def hello():
            return {"ok": True}

        @app.get("/auth/me")
        def auth_me():
            return {"ok": True}

        return TestClient(app)

    def test_headers_present_on_generic_response(self):
        client = self._mk_app()
        r = client.get("/hello")
        for k in (
            "X-Content-Type-Options",
            "Referrer-Policy",
            "X-Frame-Options",
            "Content-Security-Policy",
            "Permissions-Policy",
            "Cross-Origin-Opener-Policy",
        ):
            with self.subTest(header=k):
                self.assertIn(k, r.headers)

    def test_sensitive_path_gets_no_store_cache(self):
        client = self._mk_app()
        r = client.get("/auth/me")
        self.assertIn("Cache-Control", r.headers)
        self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertIn("no-cache", r.headers["Cache-Control"])

    def test_csp_disallows_object_and_framing(self):
        from security_headers import CSP_STRICT
        self.assertIn("object-src 'none'", CSP_STRICT)
        self.assertIn("frame-ancestors 'none'", CSP_STRICT)

    def test_headers_disable_flag_short_circuits(self):
        import os
        client = self._mk_app()
        with mock.patch.dict(
            os.environ,
            {"VAULTAI_SECURITY_HEADERS_ENABLED": "false"},
        ):
            r = client.get("/hello")

        self.assertNotIn("Content-Security-Policy", r.headers)


class TestPartI_ParameterizedSQL(unittest.TestCase):
    """User-controlled fields must never be interpolated into SQL.

    We check routes/*.py because those are the only places that
    handle user input directly. Utility modules (vault_image_audit,
    reconciler, etc.) may f-string a column list from their own
    closed-set constants — that is not a user-input interpolation.
    """

    _USER_INPUT_INTERP_RE = re.compile(
        r"cur\.execute\s*\(\s*f?[\"'][^\"']*"
        r"(?:SELECT|INSERT|UPDATE|DELETE)[^\"']*"
        r"\{\s*(?:payload|body|req|request|"
        r"query|params|user_[a-z_]+|search|term)"
        r"[\w.\[\]']*\s*\}",
        re.IGNORECASE,
    )

    def test_route_handlers_do_not_fstring_user_input_into_sql(self):
        offenders: list[str] = []
        routes_dir = _BACKEND_ROOT / "routes"
        for p in routes_dir.glob("*.py"):
            text = p.read_text(encoding="utf-8")
            for m in self._USER_INPUT_INTERP_RE.finditer(text):
                offenders.append(f"{p.name}: {m.group(0)[:80]}")
        self.assertEqual(
            offenders, [],
            msg=(
                "route handler interpolates user-controlled input "
                "into SQL — use parameterized queries (%s + params) "
                "instead. Offenders: " + str(offenders)
            ),
        )

    def test_no_string_concatenation_of_user_input_into_sql(self):

        pattern = re.compile(
            r"cur\.execute\s*\([^)]*\+\s*"
            r"(?:payload|body|req|request|query|params|user_[a-z_]+"
            r"|search|term)[\w.\[\]]*",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        routes_dir = _BACKEND_ROOT / "routes"
        for p in routes_dir.glob("*.py"):
            text = p.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                offenders.append(f"{p.name}: {m.group(0)[:80]}")
        self.assertEqual(offenders, [])


class TestPartJ_CryptoInvariants(unittest.TestCase):

    def test_crypto_control_hardcodes_can_broadcast_false(self):
        src = (
            _BACKEND_ROOT / "crypto_vault_chat_control.py"
        ).read_text(encoding="utf-8")
        self.assertIn('canBroadcast', src)
        self.assertIn('False', src)

        self.assertRegex(
            src, r'canBroadcast["\']?\s*[:=]\s*False',
        )

    def test_crypto_control_refuses_secret_material(self):

        src = (
            _BACKEND_ROOT / "crypto_vault_chat_control.py"
        ).read_text(encoding="utf-8").lower()

        for regex in (
            r"\bseed\b",
            r"\bmnemonic",
            r"\bprivate\W+key\b",
            r"\bspend\W+key\b",
            r"\bview\W+key\b",
        ):
            with self.subTest(regex=regex):
                self.assertIsNotNone(
                    re.search(regex, src),
                    msg=(
                        f"crypto control module missing pattern for "
                        f"{regex!r} — safety refusal set may be gone"
                    ),
                )

    def test_deletion_service_never_imports_broadcast(self):
        src = (
            _BACKEND_ROOT / "vault_deletion_service.py"
        ).read_text(encoding="utf-8")
        for banned in (
            "import crypto_send",
            "import crypto_broadcast",
            "broadcast_transaction",
            "send_transaction",
            "sign_transaction",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)


class TestPartK_StripeWebhookSignatureAndIdempotency(unittest.TestCase):

    def test_stripe_route_verifies_signature(self):
        src = (
            _BACKEND_ROOT / "routes" / "stripe_routes.py"
        ).read_text(encoding="utf-8")
        self.assertIn("verify_webhook_signature", src)
        self.assertIn("Stripe-Signature", src)

        self.assertIn("StripeSignatureError", src)
        self.assertIn("StripeEventDecodeError", src)

    def test_idempotency_table_exists(self):

        migration_dir = (
            _BACKEND_ROOT / "migrations" / "versions"
        )
        found_pel = False
        for p in migration_dir.glob("*.py"):
            if "provider_event_log" in p.read_text(encoding="utf-8"):
                found_pel = True
                break
        self.assertTrue(
            found_pel,
            msg=(
                "provider_event_log table must be defined in an "
                "alembic migration for Stripe webhook idempotency"
            ),
        )


class TestPartL_SecurityEventLogger(unittest.TestCase):

    def test_closed_set_of_reasons(self):
        from security_event_log import REASONS
        self.assertGreater(len(REASONS), 5)
        for r in REASONS:
            self.assertRegex(r, r"^[a-z][a-z0-9_]{5,64}$")

    def test_closed_set_of_route_groups(self):
        from security_event_log import ROUTE_GROUPS
        for g in ROUTE_GROUPS:
            self.assertRegex(g, r"^[a-z][a-z0-9_]{2,32}$")

    def test_emit_rejects_unknown_reason(self):
        import security_event_log as sec
        with self.assertRaises(ValueError):
            sec.emit(
                reason="totally-made-up",
                route=sec.ROUTE_GROUP_AUTH,
            )

    def test_emit_rejects_unknown_route(self):
        import security_event_log as sec
        with self.assertRaises(ValueError):
            sec.emit(
                reason=sec.REASON_RATE_LIMITED_AUTH,
                route="nowhere",
            )

    def test_emit_refuses_note_with_banned_secret_tokens(self):
        import security_event_log as sec
        for banned in (
            "user pin=1234",
            "user seed = abc",
            "mnemonic here",
            "raw private key material",
            "Authorization: Bearer abc",
            "password reset for x",
            "encrypted_data payload",
            "pin_verifier tampered",
        ):
            with self.subTest(banned=banned):
                with self.assertRaises(ValueError):
                    sec.emit(
                        reason=sec.REASON_PIN_ATTEMPT_FAIL,
                        route=sec.ROUTE_GROUP_PIN,
                        note=banned,
                    )

    def test_emit_refuses_oversize_note(self):
        import security_event_log as sec
        with self.assertRaises(ValueError):
            sec.emit(
                reason=sec.REASON_PIN_ATTEMPT_FAIL,
                route=sec.ROUTE_GROUP_PIN,
                note="a" * 400,
            )

    def test_emit_refuses_long_subject(self):
        import security_event_log as sec
        with self.assertRaises(ValueError):
            sec.emit(
                reason=sec.REASON_PIN_ATTEMPT_FAIL,
                route=sec.ROUTE_GROUP_PIN,
                subject="x" * 128,
            )

    def test_emit_writes_prefixed_warning_log(self):
        import logging
        import security_event_log as sec
        with self.assertLogs("security_event_log", level="WARNING") as cap:
            sec.emit(
                reason=sec.REASON_RATE_LIMITED_AUTH,
                route=sec.ROUTE_GROUP_AUTH,
                subject=sec.short_hash("abc"),
            )
        joined = "\n".join(cap.output)
        self.assertIn("[SEC-EVENT]", joined)
        self.assertIn("reason=rate_limited_auth", joined)
        self.assertIn("route=auth", joined)

    def test_short_hash_returns_hex_prefix(self):
        from security_event_log import short_hash
        h = short_hash("hello world")
        self.assertEqual(len(h), 12)
        self.assertRegex(h, r"^[0-9a-f]{12}$")

    def test_short_hash_of_empty_is_anon(self):
        from security_event_log import short_hash
        self.assertEqual(short_hash(""), "anon")

    def test_delete_flow_emits_confirmed_event_after_delete(self):

        src = (
            _BACKEND_ROOT / "routes" / "vault_delete_routes.py"
        ).read_text(encoding="utf-8")
        self.assertIn("REASON_DELETE_VAULT_CONFIRMED", src)
        self.assertIn("REASON_DELETE_VAULT_REQUESTED", src)

    def test_inactive_job_emits_inactive_deleted_event(self):
        src = (
            _BACKEND_ROOT / "inactive_unpaid_cleanup.py"
        ).read_text(encoding="utf-8")
        self.assertIn("REASON_INACTIVE_UNPAID_DELETED", src)


class TestPartM_EnvExampleAndConfigDocs(unittest.TestCase):

    def test_env_example_documents_new_rate_limit_vars(self):
        p = _BACKEND_ROOT / ".env.example"
        text = p.read_text(encoding="utf-8")
        for var in (
            "VAULTAI_RL_PIN_VERIFY_LIMIT",
            "VAULTAI_RL_CHAT_LIMIT",
            "VAULTAI_RL_DELETE_VAULT_LIMIT",
            "VAULTAI_RL_UPLOAD_BURST_LIMIT",
            "VAULTAI_RL_DELETE_BURST_LIMIT",
            "VAULTAI_RL_EXPORT_LIMIT",
            "VAULTAI_SECURITY_HEADERS_ENABLED",
        ):
            with self.subTest(var=var):
                self.assertIn(var, text)

    def test_rate_limits_doc_lists_every_bucket(self):
        text = (
            _REPO_ROOT / "docs" / "rate_limits.md"
        ).read_text(encoding="utf-8").lower()
        for bucket in (
            "auth_signup", "auth_login", "pin_verify", "chat",
            "delete_vault", "upload_burst", "delete_burst", "export",
        ):
            with self.subTest(bucket=bucket):
                self.assertIn(bucket, text)


class TestPartN_ImportSmoke(unittest.TestCase):

    def test_all_new_modules_import(self):
        import rate_limit_sensitive
        import security_event_log
        import security_headers

        self.assertTrue(hasattr(rate_limit_sensitive, "ALL_BUCKETS"))
        self.assertTrue(hasattr(security_event_log, "REASONS"))
        self.assertTrue(hasattr(security_headers, "CSP_STRICT"))


if __name__ == "__main__":
    unittest.main()
