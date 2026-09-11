# VaultAI Frontend release runbook

**Scope.** Cutting a fresh Flutter web build for `app.svaultai.com`
so that every open browser tab picks up the new bundle on its next
visibility/resume event — without users needing Incognito, logout,
manual cache clearing, or dev tools.

This runbook is **the update-safe path** authored in the Round-10
stale-cache pass. Follow it verbatim.

---

## 1. Prerequisites

- Fresh `git pull` on the release commit. The release commit must contain the
  current `origin/main`; the build wrapper now refreshes and enforces this.
- `flutter --version` reports the tooling on this build host
  (currently `Flutter 3.38.7` stable; see project root README).
- No local uncommitted changes (`git status --short` empty).
- All backend + frontend tests green (`flutter test`,
  `python -m pytest` under `vault_ai_backend/`).
- No production env changes since the last runbook checkpoint.

## 2. Build

From `vault_ai_frontend/`:

**PowerShell:**

```
.\scripts\build-web-release.ps1 `
  --dart-define=BACKEND_BASE_URL=https://api.svaultai.com `
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=false
```

**POSIX shell:**

```
./scripts/build-web-release.sh \
  --dart-define=BACKEND_BASE_URL=https://api.svaultai.com \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=false
```

Both scripts:

- resolve the current commit SHA and pass it as
  `--dart-define=APP_RELEASE=<short-sha>`;
- run `flutter build web --release --pwa-strategy=none …`
  (`--pwa-strategy=none` writes an empty
  `flutter_service_worker.js` — no offline shell cache is created,
  and old offline-first SWs installed on user browsers are replaced
  on their next visit);
- write `build/web/release.json`:
  ```
  {"commit":"<full sha>","commitShort":"<short sha>","builtAt":"<UTC ISO-8601>"}
  ```

## 3. Atomic rename deploy

On the app server, DO NOT delete the live bundle first. Copy to a
staging directory + rename the symlink:

```
# On app.svaultai.com host
sudo mkdir -p /var/www/vaultai/releases/<short-sha>
sudo rsync -a --delete \
  vault_ai_frontend/build/web/ \
  /var/www/vaultai/releases/<short-sha>/
sudo ln -sfn /var/www/vaultai/releases/<short-sha> /var/www/vaultai/current-next
sudo mv -T /var/www/vaultai/current-next /var/www/vaultai/current
```

`ln -sfn` + `mv -T` is atomic on POSIX and does not create a window
where Nginx serves a half-populated directory.

## 4. Nginx configuration

Nginx cache rules for `app.svaultai.com` are checked into the repo
at [deploy/nginx/app.svaultai.com.conf](../deploy/nginx/app.svaultai.com.conf).
Deploy it and validate before reloading:

```
sudo cp deploy/nginx/app.svaultai.com.conf /etc/nginx/sites-available/
sudo nginx -t
sudo systemctl reload nginx
```

Required response headers on the shell files (do NOT weaken):

| Path | `Cache-Control` |
|---|---|
| `/` | `no-store, no-cache, must-revalidate, max-age=0` |
| `/index.html` | same |
| `/main.dart.js` | same |
| `/flutter_bootstrap.js` | same |
| `/flutter.js` | same |
| `/flutter_service_worker.js` | same |
| `/release.json` | same |
| `/manifest.json` | same |
| `/assets/**`, `/canvaskit/**` | `public, max-age=31536000, immutable` (content-hashed filenames only) |

`etag off` + `if_modified_since off` are set on every shell file so
Nginx cannot return `304 Not Modified` based on stale upstream
metadata.

## 5. Verify cache headers

From an off-network client (or your laptop):

```
curl -sI https://app.svaultai.com/release.json | grep -i cache-control
curl -sI https://app.svaultai.com/main.dart.js | grep -i cache-control
curl -sI https://app.svaultai.com/index.html   | grep -i cache-control
```

Every one MUST return `cache-control: no-store, no-cache,
must-revalidate, max-age=0`.

## 6. Verify the served release matches the intended commit

```
curl -s https://app.svaultai.com/release.json
```

`commitShort` must equal the SHA the build script printed. If it
does not, the atomic rename step did not complete — re-run step 3.

## 7. Verify update detection from a client

- Open a browser tab that was previously logged in against the OLD
  build (do NOT clear cache).
- Wait for the tab to fetch `/release.json` (automatic within
  seconds of tab focus). It should:
  - show the "VaultAI was updated. Refreshing…" banner (or the
    UI's equivalent), or
  - remain silent if the running release already matches. In that
    case, verify `Settings → Build:` reads the new short SHA.
- Verify the previous session (auth token + wallet ciphertext)
  survives the auto-reload — the user must remain signed in with
  their vault accessible.

## 8. Rollback

Rolling back is symmetric with step 3:

```
sudo ln -sfn /var/www/vaultai/releases/<previous-sha> /var/www/vaultai/current-next
sudo mv -T /var/www/vaultai/current-next /var/www/vaultai/current
sudo systemctl reload nginx   # not strictly required, but cheap
```

Every previous release remains untouched in
`/var/www/vaultai/releases/`. The release-update controller will
detect the mismatch on the client and reload into the previous
build without further action.

## 9. What this runbook does NOT do

- **Does not** touch production env vars.
- **Does not** run Alembic migrations.
- **Does not** modify the backend service.
- **Does not** unpause ETH / SOL / TRON send flows.
- **Does not** commit server secrets or machine credentials to the
  repo — only the Nginx skeleton is versioned; TLS certificates,
  upstream host mappings, and other operator-specific values live
  in an out-of-band overlay.

---

## Emergency: user is stuck on an old build

If a specific user reports being unable to update:

1. Ask them to click the "Update now" banner (if visible). This
   invokes `AppReleaseController.applyUpdateAndReload()`, which
   unregisters any leftover service worker + clears the Cache
   Storage entries whose names start with `flutter*` + reloads.
   It does NOT touch `localStorage`, `sessionStorage`,
   `IndexedDB`, or cookies.
2. If no banner appears, ask them to check `Settings → Build:`. If
   the short SHA does NOT match `/release.json`, they are running
   the old bundle and either:
   - the release-update controller has not run yet (very fresh
     tab) — wait 30s, or
   - their browser has an offline-first SW from a pre-Round-10
     build that is still serving the stale shell. Have them force-
     reload once (Ctrl+Shift+R / Cmd+Shift+R). After that, the
     newly-fetched empty SW takes over and future updates work
     automatically.

## Emergency: Nginx returned an old 304

If `curl -sI https://app.svaultai.com/main.dart.js` returns
`Last-Modified` matching the OLD build's timestamp, the rename in
step 3 did not actually swap the symlink or Nginx cached the file
descriptor. Fix:

```
sudo systemctl reload nginx
curl -sI https://app.svaultai.com/main.dart.js | grep -i last-modified
```

The `Last-Modified` should now match the new build's file times.
