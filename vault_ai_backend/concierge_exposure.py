"""Free password-only policy by default; paid HIBP checks require explicit mode.

Never accepts a vault PIN, password or private file.

Email range results are transient and matched on the unlocked client. Only
separately consented full email monitoring is decryptable by this service.
That operational-key boundary is deliberately NOT described as zero knowledge.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg2.extras import RealDictCursor

from vault_core import get_db

CONSENT_VERSION = "2026-10-09"
ATTRIBUTION_URL = "https://haveibeenpwned.com/"
HIBP_BASE = "https://haveibeenpwned.com/api/v3/"
COVERAGE = (
    "Known HIBP records only; excludes sensitive/retired/opted-out records. "
    "No finding does not establish that an account is safe. Stealer logs are "
    "limited to provider-verified email domains, not a comprehensive dark-web scan. "
    "Private-file exposure is unsupported."
)
FREE_COVERAGE = (
    "Free password-only checks against known HIBP Pwned Passwords records, "
    "matched on the unlocked client. Email exposure, background email monitoring "
    "and stealer-log intelligence are deferred under the free-provider policy. "
    "No comprehensive dark-web scan or private-file exposure detection. "
    "No finding does not establish that a password or account is safe."
)
MAX_STATE_BYTES = 200 * 1024
MAX_PROVIDER_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_PREFIX = re.compile(r"^[0-9A-Fa-f]{6}$")
_SOURCE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")

# httpx INFO logs the full request URL. HIBP's direct-email contract puts the
# explicitly consented address in that URL; never let routine diagnostics make
# a second durable plaintext copy. Filter only this synchronous request context,
# leaving unrelated HTTP diagnostics unchanged (including other app features).
_private_provider_request: ContextVar[bool] = ContextVar("concierge_private_provider_request", default=False)


class _ProviderLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_provider_request.get()


for _logger_name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11",
                     "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_logger_name).addFilter(_ProviderLogFilter())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() == "true"


def _bounded_int(name: str, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(upper, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    enabled: bool
    background_enabled: bool
    stealer_enabled: bool
    api_key: str = field(repr=False)
    keyring: dict[str, bytes] = field(repr=False)
    active_key_id: str
    rpm: int
    interval_seconds: int
    provider_mode: str = "free"

    @classmethod
    def from_environment(cls) -> "Settings":
        provider_mode = os.getenv("VAULTAI_CONCIERGE_PROVIDER_MODE", "free").strip().lower()
        if provider_mode not in ("free", "hibp"):
            # Never silently enable a paid provider or echo arbitrary env data.
            provider_mode = "invalid"
        key = os.getenv("CONCIERGE_HIBP_API_KEY", "").strip()
        # A test/placeholder key must not masquerade as a configured paid provider.
        if not re.fullmatch(r"[0-9a-fA-F]{32}", key) or set(key) == {"0"}:
            key = ""
        keyring: dict[str, bytes] = {}
        try:
            raw = json.loads(os.getenv("CONCIERGE_MONITORING_KEYRING_JSON", "{}"))
            if not raw and os.getenv("CONCIERGE_MONITORING_KEY", "").strip():
                raw = {"v1": os.environ["CONCIERGE_MONITORING_KEY"].strip()}
            if not isinstance(raw, dict) or len(raw) > 8:
                raise ValueError("invalid_keyring")
            for key_id, value in raw.items():
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key_id):
                    raise ValueError("invalid_key_id")
                decoded = decode_b64(value, max_bytes=32)
                if len(decoded) != 32:
                    raise ValueError("invalid_key_size")
                keyring[key_id] = decoded
        except (ValueError, TypeError, binascii.Error):
            keyring = {}
        active = os.getenv("CONCIERGE_MONITORING_ACTIVE_KEY_ID", "v1").strip()
        return cls(
            _flag("VAULTAI_CONCIERGE_ENABLED"),
            _flag("VAULTAI_CONCIERGE_BACKGROUND_ENABLED"),
            _flag("VAULTAI_CONCIERGE_STEALER_LOGS_ENABLED"),
            key, keyring, active,
            _bounded_int("VAULTAI_CONCIERGE_HIBP_RPM", 5, 1, 1000),
            _bounded_int("VAULTAI_CONCIERGE_POLL_SECONDS", 86400, 3600, 604800),
            provider_mode,
        )

    @property
    def encryption_available(self) -> bool:
        return self.active_key_id in self.keyring

    @property
    def paid_provider_allowed(self) -> bool:
        return self.provider_mode == "hibp"


def decode_b64(value: str, *, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid_base64url")
    if len(value) > (max_bytes * 4 + 2) // 3 + 4:
        raise ValueError("ciphertext_too_large")
    data = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if not data or len(data) > max_bytes:
        raise ValueError("invalid_ciphertext_size")
    return data


def normalize_email(value: str) -> str:
    # Deliberately bounded common-address subset. Do not accept arbitrary URLs,
    # display names, newline/header injection or provider path parameters.
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s/@:?#\\]+@[^\s/@:?#\\]+", value):
        raise ValueError("invalid_email")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or not _DOMAIN.fullmatch(domain):
        raise ValueError("invalid_email")
    return value


def _aad(vault_id: str, monitor_id: str, purpose: str) -> bytes:
    return f"svaultai/concierge/v1/{UUID(vault_id)}/{UUID(monitor_id)}/{purpose}".encode()


def seal(settings: Settings, vault_id: str, monitor_id: str, purpose: str, data: bytes) -> bytes:
    if not settings.encryption_available:
        raise ProviderError("monitoring_key_unavailable")
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(settings.keyring[settings.active_key_id]).encrypt(
        nonce, data, _aad(vault_id, monitor_id, purpose),
    )


def unseal(settings: Settings, key_id: str, vault_id: str, monitor_id: str,
           purpose: str, data: bytes) -> bytes:
    try:
        key = settings.keyring[key_id]
        if len(data) < 29:
            raise ValueError("truncated_envelope")
        return AESGCM(key).decrypt(bytes(data[:12]), bytes(data[12:]), _aad(vault_id, monitor_id, purpose))
    except Exception:
        # Never expose a ciphertext, email, operational key or cryptographic exception.
        raise ProviderError("monitoring_key_unavailable") from None


class ProviderError(Exception):
    def __init__(self, code: str, retry_after_seconds: int | None = None):
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


def require_paid_provider(settings: Settings) -> None:
    """Budget policy is checked before any provider budget, DB or HTTP work."""
    if not settings.paid_provider_allowed:
        raise ProviderError("provider_deferred" if settings.provider_mode == "free"
                            else "provider_mode_invalid")


def open_db(factory=None):
    """Feature-only bounded statements/locks; never alters global DB settings."""
    conn = (factory or get_db)()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = '20s'")
        cur.execute("SET LOCAL lock_timeout = '5s'")
        return conn
    except Exception:
        conn.close()
        raise


def _retry_after(value: str | None) -> int:
    try:
        return max(1, min(86400, int(value or "60")))
    except ValueError:
        return 60


def reserve_provider_slot(settings: Settings) -> None:
    """A durable shared-key budget, including web requests and background workers."""
    require_paid_provider(settings)
    conn = open_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""INSERT INTO concierge_provider_control(provider)
                       VALUES ('hibp') ON CONFLICT DO NOTHING""")
        cur.execute("""SELECT next_allowed_at, blocked_until, NOW() AS db_now
                       FROM concierge_provider_control WHERE provider='hibp' FOR UPDATE""")
        row = cur.fetchone()
        until = max(row["next_allowed_at"], row["blocked_until"])
        if until > row["db_now"]:
            raise ProviderError("provider_rate_limited", max(1, int((until - row["db_now"]).total_seconds()) + 1))
        cur.execute("""UPDATE concierge_provider_control SET next_allowed_at =
                       NOW() + %s * INTERVAL '1 second' WHERE provider='hibp'""",
                    (60.0 / settings.rpm + 0.1,))
        conn.commit()
    finally:
        conn.close()


def block_provider(seconds: int) -> None:
    conn = open_db()
    try:
        cur = conn.cursor()
        cur.execute("""UPDATE concierge_provider_control SET blocked_until =
                       GREATEST(blocked_until, NOW() + %s * INTERVAL '1 second')
                       WHERE provider='hibp'""", (seconds,))
        conn.commit()
    finally:
        conn.close()


def consume_vault_budget(vault_id: str) -> None:
    """Twenty requested checks/minute per vault, coordinated across API workers."""
    conn = open_db()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO concierge_request_budget(vault_id,window_start,requests)
          VALUES(%s,date_trunc('minute',NOW()),1)
          ON CONFLICT(vault_id) DO UPDATE SET
          requests=CASE WHEN concierge_request_budget.window_start=date_trunc('minute',NOW())
                        THEN concierge_request_budget.requests+1 ELSE 1 END,
          window_start=date_trunc('minute',NOW()) RETURNING requests""", (vault_id,))
        requests = cur.fetchone()[0]
        conn.commit()
        if requests > 20:
            raise ProviderError("concierge_rate_limited", 60)
    finally:
        conn.close()


class HibpProvider:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None,
                 allow_rate_wait: bool = False):
        self.settings = settings
        self.transport = transport
        self.allow_rate_wait = allow_rate_wait

    def _request(self, path: str, *, allow_not_found: bool = False) -> Any:
        require_paid_provider(self.settings)
        if not self.settings.enabled:
            raise ProviderError("concierge_disabled")
        if not self.settings.api_key:
            raise ProviderError("provider_not_configured")
        try:
            reserve_provider_slot(self.settings)
        except ProviderError as exc:
            # Optional bounded pacing for sequential monitor checks. Never retry
            # provider 429 here, nor loop/spend the key's quota indefinitely.
            if not self.allow_rate_wait or exc.code != "provider_rate_limited" or not exc.retry_after_seconds or exc.retry_after_seconds > 15:
                raise
            time.sleep(exc.retry_after_seconds)
            reserve_provider_slot(self.settings)
        private_log_scope = _private_provider_request.set(True)
        try:
            deadline = time.monotonic() + 8.0
            with httpx.Client(timeout=httpx.Timeout(8.0), follow_redirects=False,
                              trust_env=False, transport=self.transport) as client:
                with client.stream("GET", HIBP_BASE + path, headers={
                    "hibp-api-key": self.settings.api_key,
                    "User-Agent": "SVaultAI-Concierge/1.0",
                    "Accept": "application/json",
                }) as response:
                    if response.status_code == 404 and allow_not_found:
                        return []
                    if response.status_code != 200:
                        codes = {401: "provider_unauthorized", 403: "provider_permission_denied",
                                 429: "provider_rate_limited"}
                        retry = _retry_after(response.headers.get("retry-after")) if response.status_code == 429 else None
                        if retry is not None:
                            block_provider(retry)
                        raise ProviderError(codes.get(response.status_code, "provider_unavailable"), retry)
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise ProviderError("provider_unavailable")
                        size += len(chunk)
                        if size > MAX_PROVIDER_BYTES:
                            raise ProviderError("provider_invalid_response")
                        chunks.append(chunk)
                    return json.loads(b"".join(chunks))
        except ProviderError:
            raise
        except Exception:
            # httpx exceptions contain the full URL, including a consented email.
            raise ProviderError("provider_unavailable") from None
        finally:
            _private_provider_request.reset(private_log_scope)

    def subscription(self) -> dict:
        value = self._request("subscription/status")
        if not isinstance(value, dict) or type(value.get("Rpm")) is not int or value["Rpm"] < 1:
            raise ProviderError("provider_invalid_response")
        try:
            until = datetime.fromisoformat(str(value["SubscribedUntil"]).replace("Z", "+00:00"))
            if until.tzinfo is None or until <= now_utc():
                raise ProviderError("provider_subscription_expired")
        except (KeyError, ValueError, TypeError):
            raise ProviderError("provider_invalid_response") from None
        return value

    def verified_domains(self) -> list[str]:
        value = self._request("subscribedDomains")
        if not isinstance(value, list) or len(value) > 10000:
            raise ProviderError("provider_invalid_response")
        domains = []
        for entry in value:
            domain = str(entry.get("DomainName", "")).lower() if isinstance(entry, dict) else ""
            if not _DOMAIN.fullmatch(domain):
                raise ProviderError("provider_invalid_response")
            domains.append(domain)
        return sorted(set(domains))

    def email_range(self, prefix: str) -> list[dict]:
        if not _PREFIX.fullmatch(prefix):
            raise ValueError("invalid_email_prefix")
        value = self._request("breachedaccount/range/" + prefix.upper())
        if not isinstance(value, list) or len(value) > 10000:
            raise ProviderError("provider_invalid_response")
        rows = []
        for row in value:
            if not isinstance(row, dict) or not re.fullmatch(r"[0-9A-Fa-f]{34}", str(row.get("hashSuffix", ""))):
                raise ProviderError("provider_invalid_response")
            websites = row.get("websites")
            if not isinstance(websites, list) or len(websites) > 500 or any(not isinstance(n, str) or not _NAME.fullmatch(n) for n in websites):
                raise ProviderError("provider_invalid_response")
            rows.append({"hashSuffix": row["hashSuffix"].upper(), "websites": websites})
        return rows  # Never stored/cached: only client knows which suffix matches.

    def email_breaches(self, email: str) -> list[dict]:
        normalized = normalize_email(email)
        value = self._request("breachedAccount/" + quote(normalized, safe="") + "?truncateResponse=false",
                              allow_not_found=True)
        if not isinstance(value, list) or len(value) > 2000:
            raise ProviderError("provider_invalid_response")
        return [sanitize_breach(row) for row in value]

    def breach(self, name: str) -> dict:
        if not _NAME.fullmatch(name):
            raise ValueError("invalid_breach_name")
        return sanitize_breach(self._request("breach/" + quote(name, safe="")))

    def stealer_domains(self, email: str, verified_domains: list[str]) -> list[str]:
        normalized = normalize_email(email)
        if normalized.rsplit("@", 1)[1] not in verified_domains:
            raise ProviderError("stealer_domain_unsupported")
        value = self._request("stealerLogsByEmail/" + quote(normalized, safe=""), allow_not_found=True)
        if not isinstance(value, list) or len(value) > 10000:
            raise ProviderError("provider_invalid_response")
        if any(not isinstance(d, str) or not _DOMAIN.fullmatch(d.lower()) for d in value):
            raise ProviderError("provider_invalid_response")
        return sorted(set(d.lower() for d in value))


def sanitize_breach(value: Any) -> dict:
    if not isinstance(value, dict) or not _NAME.fullmatch(str(value.get("Name", ""))):
        raise ProviderError("provider_invalid_response")
    title = value.get("Title")
    classes = value.get("DataClasses")
    if not isinstance(title, str) or not 1 <= len(title) <= 200 or any(ord(c) < 32 for c in title):
        raise ProviderError("provider_invalid_response")
    if not isinstance(classes, list) or len(classes) > 100 or any(not isinstance(c, str) or len(c) > 120 for c in classes):
        raise ProviderError("provider_invalid_response")
    try:
        from datetime import date
        date.fromisoformat(value["BreachDate"])
    except (KeyError, ValueError, TypeError):
        raise ProviderError("provider_invalid_response") from None
    domain = value.get("Domain", "")
    if not isinstance(domain, str) or (domain and not _DOMAIN.fullmatch(domain.lower())):
        raise ProviderError("provider_invalid_response")
    return {"name": value["Name"], "title": title, "domain": domain.lower(),
            "breach_date": value["BreachDate"], "data_classes": classes,
            "is_verified": value.get("IsVerified") is True,
            "is_spam_list": value.get("IsSpamList") is True,
            "is_stealer_log": value.get("IsStealerLog") is True}


_caps_lock = threading.Lock()
_caps_cache: tuple[float, tuple, dict] | None = None


def capabilities(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_environment()
    basic = {"enabled": settings.enabled, "provider": "hibp", "consent_version": CONSENT_VERSION,
             "provider_mode": settings.provider_mode if settings.provider_mode in ("free", "hibp") else "invalid",
             "attribution_url": ATTRIBUTION_URL, "coverage": COVERAGE,
             "password_breaches": {"status": "available", "mode": "client_range"},
             "file_exposure": {"status": "unsupported"}}
    if not settings.paid_provider_allowed:
        status = "deferred" if settings.provider_mode == "free" else "not_configured"
        detail = {} if status == "deferred" else {"error_code": "provider_mode_invalid"}
        return {**basic, "coverage": FREE_COVERAGE, "policy": "free_password_only",
                "email_range": {"status": status, **detail},
                "email_monitoring": {"status": status, **detail},
                "stealer_logs": {"status": status, "verified_email_domains": [], **detail}}
    status = "disabled" if not settings.enabled else "not_configured"
    base = {**basic, "email_range": {"status": status}, "email_monitoring": {"status": status},
            "stealer_logs": {"status": status, "verified_email_domains": []}}
    if not settings.enabled or not settings.api_key:
        return base
    global _caps_cache
    # Keys never appear in logs/response. Cache partitions by actual config, and
    # failures are short-lived so provider recovery can be observed.
    identity = (settings.provider_mode, settings.api_key, settings.background_enabled, settings.stealer_enabled,
                settings.encryption_available, settings.rpm)
    with _caps_lock:
        if _caps_cache and _caps_cache[0] > time.monotonic() and _caps_cache[1] == identity:
            return json.loads(json.dumps(_caps_cache[2]))
        try:
            provider = HibpProvider(settings, allow_rate_wait=True)
            sub = provider.subscription()
            # Fail closed if the operator configured a faster rate than purchased.
            if settings.rpm > sub["Rpm"]:
                raise ProviderError("provider_rate_configuration_invalid")
            base["email_range"] = {"status": "available" if sub.get("IncludesKAnon") is True else "unsupported_plan"}
            monitoring = "available" if settings.background_enabled and settings.encryption_available else "disabled"
            if settings.background_enabled and not settings.encryption_available:
                monitoring = "not_configured"
            base["email_monitoring"] = {"status": monitoring}
            if settings.stealer_enabled and sub.get("IncludesStealerLogs") is True:
                domains = provider.verified_domains()
                base["stealer_logs"] = {"status": "conditional" if domains else "unsupported_domain",
                                       "verified_email_domains": domains}
            else:
                base["stealer_logs"] = {"status": "disabled" if not settings.stealer_enabled else "unsupported_plan",
                                       "verified_email_domains": []}
            ttl = 300
        except ProviderError as exc:
            for field_name in ("email_range", "email_monitoring", "stealer_logs"):
                base[field_name] = {"status": "unavailable", "error_code": exc.code,
                                    "retry_after_seconds": exc.retry_after_seconds}
            base["stealer_logs"]["verified_email_domains"] = []
            ttl = min(30, exc.retry_after_seconds or 30)
        _caps_cache = (time.monotonic() + ttl, identity, base)
        return json.loads(json.dumps(base))


def unavailable(exc: ProviderError, *, attempted_at: datetime | None = None) -> dict:
    return {"status": "unavailable", "provider": "hibp", "coverage": COVERAGE,
            "attribution_url": ATTRIBUTION_URL, "attempted_at": attempted_at or now_utc(),
            "successful_at": None, "error_code": exc.code,
            "retry_after_seconds": exc.retry_after_seconds}


def require_capability(caps: dict, name: str) -> None:
    capability = caps[name]
    if capability["status"] not in ("available", "conditional"):
        raise ProviderError(capability.get("error_code") or f"{name}_{capability['status']}",
                            capability.get("retry_after_seconds"))


def _source_owned(cur, vault_id: str, source_item_id: str | None) -> bool:
    if source_item_id is None:
        return True
    if not _SOURCE.fullmatch(source_item_id):
        return False
    cur.execute("""SELECT EXISTS(SELECT 1 FROM vault_items WHERE vault_id=%s AND id::TEXT=%s)
      OR EXISTS(SELECT 1 FROM vault_crypto_envelopes WHERE vault_id=%s
                AND record_domain='credential' AND record_id=%s AND deleted_at IS NULL)""",
                (vault_id, source_item_id, vault_id, source_item_id))
    row = cur.fetchone()
    return bool(next(iter(row.values())) if isinstance(row, dict) else row[0])


def create_monitor(vault_id: str, email: str, source_item_id: str | None, *,
                   stealer_logs: bool, settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_environment()
    require_paid_provider(settings)
    email = normalize_email(email)
    caps = capabilities(settings)
    require_capability(caps, "email_monitoring")
    if stealer_logs:
        require_capability(caps, "stealer_logs")
        if email.rsplit("@", 1)[1] not in caps["stealer_logs"]["verified_email_domains"]:
            raise ProviderError("stealer_domain_unsupported")
    monitor_id = str(uuid4())
    ciphertext = seal(settings, vault_id, monitor_id, "email", email.encode())
    conn = open_db()
    try:
        cur = conn.cursor()
        # Serialize count limits and owner deletion with the actual parent vault.
        cur.execute("SELECT vault_id FROM vaults WHERE vault_id=%s FOR UPDATE", (vault_id,))
        if not cur.fetchone():
            raise ValueError("vault_unavailable")
        if not _source_owned(cur, vault_id, source_item_id):
            raise ValueError("source_item_not_found")
        cur.execute("SELECT COUNT(*) FROM concierge_monitors WHERE vault_id=%s", (vault_id,))
        if cur.fetchone()[0] >= 20:
            raise ValueError("monitor_limit_reached")
        cur.execute("""INSERT INTO concierge_monitors
          (id,vault_id,source_item_id,key_id,email_ciphertext,consent_version,
           email_disclosure_consent,stealer_logs,stealer_disclosure_consent,background)
          VALUES(%s,%s,%s,%s,%s,%s,TRUE,%s,%s,TRUE)""",
                    (monitor_id, vault_id, source_item_id, settings.active_key_id,
                     ciphertext, CONSENT_VERSION, stealer_logs, stealer_logs))
        conn.commit()
    finally:
        conn.close()
    return {"id": monitor_id, "source_item_id": source_item_id, "background": True,
            "stealer_logs": stealer_logs, "status": "not_checked", "attempted_at": None,
            "successful_at": None, "breaches": [], "stealer_domains": [], "provider": "hibp",
            "coverage": COVERAGE, "attribution_url": ATTRIBUTION_URL}


def monitor_view(row: dict, settings: Settings) -> dict:
    result = {"breaches": [], "stealer_domains": []}
    status, error = row["status"], row.get("error_code")
    if status in ("found", "no_known_findings") and (not row.get("result_ciphertext") or not row.get("successful_at")):
        status, error = "unavailable", "monitoring_data_unavailable"
    if row.get("result_ciphertext"):
        try:
            result = json.loads(unseal(settings, row["key_id"], str(row["vault_id"]),
                                       str(row["id"]), "result", row["result_ciphertext"]))
            if (not isinstance(result, dict) or not isinstance(result.get("breaches"), list)
                    or not isinstance(result.get("stealer_domains"), list)):
                raise ValueError("invalid_result_shape")
        except (ProviderError, ValueError, TypeError):
            status, error = "unavailable", "monitoring_key_unavailable"
            result = {"breaches": [], "stealer_domains": []}
    return {"id": str(row["id"]), "source_item_id": row["source_item_id"],
            "background": row["background"], "stealer_logs": row["stealer_logs"],
            "status": status, "error_code": error, "attempted_at": row["attempted_at"],
            "successful_at": row["successful_at"], "retry_after_seconds": row.get("retry_after_seconds"),
            "breaches": result["breaches"], "stealer_domains": result["stealer_domains"],
            "provider": "hibp", "coverage": COVERAGE, "attribution_url": ATTRIBUTION_URL}


def list_monitors(vault_id: str) -> list[dict]:
    settings = Settings.from_environment()
    conn = open_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM concierge_monitors WHERE vault_id=%s ORDER BY created_at,id", (vault_id,))
        return [monitor_view(dict(row), settings) for row in cur.fetchall()]
    finally:
        conn.close()


def delete_monitor(vault_id: str, monitor_id: str) -> bool:
    conn = open_db()
    try:
        cur = conn.cursor()
        # In-flight checks hold this row until their bounded provider call finishes.
        # Once withdrawal returns, no future worker can decrypt/disclose this email.
        cur.execute("DELETE FROM concierge_monitors WHERE vault_id=%s AND id=%s", (vault_id, monitor_id))
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def claim_monitor(*, vault_id: str | None = None, monitor_id: str | None = None,
                  settings: Settings | None = None) -> tuple[str, str] | None:
    require_paid_provider(settings or Settings.from_environment())
    conn = open_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if monitor_id is not None:
            cur.execute("""SELECT id,lease_until,attempted_at FROM concierge_monitors
              WHERE id=%s AND vault_id=%s FOR UPDATE""", (monitor_id, vault_id))
        else:
            cur.execute("""SELECT id,lease_until,attempted_at FROM concierge_monitors
              WHERE background=TRUE AND next_check_at<=NOW()
                AND (lease_until IS NULL OR lease_until<NOW())
              ORDER BY next_check_at,id FOR UPDATE SKIP LOCKED LIMIT 1""")
        row = cur.fetchone()
        if not row:
            return None
        if row["lease_until"] and row["lease_until"] > now_utc():
            raise ProviderError("monitor_check_in_progress", 120)
        if monitor_id and row["attempted_at"] and row["attempted_at"] > now_utc() - timedelta(seconds=60):
            raise ProviderError("monitor_check_rate_limited", 60)
        token = str(uuid4())
        cur.execute("""UPDATE concierge_monitors SET lease_token=%s,
          lease_until=NOW()+INTERVAL '120 seconds' WHERE id=%s""", (token, row["id"]))
        conn.commit()
        return str(row["id"]), token
    finally:
        conn.close()


def perform_monitor_check(monitor_id: str, lease_token: str, *, settings: Settings | None = None) -> dict | None:
    settings = settings or Settings.from_environment()
    require_paid_provider(settings)
    caps = capabilities(settings)
    conn = open_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT * FROM concierge_monitors WHERE id=%s AND lease_token=%s
          AND lease_until>NOW() FOR UPDATE""", (monitor_id, lease_token))
        row = cur.fetchone()
        if not row:
            return None
        row = dict(row)
        vault_id = str(row["vault_id"])
        attempted = now_utc()
        try:
            # This lock makes withdrawal/account deletion serialize with disclosure.
            # No decrypted vault entry or key is loaded by the worker.
            if not row["background"] or not row["email_disclosure_consent"] or row["consent_version"] != CONSENT_VERSION:
                raise ProviderError("consent_required")
            if not _source_owned(cur, vault_id, row["source_item_id"]):
                raise ProviderError("source_item_no_longer_available")
            require_capability(caps, "email_monitoring")
            if row["stealer_logs"]:
                if not row["stealer_disclosure_consent"]:
                    raise ProviderError("consent_required")
                require_capability(caps, "stealer_logs")
            email = unseal(settings, row["key_id"], vault_id, monitor_id, "email", row["email_ciphertext"]).decode()
            provider = HibpProvider(settings, allow_rate_wait=True)
            breaches = provider.email_breaches(email)
            domains = provider.stealer_domains(email, caps["stealer_logs"]["verified_email_domains"]) if row["stealer_logs"] else []
            result = {"breaches": breaches, "stealer_domains": domains}
            status = "found" if breaches or domains else "no_known_findings"
            # Rewrap email and results together so key rotation never mixes key IDs.
            encrypted_email = seal(settings, vault_id, monitor_id, "email", email.encode())
            serialized = json.dumps(result, separators=(",", ":")).encode()
            if len(serialized) + 28 > MAX_PROVIDER_BYTES:
                raise ProviderError("provider_invalid_response")
            encrypted_result = seal(settings, vault_id, monitor_id, "result", serialized)
            cur.execute("""UPDATE concierge_monitors SET status=%s,error_code=NULL,
              retry_after_seconds=NULL,attempted_at=%s,successful_at=%s,
              email_ciphertext=%s,result_ciphertext=%s,key_id=%s,
              next_check_at=%s,lease_until=NULL,lease_token=NULL,updated_at=NOW()
              WHERE id=%s AND lease_token=%s RETURNING *""",
                        (status, attempted, now_utc(), encrypted_email, encrypted_result,
                         settings.active_key_id, attempted + timedelta(seconds=settings.interval_seconds),
                         monitor_id, lease_token))
        except (ProviderError, UnicodeError, ValueError, TypeError) as error:
            # Retain previous encrypted evidence; mark this attempt explicitly failed.
            exc = error if isinstance(error, ProviderError) else ProviderError("monitoring_data_unavailable")
            delay = max(300, exc.retry_after_seconds or 3600)
            cur.execute("""UPDATE concierge_monitors SET status='unavailable',error_code=%s,
              retry_after_seconds=%s,attempted_at=%s,next_check_at=%s,
              background=CASE WHEN %s THEN FALSE ELSE background END,
              lease_until=NULL,lease_token=NULL,updated_at=NOW()
              WHERE id=%s AND lease_token=%s RETURNING *""",
                        (exc.code, exc.retry_after_seconds, attempted,
                         attempted + timedelta(seconds=delay),
                         exc.code in ("source_item_no_longer_available", "consent_required"),
                         monitor_id, lease_token))
        updated = cur.fetchone()
        conn.commit()
        return monitor_view(dict(updated), settings) if updated else None
    finally:
        conn.close()


def run_background_iteration() -> int:
    settings = Settings.from_environment()
    if (not settings.paid_provider_allowed or not settings.enabled or not settings.background_enabled
            or not settings.api_key or not settings.encryption_available):
        return 0
    # One bounded job per iteration; shared leases/budget coordinate replicas.
    claim = claim_monitor(settings=settings)
    if claim is None:
        return 0
    perform_monitor_check(*claim, settings=settings)
    return 1
