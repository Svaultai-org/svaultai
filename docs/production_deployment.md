# VaultAI production deployment

Production plan for the svaultai.com launch. Complements
[../vault_ai_backend/DEPLOYMENT_RUNBOOK.md](../vault_ai_backend/DEPLOYMENT_RUNBOOK.md)
(day-to-day operator instructions) with everything a first-time
deploy needs: DNS, Stripe, database, storage, security, and the
smoke-test that gates go/no-go.

**Do not treat this file as authoritative for security invariants —
it is a checklist. The invariants themselves live in
[security_threat_model.md](security_threat_model.md) and
[security_hardening.md](security_hardening.md).**

---

## Contents

- [1. Production domain plan](#1-production-domain-plan)
- [2. DNS checklist](#2-dns-checklist)
- [3. Backend deployment](#3-backend-deployment)
- [4. Frontend deployment](#4-frontend-deployment)
- [5. Database checklist](#5-database-checklist)
- [6. Stripe checklist](#6-stripe-checklist)
- [7. Storage / file handling](#7-storage--file-handling)
- [8. Security checklist](#8-security-checklist)
- [9. Smoke test plan](#9-smoke-test-plan)
- [10. Known blockers](#10-known-blockers)

---

## 1. Production domain plan

| Domain | Purpose | Serves |
|---|---|---|
| `https://app.svaultai.com`  | User-facing web app | Flutter web build output |
| `https://api.svaultai.com`  | Backend API         | FastAPI (uvicorn), Stripe webhook |
| `https://www.svaultai.com`  | Marketing site      | Static or same web app landing |
| `https://svaultai.com`      | Apex                | 301 → `https://www.svaultai.com` |

Only these four origins are accepted by the backend CORS regex. Any
other origin — including `localhost` — is refused at preflight in
production.

---

## 2. DNS checklist

Before the app goes public:

- [ ] `A`/`AAAA` or `CNAME` for `app.svaultai.com` → frontend host
      (static bucket, Cloudflare Pages, Netlify, Vercel, or nginx
      pointing at Flutter web build output).
- [ ] `A`/`AAAA` or `CNAME` for `api.svaultai.com` → backend host
      (managed container, Kubernetes ingress, or reverse proxy in
      front of `vaultai-backend` container).
- [ ] `A`/`AAAA` or `CNAME` for `www.svaultai.com` → marketing/
      landing host.
- [ ] `A`/`AAAA` for `svaultai.com` apex → same-as-www **or** a
      redirect service that 301s to `https://www.svaultai.com`.
- [ ] `MX` and SPF/DKIM/DMARC records if you plan to send mail from
      the domain (issue-report replies, Stripe receipt reply-to,
      etc.). Not required for the app itself to work.
- [ ] HTTPS certificate provisioned (Let's Encrypt via Caddy /
      Cloudflare / cert-manager / managed platform) on:
    - [ ] `app.svaultai.com`
    - [ ] `api.svaultai.com`
    - [ ] `www.svaultai.com`
    - [ ] `svaultai.com` apex (needed for the 301 to work over HTTPS)
- [ ] `curl -I https://api.svaultai.com/` returns `200`.
- [ ] `curl -I https://app.svaultai.com/` returns `200`.
- [ ] CORS preflight passes:
      ```bash
      curl -i -X OPTIONS https://api.svaultai.com/auth/login \
        -H "Origin: https://app.svaultai.com" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: content-type,x-device-id"
      ```
      Expected: `200`, `access-control-allow-origin: https://app.svaultai.com`,
      `access-control-allow-headers` containing `content-type` and
      `x-device-id`, `access-control-allow-credentials: true`.
- [ ] The **Stripe webhook endpoint** is reachable from the public
      internet: `POST https://api.svaultai.com/billing/stripe/webhook`
      returns `400` (bad signature) rather than `404` or timing out
      when hit with a dummy body.

---

## 3. Backend deployment

### 3.1 Production run command

Bare metal / systemd:

```bash
uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --workers 2
```

Docker (recommended):

```bash
cd vault_ai_backend
docker build -t vaultai-backend:latest .
docker run --rm --name vaultai-backend \
  -p 127.0.0.1:8000:8000 \
  --env-file /path/to/production.env \
  vaultai-backend:latest
```

The [Dockerfile](../vault_ai_backend/Dockerfile) uses a two-stage
build, runs as UID 1001 (`vaultai`), and bakes no secrets. TLS
termination happens at the reverse proxy in front (Caddy, nginx,
Cloudflare, or the managed platform). The container listens on
port `8000` inside the network only.

`vault_ai_backend/[docker-compose.production.example.yml](../vault_ai_backend/docker-compose.production.example.yml)`
is a reference template for a single-node prod deploy.

### 3.2 Boot-time production hardening

`vault_ai_backend/main.py` refuses to boot when `VAULTAI_ENV` reads
as production (`prod`/`production`/`live`) **and** any of the
following are missing or unsafe:

- `VAULT_SESSION_SECRET` — required, ≥ 32 chars, high-entropy.
- `DATABASE_URL` — required.
- `OPENAI_API_KEY` — required if chat/completion is enabled.
- `CORS_ALLOWED_ORIGIN_REGEX` — required, must not be `*`.
- `STRIPE_WEBHOOK_SECRET` — required for billing routes.
- `VAULTAI_DEBUG_ENDPOINTS_ENABLED` must be `false`/unset.
- `VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST` must be `false`/unset.
- Rate-limit backend defaults to redis in prod; the app warns and
  fails closed on high-risk buckets if Redis is unreachable.

All of these are asserted by
`test_production_deployment_readiness_2026_06_30.py` and
`test_stripe_production_hardening_2026_07_02.py` in the backend
test suite.

### 3.3 Alembic migrations

Run on every deploy, before switching traffic:

```bash
alembic upgrade head
```

The migration chain lives at
`vault_ai_backend/migrations/versions/`. `0019_dev_wipe_deletion_reason.py`
is the latest revision and covers the deletion-reason widening for
the dev-only wipe script (which itself refuses to run in prod).

---

## 4. Frontend deployment

### 4.1 Production build

```bash
cd vault_ai_frontend
flutter build web --release \
  --dart-define=BACKEND_BASE_URL=https://api.svaultai.com
```

Output goes to `vault_ai_frontend/build/web/`. That directory is
what you upload to your static host.

The frontend has a **hard rail** in
`vault_ai_frontend/lib/main.dart` (~L595): a release build that is
not pointing at an `https://` backend **throws at startup**. This
means a stray `flutter build web --release` without
`--dart-define=BACKEND_BASE_URL=https://…` fails loudly rather than
shipping a "localhost:8000" build to production.

### 4.2 SPA routing / rewrite

The app uses in-memory Navigator routes (`/auth`, `/login`,
`/signup`, `/unlock`, `/chat`, `/storage`, `/security-center`,
`/devices`, `/vault-frozen`, `/recover`, `/device-pending`, `/pin`).
Every one of them must resolve to `index.html` at the static host
so a page refresh does not 404.

**nginx** rewrite:

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

**Cloudflare Pages / Netlify / Vercel:** built-in SPA fallback —
add a `_redirects` file to `vault_ai_frontend/web/`:

```
/*    /index.html   200
```

**Apache** `.htaccess`:

```apache
RewriteEngine On
RewriteBase /
RewriteRule ^index\.html$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.html [L]
```

### 4.3 Cache-control recommendations

- `index.html`, `flutter_service_worker.js`, `flutter.js`,
  `manifest.json` → `Cache-Control: no-cache, must-revalidate`
- Hashed assets under `/assets/`, `/canvaskit/`, `/icons/` →
  `Cache-Control: public, max-age=31536000, immutable`
- Always send `Content-Encoding: br` or `gzip` for `.js`, `.wasm`,
  `.json`.

### 4.4 Local development

Unchanged: `flutter run -d chrome --web-port 5173` continues to
default to `http://localhost:8000` for the backend. No production
config touches that path.

---

## 5. Database checklist

- [ ] **Managed PostgreSQL** provisioned (Supabase, RDS, GCP Cloud
      SQL, Neon, etc.). Bare-metal self-hosted is fine if you own
      the backup pipeline.
- [ ] `DATABASE_URL` uses `sslmode=require` (or the equivalent
      pooler config that enforces SSL server-side).
- [ ] Alembic migrations run cleanly: `alembic upgrade head`.
- [ ] `SELECT COUNT(*) FROM alembic_version;` returns `1` and the
      row matches `0019_dev_wipe_deletion_reason` or later.
- [ ] Backups enabled (nightly minimum; PITR preferred).
- [ ] **Restore procedure verified** on a staging copy at least
      once — untested backups do not exist.
- [ ] Connection pool sized so `workers × max_connections_per_worker`
      stays under the DB's connection cap. VaultAI uses psycopg2
      with a ThreadedConnectionPool per worker — tune with
      `VAULTAI_DB_POOL_MIN` / `VAULTAI_DB_POOL_MAX` if set.
- [ ] **Least-privilege DB user** — the app user needs `SELECT`,
      `INSERT`, `UPDATE`, `DELETE` on the schema; migration user
      needs `CREATE`, `ALTER`, `DROP`. Do not use a superuser at
      runtime.
- [ ] **Wipe script blocked in production.** The dev-only
      `python -m vault_ai_backend.scripts.wipe_all_test_users`
      refuses to run unless `VAULTAI_ENV` is dev/local/test/ci
      **or** the explicit `VAULTAI_ALLOW_TEST_USER_WIPE=true` env
      override is set. Verify by running the dry-run version in
      staging:
      ```bash
      VAULTAI_ENV=production \
        python -m vault_ai_backend.scripts.wipe_all_test_users --dry-run
      # Expected: refusal message, exit code non-zero, no DB access.
      ```
- [ ] Delete-vault flow verified against a real prod-shaped
      database — the CASCADE FK chain, tombstone insert, and
      session revocation all fire.

---

## 6. Stripe checklist

### 6.1 Live-mode setup

- [ ] Live-mode Stripe account created.
- [ ] Live **product** created (the "VaultAI storage block" or
      whatever the launch name is).
- [ ] Live **price** for the storage block; copy the `price_...`
      id to `STRIPE_STORAGE_BLOCK_PRICE_ID`.
- [ ] Live **API secret key** (`sk_live_...`) in the secret store
      as `STRIPE_API_KEY`.
- [ ] Live **publishable key** (`pk_live_...`) as
      `STRIPE_PUBLISHABLE_KEY`.
- [ ] Live **webhook endpoint** created in the Stripe dashboard
      pointing at `https://api.svaultai.com/billing/stripe/webhook`.
- [ ] Live **webhook signing secret** (`whsec_...`) from the
      dashboard as `STRIPE_WEBHOOK_SECRET`.

### 6.2 Required webhook events

The Stripe webhook must be subscribed to at least:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

Additional events (e.g. `charge.dispute.created`) are optional but
recommended for ops visibility.

### 6.3 URLs

Verify each of these is set exactly to the svaultai.com domain:

```
STRIPE_CHECKOUT_SUCCESS_URL=https://app.svaultai.com/storage?checkout=success
STRIPE_CHECKOUT_CANCEL_URL=https://app.svaultai.com/storage?checkout=cancel
STRIPE_PORTAL_RETURN_URL=https://app.svaultai.com/storage
```

### 6.4 Verify before launch

- [ ] Checkout opens from `https://app.svaultai.com/storage`.
- [ ] Test-mode success → `?checkout=success` return path.
- [ ] Test-mode cancel  → `?checkout=cancel` return path.
- [ ] Test-mode webhook delivery lands and is signature-verified
      (backend logs `[STRIPE] verified event ...`).
- [ ] Storage quota increases after a successful test payment.
- [ ] **Failed payment does NOT grant storage** — tested with
      Stripe's `4000000000000341` (attaches successfully then
      fails on charge).
- [ ] Portal opens and returns to `/storage`.
- [ ] Once verified in test mode, flip to live keys and rerun the
      full checkout with a small real transaction, then refund.

---

## 7. Storage / file handling

- [ ] Upload path (per-vault chunks) points at a **persistent
      volume**, not the container's ephemeral filesystem. If you
      use S3 / GCS, ensure the app-user credentials scope to
      "own bucket, no listing anywhere else".
- [ ] `MAX_JSON_BODY_BYTES` set to the intended production ceiling
      (blank = code default of ~1 MB).
- [ ] `MAX_UPLOAD_BYTES` set to the intended file size cap (blank
      = code default of ~100 MB). The single-upload safety cap is
      documented in the frontend at
      `commonFileUploadSafetyCap` copy.
- [ ] `CHUNK_UPLOAD_MAX_FRAME_BYTES` set (blank = code default).
- [ ] `FILE_SCAN_ENABLED=true` in prod; `FILE_SCAN_PROVIDER` set
      to a real backend (or leave the stub in place until ClamAV
      is wired — the pipeline degrades gracefully).
- [ ] Backup policy documented (which S3 bucket, which retention,
      lifecycle rules) — same document as the DB backup policy.
- [ ] Restore procedure documented and tested end-to-end.
- [ ] `/download-file/*` routes reachable over HTTPS through the
      reverse proxy.

---

## 8. Security checklist

- [ ] No `.env` committed. Verify with `git ls-files | grep '\.env$'`
      — empty is required.
- [ ] No `.venv` committed. Verify with `git ls-files | grep '\.venv'`.
- [ ] No `.claude/` committed. Verify with
      `git ls-files | grep '\.claude'`.
- [ ] No real API keys in the repo. `git grep -nE 'sk_live_[A-Za-z0-9]{16,}'`
      must return only obvious test placeholders.
- [ ] No real Stripe webhook secrets. `git grep -nE 'whsec_[A-Za-z0-9]{16,}'`
      same expectation.
- [ ] No real OpenAI project keys. `git grep -nE 'sk-proj-[A-Za-z0-9]{16,}'`
      returns empty.
- [ ] No real database URL. `git grep -nE 'postgres(ql)?://[^ "]*(pooler|amazonaws|supabase)'`
      returns empty.
- [ ] No private keys, mnemonics, or seed phrases. The security
      hardening test suite already asserts this — run it before
      cutting a release.
- [ ] `VAULTAI_SECURITY_HEADERS_ENABLED=true` in production.
- [ ] `CORS_ALLOWED_ORIGIN_REGEX` restricted to the four svaultai.com
      origins.
- [ ] `VAULTAI_DEBUG_ENDPOINTS_ENABLED=false`.
- [ ] `VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=false`.
- [ ] `RATE_LIMIT_ENABLED=true` + `VAULTAI_RATE_LIMIT_BACKEND=redis`
      with a real `VAULTAI_RATE_LIMIT_REDIS_URL`.
- [ ] High-risk rate-limit buckets (`pin_verify`, `delete_vault`,
      `delete_burst`) **fail closed** if Redis becomes unavailable
      — invariant asserted by
      `test_rate_limit_redis_backend_2026_07_08.py`.
- [ ] Trusted-device gate preserved on all sensitive routes.
      `test_vault_delete_and_inactive_cleanup_2026_07_08.py`
      covers `/vault/delete/*`.
- [ ] Delete-vault gates preserved (trusted device + PIN + exact
      phrase). Delete-vault frontend + backend regression tests
      from
      `delete_vault_session_cleanup_2026_07_09_test.dart` and
      `test_vault_delete_session_revocation_2026_07_09.py`
      cover this.
- [ ] Crypto Vault non-custodial invariants preserved: the schema
      layer rejects `privateKey`, `seedPhrase`, `mnemonic`,
      `recoveryPhrase`, `wif`, `xprv`, `spendKey`, `viewKey`,
      `polyseed`, `walletPassword` field aliases at request-parse
      time.
- [ ] **XMR send is OFF.** `VAULTAI_CRYPTO_XMR_SEND_ENABLED=false`
      and `VAULTAI_CRYPTO_XMR_SCANNER_MODE=none`. Do not flip
      these on until the resident scanner + audited send path
      ships.
- [ ] No buy / sell / trade / swap / stake / bridge / exchange
      surfaces in the UI or the chat classifier. Enforced by
      copy-integrity tests in the frontend suite.

---

## 9. Smoke test plan

Run through this list against `https://app.svaultai.com` immediately
after a production deploy. **Every checkbox is a go/no-go item.**

- [ ] Landing loads at `https://app.svaultai.com`.
- [ ] Sign-up creates an account, sets a PIN, and lands the user on
      the unlocked dashboard.
- [ ] PIN unlock works on a subsequent visit.
- [ ] Trusted-device approval flow works — a fresh device is
      pending, then approvable.
- [ ] File upload succeeds; upload progress renders.
- [ ] File preview + download succeeds for a small image and a PDF.
- [ ] Save a login → visible in the logins list.
- [ ] Save a secure item → visible in the secure items list.
- [ ] Save an ID document → visible in the IDs list.
- [ ] VaultAI Chat: "How much storage am I using?" → renders a
      storage card (not free-form text).
- [ ] VaultAI Chat: "Show my saved logins" → renders a logins card.
- [ ] Help & FAQ opens; a search returns results in the shell
      language.
- [ ] Crypto Vault → receive screen renders for ETH / USDT-ERC20 /
      USDC / SOL / TRX / USDT-TRC20 without errors.
- [ ] Crypto Vault → **XMR screen shows the "scanner-gated"
      messaging**; no balance is fabricated.
- [ ] Storage page → upgrade / manage buttons open Stripe checkout.
- [ ] Complete a small test-mode payment; storage quota increases.
- [ ] Stripe webhook delivery visible in backend logs, signature-
      verified.
- [ ] Log out → session cleared, back button does not re-enter
      authenticated routes.
- [ ] Log back in → previous data intact.
- [ ] Settings → Delete Vault → phrase + PIN → success.
- [ ] After delete: URL bar visits to `/chat`, `/storage`,
      `/security-center` all bounce to `/auth`.
- [ ] After delete + refresh: still logged out. No stale vault
      name in the header.
- [ ] Old session token (captured before delete) returns `401`
      from `curl` against any authed API route.

---

## 10. Known blockers

- **Provisioned but empty**: Redis is required in production
  (`VAULTAI_RATE_LIMIT_BACKEND=redis`). Without it, the app boots
  but degrades to in-memory rate limits — safe for single-node,
  broken for multi-node.
- **DB backup restore not tested**: not a code blocker but a
  release blocker. Restore into a scratch DB before the launch
  window.
- **File scan provider**: currently a stub. Set
  `FILE_SCAN_ENABLED=true` only after the real provider is wired.
- **Monero (XMR)**: launches in receive-only "scanner-gated"
  state. Do not flip `VAULTAI_CRYPTO_XMR_ENABLED=true` or
  `VAULTAI_CRYPTO_XMR_SEND_ENABLED=true` at launch.
- **Store presence**: Play Store / App Store packaging is a
  separate track — see
  [mobile_packaging_readiness.md](mobile_packaging_readiness.md).
