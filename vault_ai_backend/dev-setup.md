# VaultAI — Local Dev Setup (Windows-safe)

Quick reference for getting both halves of VaultAI running on a Windows host. Every command in this doc has been tested against the actual paths used during development (`C:\Users\user\Desktop\Vaultai`). Adjust the drive/user path if your checkout lives elsewhere.

The single most important rule: **always invoke Alembic as `python -m alembic`**, never the bare `alembic` / `alembic.exe`. Windows Application Control on some corporate laptops (including the one this doc was written for) blocks the standalone executable; the module form goes through the regular Python interpreter and works everywhere.

---

## 0. Install dev / test dependencies

Test runner (`pytest`), `httpx` (FastAPI TestClient), and PDF fixture
builders are split into a separate dev manifest so the production
image doesn't carry them. Install both:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the backend test suite (from inside `vault_ai_backend/`):

```powershell
python -m pytest -q
```

DB-bound end-to-end tests skip cleanly unless you set
`VAULTAI_TEST_DATABASE_URL` (a SEPARATE test database — never your
primary `DATABASE_URL`):

```powershell
$env:VAULTAI_TEST_DATABASE_URL = "postgres://USER:PASS@HOST:5432/vaultai_test"
python -m pytest -q
```

If you only want to verify the codebase imports cleanly without
running tests:

```powershell
python -m compileall vault_ai_backend
```

---

## 1. Backend startup

`VAULT_SESSION_SECRET` is **required even in dev**. The legacy
`vaultai-dev-only-fallback-secret-do-not-ship` default was removed
because it became a soft prod-bypass if `VAULTAI_ENV` was ever
misclassified. Use any string ≥ 32 chars for dev; generate one with
`python -c "import secrets;print(secrets.token_urlsafe(48))"`.

```powershell
Set-Location C:\Users\user\Desktop\Vaultai\vault_ai_backend
.\.venv\Scripts\Activate.ps1

$env:VAULTAI_ENV = "local"
$env:VAULT_SESSION_SECRET = "dev-local-session-secret-change-me"
$env:VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST = "true"

python -m alembic upgrade head
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level debug
```

Backend tunables (chunker / retrieval / upload caps / cache TTLs /
billing / media limits) live in `vault_config.py`. Every value is
overridable via env (`VAULTAI_*` prefix); see the dataclass field
names in `vault_config.py` for the full list. `lifespan()` logs
`describe()` at boot so you can audit the active values without
greppting code.

Wait for the line:

```
INFO:     Application startup complete.
```

If you see anything else (errors, exit, "address already in use"), see [§ 6 Troubleshooting](#6-troubleshooting).

Notes:

- `.\.venv\Scripts\Activate.ps1` — the leading `.` is required on PowerShell when execution policy blocks scripts outside the current directory.
- `VAULTAI_ENV=local` switches a handful of safety defaults (relaxed rate limits, looser device-gate behaviour) — never set this on a deployed host.
- `VAULT_SESSION_SECRET` is the HMAC key for session tokens. Any non-empty value works for local dev; rotate it on first deploy.
- `VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=true` auto-approves the first device that signs in so you don't have to do the email-loop dance for every fresh DB.
- The backend reads `DATABASE_URL` from `.env` in the same directory. Make sure it's there before you run `alembic` — Alembic will refuse to start without it.

---

## 2. Frontend startup

```powershell
Set-Location C:\Users\user\Desktop\Vaultai\vault_ai_frontend
flutter run -d chrome `
  --web-port=5173 `
  --web-hostname=localhost `
  --dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Important:

- `--web-hostname=localhost` is required. The backend's CORS regex allows `http://(localhost|127.0.0.1):<port>`; if you let Flutter pick a hostname (e.g. `192.168.x.x` for LAN testing) every API call will fail the preflight.
- `--dart-define=BACKEND_BASE_URL` overrides the compile-time default. Without it, the frontend uses `http://localhost:8000` — which is the same value, so the explicit form is belt-and-braces.
- `--web-port=5173` keeps the dev server on a predictable port so you can bookmark it.

---

## 3. Verify backend

```powershell
# Confirm something is listening on 8000.
netstat -ano | findstr :8000
```

Expected: one or more rows containing `LISTENING` on `127.0.0.1:8000` or `0.0.0.0:8000`. Note the PID in the rightmost column — if uvicorn is bound, that PID should match the `python` process you started.

Then open the auto-generated API docs in a browser:

```
http://localhost:8000/docs
```

You should see the FastAPI Swagger UI. If you get "this site can't be reached", uvicorn isn't actually bound — go back to [§ 1](#1-backend-startup) and read the startup output.

---

## 4. Migration verification

After every `python -m alembic upgrade head`, verify the head matches the latest migration on disk:

```powershell
python -m alembic current
```

Expected output (the exact revision id depends on what's been merged; pick the highest-numbered file in `migrations/versions/`):

```
0004_uploaded_files_content_hash (head)
```

If `current` returns nothing or a lower revision than the highest file in `migrations/versions/`, run `python -m alembic upgrade head` again and watch its output — the real error will be in there.

---

## 5. Uploaded-files duplicate migration verification

Phase 4 (`0004_uploaded_files_content_hash`) added three columns to `uploaded_files`. Confirm they landed with the right types:

```powershell
python -c "import os; from dotenv import load_dotenv; load_dotenv(); import psycopg2; c = psycopg2.connect(os.environ['DATABASE_URL']); cur = c.cursor(); cur.execute(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'uploaded_files' AND column_name IN ('content_sha256','duplicate_of_file_id','version_number') ORDER BY column_name\"); [print(r) for r in cur.fetchall()]; c.close()"
```

Expected output (order alphabetical, types verbatim):

```
('content_sha256', 'text')
('duplicate_of_file_id', 'text')
('version_number', 'integer')
```

Why `duplicate_of_file_id` is `text` rather than `uuid`: `uploaded_files.id` is `TEXT PRIMARY KEY` in the baseline schema, and Postgres rejects a UUID column that references a TEXT primary key with `foreign key constraint cannot be implemented — incompatible types: uuid and text`. Treat the column as an opaque string everywhere (backend already does — `str(existing_match.get("id"))`; frontend uses `String?`).

---

## 6. Troubleshooting

### Frontend says "Failed to fetch" / network errors

The frontend can't reach the backend. Walk through these in order:

1. **Is the backend actually listening?** Run [§ 3](#3-verify-backend). If `netstat` shows nothing on 8000, uvicorn isn't bound — go back to [§ 1](#1-backend-startup).
2. **Is the backend on a different port?** Re-read your uvicorn command. The frontend's default is `http://localhost:8000`; anything else needs an explicit `--dart-define=BACKEND_BASE_URL=...`.
3. **Are you on a LAN / non-`localhost` origin?** Look at the URL in your browser's address bar. If it's `192.168.x.x` or your machine's hostname, the backend's CORS regex won't match — you must use `--web-hostname=localhost` (see [§ 2](#2-frontend-startup)).
4. **Mixed-content (HTTPS frontend → HTTP backend)?** Both sides should be HTTP for local dev. If you're using `flutter run` on a hosted dev origin, switch to local.
5. **Open DevTools → Network**, click the first failing request, and read the actual status / error text. CORS preflight failures show up as red `OPTIONS` rows with no response body.

### `alembic.exe` is blocked by Application Control

Use the module form everywhere:

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic downgrade <revision>
python -m alembic history --verbose
```

Same flags, same behaviour, no `alembic.exe` invocation. This is the canonical form in CI and on every supported host.

### Backend exits during startup (no "Application startup complete.")

The uvicorn lifespan tries to run migrations on import via `RUN_MIGRATIONS_ON_STARTUP=true`. When a migration fails, the error gets buried under a stack trace and uvicorn exits without the friendly startup line.

Run the migration step *outside* uvicorn first to see the real error:

```powershell
python -m alembic upgrade head
```

Common failures:

- **Foreign-key type mismatch** (`incompatible types: uuid and text`) — a migration declared a column type that doesn't match the referenced primary key. The fix is in the migration file; never edit the catalog by hand to "make it work".
- **`DATABASE_URL is not set`** — `.env` is missing or your shell hasn't loaded it. Confirm with `Get-Content .env | Select-String DATABASE_URL`.
- **`could not translate host name`** — DB is unreachable; you're offline or the DB host is wrong.
- **`alembic_version` value too long** — see the long comment in `migrations/env.py`; the wide-column preflight should handle this, but if it ever recurs the table needs to be widened by hand.

### Port 8000 is already in use

Another uvicorn / Python is still running. Find it:

```powershell
netstat -ano | findstr :8000
```

The PID is the last column. Kill it:

```powershell
Stop-Process -Id <pid> -Force
```

Then restart [§ 1](#1-backend-startup).

### `Activate.ps1` blocks with execution-policy errors

PowerShell's default policy refuses unsigned scripts. Allow them for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then re-run `.\.venv\Scripts\Activate.ps1`.

### Migration succeeded but `alembic current` shows the wrong head

You probably have two `.venv`s and the wrong one is on `PATH`. Run `python -c "import sys; print(sys.executable)"` to confirm which interpreter you're using; it should be the one inside `vault_ai_backend\.venv\Scripts\python.exe`.
