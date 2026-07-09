# VaultAI rate limits

Complete list of every rate-limit bucket VaultAI enforces, what it
protects, its default, and the env var that overrides it.

Buckets isolate cost across routes: a burst on one route can't
drain another route's budget. Every 429 returns the same body
shape and does NOT reveal whether an account or vault exists.

Response shape on limit hit:

```json
{
  "detail": {
    "code": "rate_limited",
    "message": "Too many requests. Please wait and try again.",
    "reset_in_seconds": 3600
  }
}
```

with `Retry-After: <seconds>` header.

## Backend

Two implementations coexist:

- **slowapi** — IP-based per-route limits via `@limiter.limit(...)`
  decorators in `main.py`. In-memory by default.
- **rate_limit_backend.py** — the module used by `rate_limit_auth`,
  `rate_limit_crypto_reveal`, and `rate_limit_sensitive`. Supports
  in-memory (default) and Redis (for clustered deploys).

### Backend selection

```
# Explicit override — use "redis" or "in_memory". Leave blank to
# auto-detect: if a Redis URL is present, Redis is used; otherwise
# the in-memory backend runs.
VAULTAI_RATE_LIMIT_BACKEND=

# Redis URL. Either env var name works; VAULTAI_RATE_LIMIT_REDIS_URL
# takes precedence if both are set.
VAULTAI_RATE_LIMIT_REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_REDIS_URL=
```

Production without a Redis URL falls back to the in-memory backend
and emits a `WARNING` at boot on the `rate_limit_backend` logger:

```
[RATE-LIMIT] production is running with the in-memory rate-limit
backend. Multi-instance deployments SHOULD set
VAULTAI_RATE_LIMIT_REDIS_URL so rate limits are enforced across
replicas.
```

A single-instance production deploy is *safe* on the in-memory
backend — the warning exists so an operator running >1 replica does
not silently ship with per-replica counters.

### Redis backend implementation

`RedisRateLimitBackend.check_and_increment` runs a single Lua
script inside Redis so the check + increment is atomic:

  1. `ZREMRANGEBYSCORE key 0 (now - window)` — drop expired.
  2. `ZCARD key` — how many hits inside the window.
  3. If ≥ limit → return denied with `reset_in_seconds` computed
     from the oldest surviving hit.
  4. Otherwise `ZADD key now unique_member` and
     `PEXPIRE key window+1s`.

Two backend instances pointing at the same Redis observe one shared
counter, which is the whole point of moving off in-memory. The Lua
script is loaded once with `SCRIPT LOAD` and reloaded on
`NoScriptError`.

### Key hashing

Both backends hash the caller's `user_id` before it becomes a key:

```
key = "rl:v1:" + bucket + ":" + sha256(user_id)[:16]
```

Raw IPs, vault ids, device ids, emails, or session tokens NEVER
appear in Redis command logs or in the in-memory dict. Bucket names
(e.g. `auth_login`) are closed-set operational text and stay
plaintext for grep-ability.

### Redis outage behaviour — fail-closed vs fail-open

Every bucket is classified as HIGH or LOW risk. When Redis is
unreachable, or when SCRIPT LOAD or EVALSHA raises:

| Risk | Buckets | Outage policy |
|---|---|---|
| High | `auth_signup`, `auth_login`, `pin_verify`, `delete_vault`, `crypto_reveal`, `upload_burst`, `delete_burst`, `export` | **fail closed** — return a denied decision with `reset_in_seconds = window_seconds` |
| Low | `chat` | **fail open** — allow the request through so a Redis blip does not brick user chat |

Fail-closed prevents a Redis outage from becoming a distributed
brute-force window. Fail-open protects UX where the operator has
decided the read is not sensitive enough to lock out real users.

An unknown bucket (someone adds a new one and forgets to classify
it) is treated as HIGH risk by default — the safer failure mode.

### Redis URL redaction in logs

`RedisRateLimitBackend.health()` returns the URL with the userinfo
stripped:

```
redis://alice:supersecret@r.example.com:6379/0
    → redis://r.example.com:6379
```

Nothing else in the module logs the raw URL.

## Per-bucket configuration

### Auth
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `auth_signup` | Prevent signup floods per IP | 20 / hour | `VAULTAI_AUTH_SIGNUP_LIMIT`, `VAULTAI_AUTH_WINDOW_SECONDS` |
| `auth_login` | Prevent credential stuffing per IP | 30 / hour | `VAULTAI_AUTH_LOGIN_LIMIT`, `VAULTAI_AUTH_WINDOW_SECONDS` |

Wired: `routes/auth_routes.py::signup` and `::login`.

### PIN + unlock
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `pin_verify` | Rate limit on `/verify-pin`; complements the 5-strike vault lockout | 30 / hour per vault+IP | `VAULTAI_RL_PIN_VERIFY_LIMIT`, `VAULTAI_RL_PIN_VERIFY_WINDOW_SECONDS` |

Wired: `main.py::verify_pin_endpoint`.

The 5-strike vault lockout in `vault_core.py` (`MAX_PIN_ATTEMPTS`,
`PIN_LOCKOUT_HOURS`) still applies on top of this — a single
attacker will hit the vault lockout after 5 wrong PINs even if the
HTTP rate limit hasn't fired.

### Chat
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `chat` | Cap LLM-cost per vault | 120 / 10 min per vault+IP | `VAULTAI_RL_CHAT_LIMIT`, `VAULTAI_RL_CHAT_WINDOW_SECONDS` |

Wired: `main.py::chat_endpoint`. Slowapi's `5/minute` IP limit runs
in parallel.

### Delete vault
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `delete_vault` | Cap on all three delete endpoints | 10 / hour per vault+IP | `VAULTAI_RL_DELETE_VAULT_LIMIT`, `VAULTAI_RL_DELETE_VAULT_WINDOW_SECONDS` |

Wired: `routes/vault_delete_routes.py` all three endpoints.

A legitimate delete-vault flow needs at most one status + one
request + one confirm — the default cap of 10/hr allows for retries
and errors without letting an attacker cycle through the flow
repeatedly.

### Mass-action burst guards
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `upload_burst` | Ransomware-style mass upload guard | 100 / minute per vault | `VAULTAI_RL_UPLOAD_BURST_LIMIT`, `VAULTAI_RL_UPLOAD_BURST_WINDOW_SECONDS` |
| `delete_burst` | Ransomware-style mass delete guard | 50 / minute per vault | `VAULTAI_RL_DELETE_BURST_LIMIT`, `VAULTAI_RL_DELETE_BURST_WINDOW_SECONDS` |

Wired via `rate_limit_sensitive.enforce_upload_burst_rate_limit`
and `.enforce_delete_burst_rate_limit`. These are per-vault: they
protect a single vault against a compromised session, not the
whole app.

### Export
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `export` | Cap on any export-vault action | 5 / hour per vault | `VAULTAI_RL_EXPORT_LIMIT`, `VAULTAI_RL_EXPORT_WINDOW_SECONDS` |

Wired: any export route MUST call
`rate_limit_sensitive.enforce_export_rate_limit(vault_id=...)`
before running.

### Crypto reveal
| Bucket | Purpose | Default | Env vars |
|---|---|---|---|
| `crypto_reveal` | Cap on `crypto/reveal-sensitive-backup` per vault | 5 / 60s | (baked in) |

Wired: `routes/login_routes.py::crypto_reveal_sensitive_backup`.

## Adding a new rate-limited route

1. Pick or add a bucket in `rate_limit_sensitive.py`. Give it its
   own env-configurable limit + window. Do NOT reuse an existing
   bucket for a different route — buckets isolate cost.
2. Import the enforce function and call it inside the route handler
   BEFORE any expensive work.
3. Emit a `security_event_log` line when the limit fires so we can
   detect abuse patterns.
4. Add a test in the security suite that:
   - the rate limit fires at N+1 requests
   - the 429 body is the generic `Too many requests.` message
     (does NOT reveal whether the account exists)
   - the `Retry-After` header is present
   - the `security_event_log` line is emitted with the closed-set
     reason.

## When 429 alone is not enough

Rate limits protect the API. They do not protect the underlying
account. For anything that could brute-force a secret (PIN, seed,
etc.), the rate limit MUST compose with an account-level counter
(vault lockout, session revoke, etc.) so an attacker distributing
across IPs can't sidestep it.
