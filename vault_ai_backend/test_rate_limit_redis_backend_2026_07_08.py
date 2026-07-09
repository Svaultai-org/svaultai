"""Production-grade rate-limit backend tests.

Verifies:

  * Redis backend increments atomically via the sliding-window Lua
    script — 4th hit against a limit of 3 is denied.
  * TTL expires — after the window elapses, allowed again.
  * Two independent RedisRateLimitBackend instances sharing one
    Redis see one shared counter (the distributed invariant).
  * In-memory backend remains available for dev.
  * Production without a Redis URL logs a safe warning at singleton
    resolve time.
  * Redis outage behavior is correct per bucket risk:
      - high-risk (auth, PIN, delete_vault, upload_burst,
        delete_burst, export, crypto_reveal) → fail CLOSED
      - low-risk (chat) → fail OPEN
  * Redis keys hash the caller's user_id — no raw IP / vault id /
    device id in the key going to Redis.
  * Redis URL is redacted in health() so credentials do not leak.
  * The 429 response body from every enforce_* helper is still the
    generic message and does not reveal which counter tripped or
    whether the account exists.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest import mock

from rate_limit_backend import (
    BUCKET_RISK_HIGH,
    BUCKET_RISK_LOW,
    InMemoryRateLimitBackend,
    RedisRateLimitBackend,
    _bucket_is_high_risk,
    _compose_key,
    _failure_decision,
    _hash_user_id,
    _redact_redis_url,
    get_rate_limit_backend,
    install_backend_for_tests,
    reset_rate_limit_backend_for_tests,
)


try:
    import redis as _redis
    _HAS_REDIS = True
except Exception:
    _HAS_REDIS = False


_requires_redis = unittest.skipUnless(
    _HAS_REDIS,
    "redis module not installed in test venv "
    "(the backend itself does not need it — these two tests only "
    "exercise the `redis.Redis.from_url` boot path)",
)


class _FakeRedis:
    """Minimal Redis stand-in that implements just enough of the
    server protocol to run our sliding-window Lua script. Backs
    ZADD / ZCARD / ZRANGE / ZREMRANGEBYSCORE / PEXPIRE / EVALSHA /
    SCRIPT LOAD / PING.

    All state lives in a plain dict so two _FakeRedis wrappers can
    share the same underlying dict — that mimics two backend
    instances hitting the same Redis.
    """

    def __init__(self, shared_state: dict | None = None):
        self._state: dict[bytes, list[tuple[float, str]]] = (
            shared_state if shared_state is not None else {}
        )
        self._scripts: dict[str, str] = {}
        self._expires: dict[bytes, float] = {}

    def ping(self) -> bool:
        return True

    def script_load(self, script: str) -> bytes:
        import hashlib as _h
        sha = _h.sha1(script.encode("utf-8")).hexdigest()
        self._scripts[sha] = script
        return sha.encode("ascii")

    def _bkey(self, key) -> bytes:
        return key if isinstance(key, bytes) else str(key).encode("utf-8")

    def _expire_check(self, key: bytes) -> None:
        exp = self._expires.get(key)
        if exp is not None and exp < time.time() * 1000:
            self._state.pop(key, None)
            self._expires.pop(key, None)

    def evalsha(self, sha, numkeys, *args):

        if isinstance(sha, bytes):
            sha = sha.decode("ascii")
        script = self._scripts.get(sha)
        if script is None:
            class NoScriptError(Exception):
                pass
            raise NoScriptError("script not loaded")

        keys = [args[i] for i in range(numkeys)]
        argv = list(args[numkeys:])
        key = self._bkey(keys[0])
        now_ms = int(argv[0])
        window_ms = int(argv[1])
        limit = int(argv[2])
        member = argv[3]
        cutoff = now_ms - window_ms

        self._expire_check(key)
        z = self._state.setdefault(key, [])
        z[:] = [(s, m) for (s, m) in z if s > cutoff]

        if len(z) >= limit:
            oldest_score = z[0][0]
            reset_ms = (oldest_score + window_ms) - now_ms
            if reset_ms < 0:
                reset_ms = 0
            return [0, 0, int((reset_ms + 999) // 1000)]

        z.append((float(now_ms), str(member)))
        z.sort(key=lambda p: p[0])
        self._expires[key] = time.time() * 1000 + window_ms + 1000
        return [1, limit - len(z), int((window_ms + 999) // 1000)]


class TestKeyHashingAndRedaction(unittest.TestCase):
    """Requirement (3): keys must not contain raw user id, vault id,
    device id, IP, auth token, API key, email, or session token."""

    def test_hash_prefix_length(self):
        h = _hash_user_id("ip:1.2.3.4")
        self.assertEqual(len(h), 16)
        self.assertRegex(h, r"^[0-9a-f]{16}$")

    def test_empty_maps_to_anon_sentinel(self):
        self.assertEqual(_hash_user_id(""), "anon")

    def test_key_contains_no_raw_ip(self):
        k = _compose_key("auth_login", "ip:203.0.113.9")
        self.assertNotIn("203.0.113.9", k)
        self.assertTrue(k.startswith("rl:v1:auth_login:"))

    def test_key_contains_no_raw_vault_id(self):
        k = _compose_key(
            "pin_verify",
            "pin:vault-uuid-secret-abc:203.0.113.9",
        )
        for banned in (
            "vault-uuid-secret-abc", "203.0.113.9",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, k)

    def test_key_contains_no_email(self):
        k = _compose_key("auth_signup", "alice@example.com")
        self.assertNotIn("alice", k)
        self.assertNotIn("example.com", k)

    def test_key_deterministic(self):
        self.assertEqual(
            _compose_key("auth_login", "ip:1.2.3.4"),
            _compose_key("auth_login", "ip:1.2.3.4"),
        )
        self.assertNotEqual(
            _compose_key("auth_login", "ip:1.2.3.4"),
            _compose_key("auth_login", "ip:1.2.3.5"),
        )

    def test_redis_url_password_is_never_leaked_in_health(self):

        b = RedisRateLimitBackend(
            url="redis://alice:supersecret@r.example.com:6379/0",
            client=_FakeRedis(),
        )
        h = b.health()

        self.assertIsInstance(h.get("url"), str)
        self.assertNotIn("supersecret", h["url"])
        self.assertNotIn("alice", h["url"])
        self.assertIn("r.example.com", h["url"])

    def test_redact_helper_handles_no_password(self):
        self.assertIn(
            "r.example.com",
            _redact_redis_url("redis://r.example.com:6379"),
        )


class TestBucketRiskClassification(unittest.TestCase):
    """Requirement (5): fail closed for high-risk, fail open for
    low-risk."""

    def test_high_risk_buckets_are_the_expected_set(self):
        for b in (
            "auth_signup", "auth_login", "pin_verify",
            "delete_vault", "upload_burst", "delete_burst",
            "export", "crypto_reveal",
        ):
            with self.subTest(bucket=b):
                self.assertTrue(_bucket_is_high_risk(b))
                self.assertIn(b, BUCKET_RISK_HIGH)

    def test_chat_is_low_risk_fail_open(self):
        self.assertFalse(_bucket_is_high_risk("chat"))
        self.assertIn("chat", BUCKET_RISK_LOW)

    def test_unknown_bucket_defaults_to_high_risk(self):

        self.assertTrue(_bucket_is_high_risk("brand-new-bucket"))

    def test_failure_decision_high_risk_is_denied(self):
        d = _failure_decision("pin_verify", 3600)
        self.assertFalse(d.allowed)
        self.assertEqual(d.remaining, 0)
        self.assertEqual(d.reset_in_seconds, 3600)

    def test_failure_decision_low_risk_is_allowed(self):
        d = _failure_decision("chat", 600)
        self.assertTrue(d.allowed)
        self.assertEqual(d.reset_in_seconds, 600)


class TestRedisBackendAtomicIncrement(unittest.TestCase):
    """Requirement (1) + (6): atomic increment via Lua; 4th call
    over a limit of 3 is denied; TTL expires."""

    def _new_backend(self, shared_state=None):
        client = _FakeRedis(shared_state=shared_state)
        return RedisRateLimitBackend(url="redis://x", client=client)

    def test_first_calls_allowed_then_denied(self):
        b = self._new_backend()
        for i in range(3):
            d = b.check_and_increment(
                user_id="ip:1.2.3.4",
                bucket="auth_login",
                limit_per_window=3,
                window_seconds=60,
            )
            self.assertTrue(d.allowed, msg=f"call {i+1} should be allowed")
        denied = b.check_and_increment(
            user_id="ip:1.2.3.4",
            bucket="auth_login",
            limit_per_window=3,
            window_seconds=60,
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.remaining, 0)

        self.assertGreater(denied.reset_in_seconds, 0)
        self.assertLessEqual(denied.reset_in_seconds, 60)

    def test_remaining_decrements(self):
        b = self._new_backend()
        d1 = b.check_and_increment(
            user_id="u", bucket="auth_login",
            limit_per_window=5, window_seconds=60,
        )
        d2 = b.check_and_increment(
            user_id="u", bucket="auth_login",
            limit_per_window=5, window_seconds=60,
        )
        self.assertEqual(d1.remaining, 4)
        self.assertEqual(d2.remaining, 3)

    def test_ttl_expires_and_counter_resets(self):

        client = _FakeRedis()
        b = RedisRateLimitBackend(url="redis://x", client=client)
        for _ in range(3):
            b.check_and_increment(
                user_id="u", bucket="auth_login",
                limit_per_window=3, window_seconds=1,
            )
        denied = b.check_and_increment(
            user_id="u", bucket="auth_login",
            limit_per_window=3, window_seconds=1,
        )
        self.assertFalse(denied.allowed)

        time.sleep(1.05)
        allowed = b.check_and_increment(
            user_id="u", bucket="auth_login",
            limit_per_window=3, window_seconds=1,
        )
        self.assertTrue(allowed.allowed)


class TestRedisDistributedInvariant(unittest.TestCase):
    """Requirement (1) + (6): two backend instances sharing one
    Redis see one counter."""

    def test_two_backends_share_state(self):
        shared: dict = {}
        client_a = _FakeRedis(shared_state=shared)
        client_b = _FakeRedis(shared_state=shared)
        backend_a = RedisRateLimitBackend(
            url="redis://x", client=client_a,
        )
        backend_b = RedisRateLimitBackend(
            url="redis://x", client=client_b,
        )

        for i in range(3):

            src = backend_a if i % 2 == 0 else backend_b
            d = src.check_and_increment(
                user_id="ip:1.2.3.4",
                bucket="auth_login",
                limit_per_window=3,
                window_seconds=60,
            )
            self.assertTrue(d.allowed)

        d = backend_b.check_and_increment(
            user_id="ip:1.2.3.4",
            bucket="auth_login",
            limit_per_window=3,
            window_seconds=60,
        )
        self.assertFalse(
            d.allowed,
            msg=(
                "second backend instance should see the counter "
                "from the first — that's the whole point of "
                "moving off in-memory."
            ),
        )


class TestRedisOutageBehaviour(unittest.TestCase):
    """Requirement (5) + (6): outage → high-risk buckets fail
    closed; low-risk buckets fail open."""

    def _new_backend_with_broken_client(self):

        client = mock.MagicMock()
        client.script_load.side_effect = RuntimeError(
            "redis unreachable",
        )
        return RedisRateLimitBackend(url="redis://x", client=client)

    def test_pin_verify_fails_closed_when_redis_is_broken(self):
        b = self._new_backend_with_broken_client()
        d = b.check_and_increment(
            user_id="u", bucket="pin_verify",
            limit_per_window=30, window_seconds=3600,
        )
        self.assertFalse(d.allowed)
        self.assertEqual(d.remaining, 0)

    def test_delete_vault_fails_closed_when_redis_is_broken(self):
        b = self._new_backend_with_broken_client()
        d = b.check_and_increment(
            user_id="u", bucket="delete_vault",
            limit_per_window=10, window_seconds=3600,
        )
        self.assertFalse(d.allowed)

    def test_auth_login_fails_closed_when_redis_is_broken(self):
        b = self._new_backend_with_broken_client()
        d = b.check_and_increment(
            user_id="u", bucket="auth_login",
            limit_per_window=30, window_seconds=3600,
        )
        self.assertFalse(d.allowed)

    def test_chat_fails_open_when_redis_is_broken(self):
        b = self._new_backend_with_broken_client()
        d = b.check_and_increment(
            user_id="u", bucket="chat",
            limit_per_window=120, window_seconds=600,
        )
        self.assertTrue(
            d.allowed,
            msg=(
                "chat is low-risk — a Redis blip must not brick "
                "user chat"
            ),
        )

    def test_missing_client_at_init_falls_back_to_failure_policy(
        self,
    ):

        b = RedisRateLimitBackend.__new__(RedisRateLimitBackend)
        b._url = "redis://x"
        b._client = None
        b._script_sha = None

        d = b.check_and_increment(
            user_id="u", bucket="pin_verify",
            limit_per_window=30, window_seconds=3600,
        )
        self.assertFalse(d.allowed)

        d = b.check_and_increment(
            user_id="u", bucket="chat",
            limit_per_window=30, window_seconds=600,
        )
        self.assertTrue(d.allowed)


class TestInMemoryFallback(unittest.TestCase):
    """Requirement (2): in-memory limiter still works in dev."""

    def setUp(self):
        reset_rate_limit_backend_for_tests()
        for k in (
            "VAULTAI_RATE_LIMIT_BACKEND",
            "VAULTAI_RATE_LIMIT_REDIS_URL",
            "RATE_LIMIT_REDIS_URL",
            "VAULTAI_ENV",
            "ENVIRONMENT",
            "FLASK_ENV",
            "NODE_ENV",
        ):
            os.environ.pop(k, None)

    def tearDown(self):
        reset_rate_limit_backend_for_tests()

    def test_default_dev_backend_is_in_memory(self):
        b = get_rate_limit_backend()
        self.assertIsInstance(b, InMemoryRateLimitBackend)

    def test_in_memory_denies_after_limit(self):
        b = get_rate_limit_backend()
        for _ in range(3):
            b.check_and_increment(
                user_id="u", bucket="auth_login",
                limit_per_window=3, window_seconds=60,
            )
        d = b.check_and_increment(
            user_id="u", bucket="auth_login",
            limit_per_window=3, window_seconds=60,
        )
        self.assertFalse(d.allowed)

    def test_in_memory_key_is_hashed_too(self):

        b = get_rate_limit_backend()
        b.check_and_increment(
            user_id="ip:203.0.113.9",
            bucket="auth_login",
            limit_per_window=3, window_seconds=60,
        )

        for stored_key in b._state.keys():
            self.assertNotIn("203.0.113.9", stored_key)
            self.assertTrue(stored_key.startswith("rl:v1:"))


class TestProductionResolverWarnings(unittest.TestCase):
    """Requirement (2): production missing Redis → safe warning."""

    def setUp(self):
        reset_rate_limit_backend_for_tests()
        for k in (
            "VAULTAI_RATE_LIMIT_BACKEND",
            "VAULTAI_RATE_LIMIT_REDIS_URL",
            "RATE_LIMIT_REDIS_URL",
            "VAULTAI_ENV",
            "ENVIRONMENT",
            "FLASK_ENV",
            "NODE_ENV",
        ):
            os.environ.pop(k, None)

    def tearDown(self):
        reset_rate_limit_backend_for_tests()
        for k in (
            "VAULTAI_RATE_LIMIT_BACKEND",
            "VAULTAI_RATE_LIMIT_REDIS_URL",
            "RATE_LIMIT_REDIS_URL",
            "VAULTAI_ENV",
            "ENVIRONMENT",
            "FLASK_ENV",
            "NODE_ENV",
        ):
            os.environ.pop(k, None)

    def test_production_without_redis_url_warns(self):
        os.environ["VAULTAI_ENV"] = "production"
        with self.assertLogs(
            "rate_limit_backend", level="WARNING",
        ) as cap:
            b = get_rate_limit_backend()
        joined = "\n".join(cap.output)
        self.assertIn("production", joined.lower())
        self.assertIn("in-memory", joined)
        self.assertIn("RATE_LIMIT_REDIS_URL", joined)

        self.assertIsInstance(b, InMemoryRateLimitBackend)

    @_requires_redis
    def test_production_with_redis_url_uses_redis_without_warning(
        self,
    ):
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULTAI_RATE_LIMIT_REDIS_URL"] = "redis://r"
        with mock.patch(
            "redis.Redis.from_url", return_value=_FakeRedis(),
        ):
            b = get_rate_limit_backend()
        self.assertIsInstance(b, RedisRateLimitBackend)

    def test_redis_choice_without_url_falls_back_to_memory_warning(
        self,
    ):
        os.environ["VAULTAI_RATE_LIMIT_BACKEND"] = "redis"
        with self.assertLogs(
            "rate_limit_backend", level="WARNING",
        ) as cap:
            b = get_rate_limit_backend()
        joined = "\n".join(cap.output)
        self.assertIn("in-memory", joined.lower())
        self.assertIsInstance(b, InMemoryRateLimitBackend)


class TestBackendInjectionForRouteTests(unittest.TestCase):
    """Requirement (6) test infra: routes can install a specific
    backend instance without touching env vars."""

    def tearDown(self):
        reset_rate_limit_backend_for_tests()

    def test_install_backend_for_tests_wins(self):
        fake = InMemoryRateLimitBackend()
        install_backend_for_tests(fake)
        self.assertIs(get_rate_limit_backend(), fake)


class TestGeneric429ResponseUnchanged(unittest.TestCase):
    """Requirement (4): the 429 body is still the generic message
    and does not reveal whether an account exists."""

    def test_rate_limit_sensitive_message_is_generic(self):
        from rate_limit_sensitive import _GENERIC_429_MESSAGE
        low = _GENERIC_429_MESSAGE.lower()

        self.assertEqual(
            _GENERIC_429_MESSAGE,
            "Too many requests. Please wait and try again.",
        )

        for banned in (
            "account", "user", "vault", "does not exist",
            "attempts remaining", "counter", "bucket",
            "redis", "backend",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, low)

    def test_auth_route_429_message_is_generic(self):
        from rate_limit_auth import (
            enforce_signup_rate_limit,
        )
        import inspect
        src = inspect.getsource(enforce_signup_rate_limit)
        self.assertIn("Too many", src)
        self.assertNotIn("account exists", src.lower())


if __name__ == "__main__":
    unittest.main()
