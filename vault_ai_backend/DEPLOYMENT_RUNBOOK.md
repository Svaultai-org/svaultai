# VaultAI — Production Deployment Runbook

Authoritative checklist for taking VaultAI from a clean staging environment to live production. Every step is reversible; do not skip the verification commands.

This document is the deploy-time companion to `BACKUP_AND_RECOVERY.md` (recovery procedures) and the in-source contract tests `test_production_deployment_readiness_2026_06_30.py` (boot-time invariants).

---

## 1. Required environment variables

The backend **refuses to boot** in production when any of the following are missing (enforced by `vault_config._validate_production_requirements`). There is no silent dev-default fallback — the process exits with a `RuntimeError` naming the missing variable.

### 1.1 Hard-required (refuse-to-boot in prod)

| Variable                          | Purpose                                                        | Example                                        |
|-----------------------------------|----------------------------------------------------------------|------------------------------------------------|
| `VAULTAI_ENV`                     | Flip prod path; one of `prod`, `production`, `live`.           | `production`                                   |
| `VAULT_SESSION_SECRET`            | HMAC key for session tokens. Min 32 chars. **No fallback.**    | `<64 random bytes hex>`                        |
| `CORS_ALLOWED_ORIGIN_REGEX`       | Regex matching every legitimate frontend origin.               | `https://(app\|www)\.vaultai\.com`             |
| `DATABASE_URL`                    | Postgres DSN. Hard-required at import; refuse to boot if absent.| `postgresql://user:pass@host:5432/vaultai_prod`|
| `OPENAI_API_KEY`                  | OpenAI API key. Hard-required at import.                       | `sk-...`                                       |

### 1.2 Soft-required (graceful 503 / disabled feature)

| Variable                          | Purpose                                                        | Failure mode                                  |
|-----------------------------------|----------------------------------------------------------------|-----------------------------------------------|
| `STRIPE_API_KEY`                  | Live Stripe secret key. Must start with `sk_live_` in prod.    | Billing endpoints return 503 `stripe_unconfigured`. |
| `STRIPE_WEBHOOK_SECRET`           | `whsec_...` for the live webhook endpoint.                     | Webhook returns 400 on every event.            |
| `STRIPE_STORAGE_BLOCK_PRICE_ID`   | Live Price ID for the $25 / 50GB storage block.                | Checkout-session creation fails.               |

### 1.3 Optional tunables (safe defaults; document overrides per environment)

| Variable                                | Default        | Notes                                              |
|-----------------------------------------|----------------|----------------------------------------------------|
| `MAX_UPLOAD_BYTES`                      | `104857600`    | Single-file upload safety cap (100 MB).            |
| `MAX_JSON_BODY_BYTES`                   | `1048576`      | Non-upload request body cap (1 MB).                |
| `VAULTAI_CRYPTO_REVEAL_LIMIT`           | `5`            | Reveal calls per vault per window.                 |
| `VAULTAI_CRYPTO_REVEAL_WINDOW_SECONDS`  | `60`           | Reveal window in seconds.                          |
| `VAULTAI_AUTH_SIGNUP_LIMIT`             | `20`           | Per-IP signup attempts per hour.                   |
| `VAULTAI_AUTH_LOGIN_LIMIT`              | `30`           | Per-IP login attempts per hour.                    |
| `VAULTAI_AUTH_WINDOW_SECONDS`           | `3600`         | Auth-limit window in seconds.                      |
| `VAULTAI_DEBUG_ENDPOINTS_ENABLED`       | `false`        | **MUST be unset/false in prod.** Boot refuses otherwise. |
| `VAULTAI_RATE_LIMIT_BACKEND`            | `in_memory`    | Set to `redis` for multi-worker deployments.       |
| `VAULTAI_RATE_LIMIT_REDIS_URL`          | (none)         | Required when `VAULTAI_RATE_LIMIT_BACKEND=redis`.  |

### 1.4 Things NOT to set in production

- `VAULTAI_DEBUG_ENDPOINTS_ENABLED=true` — boot refuses.
- Wildcard CORS regex (`.*`) — explicit source guard rejects this.
- Stripe **test** keys (`sk_test_...` / `whsec_test_...`) on the live host.

### 1.5 Boot-time verification

Before flipping DNS to the new backend, hit `/health` from inside the cluster. The endpoint returns `{"status": "ok", "db": "connected"}` on success and `{"status": "unhealthy", "db": "unavailable", "error": "<ClassName>"}` with HTTP 503 on failure. The DSN, password, and host are **never** in the response body.

---

## 2. CORS and domain configuration

The CORS resolver (`main._resolve_cors_origin_regex`) lives in `main.py:633`. Verified by `test_cors_prod_config.py`.

Production rule:
1. Set `CORS_ALLOWED_ORIGIN_REGEX` to a regex covering every legitimate frontend origin.
2. Do NOT set `CORS_ALLOWED_ORIGIN_REGEX=.*`. The source contains no wildcard fallback.
3. Loopback origins (`localhost`, `127.0.0.1`, `0.0.0.0`, `[::1]`, `10.0.2.2`) are **dev only** — they are emitted only when `VAULTAI_ENV` is unset or in `{dev, development, local, test, ci}`.

Verify CORS at deploy:

```bash
# From a non-allowed origin — should NOT include access-control-allow-origin.
curl -i -X OPTIONS https://api.vaultai.com/health \
  -H 'Origin: https://evil.example.com' \
  -H 'Access-Control-Request-Method: GET'

# From the production frontend origin — should include the allow-origin echo.
curl -i -X OPTIONS https://api.vaultai.com/health \
  -H 'Origin: https://app.vaultai.com' \
  -H 'Access-Control-Request-Method: GET'
```

---

## 3. Migrations

VaultAI uses Alembic. Migration files live under `vault_ai_backend/migrations/versions/`. As of 2026-06-30 there are 17 numbered migrations from `0001_baseline_vaultid.py` through `0017_vault_intelligence_summary.py`.

### 3.1 Pre-flight

```bash
cd vault_ai_backend

# 1. Show what is currently applied on the target DB.
alembic current

# 2. Show pending migrations.
alembic history --indicate-current

# 3. Generate a SQL dry-run for review (does NOT execute).
alembic upgrade head --sql > /tmp/vaultai_migrations_dryrun.sql
```

### 3.2 Apply

```bash
# Take a snapshot first (see BACKUP_AND_RECOVERY.md §1.1).
pg_dump --format=custom --no-owner --no-privileges \
  --file=/backups/pre-deploy-$(date +%Y%m%dT%H%M%S).dump \
  "$DATABASE_URL"

# Apply pending migrations.
alembic upgrade head
```

### 3.3 Destructive operation policy

Migrations `0001`–`0004` and `0017` include `DROP TABLE` / `DROP COLUMN` statements, all guarded by `IF EXISTS`. Any new migration introducing a destructive operation MUST:

1. Get a manual snapshot per §3.2 before merging.
2. Carry a one-line `# DESTRUCTIVE:` comment naming the dropped object.
3. Use `IF EXISTS` so a partial-state re-run does not error out.

Encrypted blob columns (`vault_items.encrypted_data`, `uploaded_files.encrypted_file_data`) are NEVER altered in-place — schema changes inside the blob are handled by the `schema` discriminator inside the JSON envelope and a per-record reader fallback in `crypto_schemas.py`.

---

## 4. Stripe production setup

Webhook handler: `routes/stripe_routes.py:463`. Signature verification: `stripe_service.py:1161`. Idempotency: `provider_event_log(source, source_event_id)` composite PK in `stripe_service.py:1213-1252`. Tests: `test_stripe_p1.py`.

### 4.1 Live-keys checklist

1. Generate a **separate** Stripe restricted key for production. Never reuse the staging key.
2. Set `STRIPE_API_KEY=sk_live_...`.
3. In the Stripe dashboard → Developers → Webhooks → add endpoint **exactly** `https://api.vaultai.com/billing/stripe/webhook`. The path is enforced by `test_production_release_hardening_2026_06_30.py::P5`.
4. Subscribe to: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`.
5. Copy the signing secret to `STRIPE_WEBHOOK_SECRET=whsec_...`.
6. In Stripe → Products → create the live `Storage Block — 50 GB / $25` price and set `STRIPE_STORAGE_BLOCK_PRICE_ID`.

### 4.2 Checkout return URLs

`success_url` and `cancel_url` must point to the production frontend, not staging. Verified at runtime — the resolver reads `FRONTEND_BASE_URL` (set by the platform) or the `Origin` header on the request.

### 4.3 Smoke

```bash
# 1. Hit /billing/me with a valid session token. Expected: 200 with
#    {status, account_id, tier_name, storage_limit_bytes, ...}.
curl -H "Authorization: Bearer $SESSION" https://api.vaultai.com/billing/me

# 2. From the Stripe dashboard, click "Send test webhook" → checkout.session.completed.
#    Verify the request shows 200 in Stripe's delivery log.
#    Verify provider_event_log has the new row.

# 3. Resend the same test event. Verify the second delivery still returns 200
#    (idempotent) but does NOT mutate billing state — only the first wins.
```

---

## 5. Storage / file handling

- Upload limit: `MAX_UPLOAD_BYTES` (default 100 MB) enforced by `limit_request_body_size` middleware in `main.py:725`.
- Download requires `verify_trusted_device` and ownership check (`WHERE id = %s AND vault_id = %s`) at `main.py:11913`.
- Storage paths / internal blob keys are **never** returned in error responses (verified by `P2/P6/P8` in `test_production_release_hardening_2026_06_30.py`).
- Quota counter (`bump_vault_total_bytes`) wired on every storage-mutating path: upload, secure-item save, secure-item update, secure-item delete (verified by `P4` in the same test).

For deployments using object storage, the bucket name + access key go in env (do NOT bake into source). The current VaultAI build keeps `encrypted_file_data` in Postgres as a `bytea` column — no separate bucket is required.

---

## 6. Monitoring and logging

- Health endpoint: `GET /health` (200 ok / 503 unhealthy). No auth required.
- Logging is stdlib `logging` (line-oriented). Log redaction is enforced at source level — `test_production_release_hardening_2026_06_30.py` (P2/P6/P7/P8) blocks `logger.info(payload)`, `print(payload)`, f-string payload embedding, and raw-payload `print` arguments in every route file.
- For structured (JSON) logging or APM (Sentry / OpenTelemetry / Datadog), wire the SDK at the lifespan hook (`main.py:208`). The hook is the closed-set place to do that — do NOT scatter SDK imports across route files.

---

## 7. Rate limiting

| Surface                                | Bucket / key            | Default              | Source                                |
|----------------------------------------|-------------------------|----------------------|---------------------------------------|
| Signup                                 | per-IP                  | 20 / hour            | `rate_limit_auth.py:52`               |
| Login                                  | per-IP                  | 30 / hour            | `rate_limit_auth.py:53`               |
| PIN unlock                             | per-vault lockout       | (configurable)       | `vault_core.verify_vault_pin`         |
| `/crypto/reveal-sensitive-backup`      | per-vault               | 5 / 60s              | `rate_limit_crypto_reveal.py`         |
| File ops, chat, billing endpoints      | slowapi decorators      | varies (5–120 / win) | `main.py:10328+`                      |

For multi-worker / multi-replica deploys, switch the limiter backend to Redis:

```bash
export VAULTAI_RATE_LIMIT_BACKEND=redis
export VAULTAI_RATE_LIMIT_REDIS_URL=redis://prod-redis.internal:6379/0
```

In-memory buckets are local to each worker process; in a 4-worker prod box this means a per-IP login limit of 30 effectively becomes 120 unless Redis is in front.

---

## 8. Frontend build (Flutter)

Release-mode HTTPS hard guard at `main.dart:666` — release builds with a non-HTTPS `BACKEND_BASE_URL` throw at boot. Pin tested by `production_deployment_readiness_test.dart::R1`.

### 8.1 Web

```bash
cd vault_ai_frontend
flutter build web \
  --release \
  --dart-define=BACKEND_BASE_URL=https://api.vaultai.com
# Output → build/web/. Upload to the CDN/static host.
```

### 8.2 Android

```bash
flutter build apk \
  --release \
  --dart-define=BACKEND_BASE_URL=https://api.vaultai.com
```

### 8.3 iOS

```bash
flutter build ipa \
  --release \
  --dart-define=BACKEND_BASE_URL=https://api.vaultai.com
```

### 8.4 Verify

- No DEBUG ribbon (R4 pins `debugShowCheckedModeBanner: false`).
- No localhost in the bundled JS (search `build/web/main.dart.js` for `localhost` → only string-table dev defaults, never an active fetch URL).
- Sign in / sign out / PIN unlock work end-to-end against the live API.

---

## 9. Smoke test checklist (post-deploy)

Run these from a fresh browser session and a fresh device.

- [ ] Sign up creates a new account.
- [ ] PIN create + confirm succeeds.
- [ ] Create vault, save a login, save a secure item, log out, log in, items still readable.
- [ ] Upload a 5 MB file. Storage page shows the new total.
- [ ] Upload a 200 MB file fails with `upload_safety_cap_exceeded`.
- [ ] Stripe checkout: free tier → buy 1 storage block → return to `/storage?checkout=success` → `/billing/me` reflects the new limit.
- [ ] Webhook log shows `checkout.session.completed` row in `provider_event_log`.
- [ ] Crypto Vault unlocks for the upgraded user.
- [ ] Save wallet profile → receive QR renders with the public address.
- [ ] Save a sensitive backup (recovery phrase) → reveal flow asks PIN re-check + warning, then shows the cleartext panel; Hide wipes state; Copy requires a 2nd confirm.
- [ ] Reveal endpoint rate-limits at the 6th call in 60s (HTTP 429, `reveal_error: rate_limited`).
- [ ] Save a crypto note and a transaction note. Both surface the pinned safety copy.
- [ ] Delete a secure item → quota counter decreases.
- [ ] Log out → `_VaultCrypto.clearCache` runs, persisted session is gone.

---

## 10. Rollback steps

1. **Revert the backend deploy** to the previous image / commit.
2. **Roll back the migrations** ONLY if a destructive operation was applied. Otherwise leave the schema forward and let the previous app version see the new columns/tables (Alembic migrations are designed to be additive-compatible across two app versions).
3. **Restore the pre-deploy DB snapshot** taken in §3.2 if migrations are non-recoverable. See `BACKUP_AND_RECOVERY.md` §3 for the restore procedure.
4. **Revert the Flutter web bundle** by re-uploading the previous `build/web/` artifact to the CDN.
5. **Stripe webhooks remain pointed at the same URL** — no action needed unless the rollback URL changed.

---

## 11. Day-one operator commands

```bash
# Tail the backend log for fail-closed boot diagnostics.
journalctl -u vaultai-backend -f | grep -E 'vault_config|RuntimeError|ERROR'

# Verify Stripe webhook signatures are passing.
journalctl -u vaultai-backend -f | grep stripe_webhook

# Hit the health endpoint from inside the cluster.
curl https://api.vaultai.com/health

# Check the rate-limit backend in use (in-memory vs redis).
echo "$VAULTAI_RATE_LIMIT_BACKEND"
```

---

## 12. Compliance and policy boundaries

- **No admin** has access to decrypted vault contents. The PIN unlock derives the AES key per-request; the key is never persisted server-side.
- **No support process** that recovers a vault from a forgotten PIN. The recovery flow (inheritance pairing, beneficiary claim) is documented in `project_vaultai_inheritance.md` in the memory store; it never bypasses the PIN.
- **Logs are redaction-pinned** — see `test_production_release_hardening_2026_06_30.py::P2/P6/P7/P8` for the source-level guards.

---

Last reviewed: 2026-06-30. See git for revision history.
