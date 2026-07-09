# Frontend hosting (Flutter web on app.svaultai.com)

Everything the static host needs to serve the VaultAI web app
correctly. Pairs with [production_deployment.md](production_deployment.md).

---

## 1. Build

```bash
cd vault_ai_frontend
flutter pub get
flutter build web --release \
  --dart-define=BACKEND_BASE_URL=https://api.svaultai.com
```

- Output: `vault_ai_frontend/build/web/`.
- **Do not** run `flutter build web --release` without the
  `--dart-define=BACKEND_BASE_URL=https://…`. The app has a
  release-mode guard (`vault_ai_frontend/lib/main.dart` ~L595)
  that **throws at startup** if `BACKEND_BASE_URL` is not an
  `https://` URL. This is a deliberate safety rail so a stray
  local-default build cannot ship.
- Local development is unchanged — `flutter run -d chrome
  --web-port 5173` defaults to `http://localhost:8000`.

Optional flags for release:

```bash
--web-renderer=canvaskit           # sharper rendering, ~4 MB extra
--source-maps                      # if your host serves them
--pwa-strategy=offline-first       # if you want the SW to cache
```

---

## 2. Upload

The contents of `build/web/` become the site root. The tree is:

```
build/web/
├── assets/
├── canvaskit/
├── icons/
├── flutter.js
├── flutter_service_worker.js
├── flutter_bootstrap.js
├── main.dart.js
├── index.html
├── manifest.json
└── favicon.png
```

Push this directory to your static host of choice — Cloudflare
Pages, Netlify, Vercel, S3 + CloudFront, nginx, or a bare bucket.

---

## 3. SPA rewrite (required)

The Flutter app is a single-page app. Every route that the user
can land on (via bookmark, refresh, or back-forward) must resolve
to `index.html`, not 404. Known routes:

```
/         /auth        /login       /signup      /unlock
/pin      /vault-frozen/recover     /chat        /device-pending
/devices  /security-center          /storage
```

**nginx**

```nginx
server {
    listen 443 ssl http2;
    server_name app.svaultai.com;

    root /var/www/vaultai-web;
    index index.html;

    # SPA fallback.
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Long-cache immutable assets.
    location ~* ^/(assets|canvaskit|icons)/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    # Short-cache the shell.
    location = /index.html {
        add_header Cache-Control "no-cache, must-revalidate";
    }
    location = /flutter_service_worker.js {
        add_header Cache-Control "no-cache, must-revalidate";
    }
    location = /manifest.json {
        add_header Cache-Control "no-cache, must-revalidate";
    }

    # Compression.
    gzip on;
    gzip_types text/plain application/javascript application/json
               text/css application/wasm image/svg+xml;
    brotli on;
    brotli_types text/plain application/javascript application/json
                 text/css application/wasm image/svg+xml;
}
```

**Cloudflare Pages / Netlify** — add `vault_ai_frontend/web/_redirects`:

```
/*    /index.html   200
```

Cloudflare Pages / Netlify apply this automatically at deploy time.

**Vercel** — add `vercel.json` at the project root:

```json
{
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

**Apache** — `.htaccess`:

```apache
RewriteEngine On
RewriteBase /
RewriteRule ^index\.html$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.html [L]
```

---

## 4. Cache-Control policy

| Path pattern | Header |
|---|---|
| `/index.html`, `/flutter_service_worker.js`, `/manifest.json`, `/flutter.js`, `/flutter_bootstrap.js` | `Cache-Control: no-cache, must-revalidate` |
| `/assets/**`, `/canvaskit/**`, `/icons/**` (hashed) | `Cache-Control: public, max-age=31536000, immutable` |
| `main.dart.js` (regenerated every build) | `Cache-Control: no-cache, must-revalidate` |
| `*.wasm`, `*.data` | `Cache-Control: public, max-age=31536000, immutable` |

Rationale: hashed assets can be cached forever because their name
changes when the content changes; the shell (`index.html` +
service worker) must NOT be cached long or users will not see the
new version of the app on the next deploy.

---

## 5. HTTPS

- Serve only over HTTPS. Redirect HTTP → HTTPS at the host.
- Enable HSTS (`Strict-Transport-Security: max-age=63072000;
  includeSubDomains; preload`) — the backend already emits it in
  production; the frontend host should mirror it.
- Cert renewal automated (Let's Encrypt, cert-manager, Cloudflare
  managed cert). Do not manually renew.

---

## 6. Security headers (mirror what the backend sets)

If the static host lets you add headers, add these on top of the
SPA rewrite:

```
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Permissions-Policy: geolocation=(), camera=(), microphone=(), ...
X-Frame-Options: DENY
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
```

CSP is trickier for Flutter web because of CanvasKit's WASM +
inline styles. Start from the backend's CSP
(`vault_ai_backend/security_headers.py :: CSP_STRICT`) and relax
only what CanvasKit demands:

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'wasm-unsafe-eval';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: blob:;
  font-src 'self' data:;
  connect-src 'self' https://api.svaultai.com;
  media-src 'self' blob:;
  object-src 'none';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self'
```

Note the explicit `connect-src` allowlist — the app talks to
`https://api.svaultai.com` and nothing else.

---

## 7. Health check

- `https://app.svaultai.com/` returns 200 with an HTML body
  containing the string `<flutter-view` (Flutter's mount point).
- After a hard refresh at `https://app.svaultai.com/chat`, the
  page loads (not 404, not the raw filesystem).
- Network tab shows the first fetch is to
  `https://api.svaultai.com/…`, not `localhost`. This is your
  quickest check that the release build wasn't accidentally shipped
  with the local backend URL baked in.
