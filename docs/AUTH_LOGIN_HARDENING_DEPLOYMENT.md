# Production API documentation and response-header hardening

The application removes `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, and
`/redoc` when `vault_config.is_production()` is true (`prod`, `production`, or
`live`). Development documentation remains available. This protects direct
backend access as well as requests forwarded through alternate proxies.

The production nginx API template lives at
`deploy/nginx/api.svaultai.com.conf`. Adapt the existing live API server block
in place; retain its certificates, upstream address, logs, timeouts, and other
operational settings. Install these two snippets before referencing them:

```
deploy/nginx/snippets/svaultai-api-security-headers.conf
deploy/nginx/snippets/svaultai-hide-api-docs.conf
```

Their target paths are `/etc/nginx/snippets/` with the same filenames. The
headers snippet supplies HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
and Referrer-Policy with `always`, including 400, 404, 429, and proxy errors.
Hide the five equivalent upstream headers as shown in the template to avoid
duplicate policies. Preserve the application's CORS and cache headers.

The strict API CSP is intended for the API host. Do not add it to the Flutter
HTML host: Flutter uses WebAssembly, inline boot scripts/styles, and renderer
assets that need their own audited policy. The production docs-denial snippet
may also be added to the web server to deny `/api/docs`, `/api/openapi.json`,
and `/api/redoc` aliases before they reach its `/api/` proxy.

On nginx 1.24, a child `location` or `if` defining any `add_header` stops
inheriting all parent `add_header` directives. Include the API header snippet
again inside such API locations. Do not use `add_header_inherit merge`, which
requires nginx 1.29.3. Verify the rendered configuration with `nginx -t` before
an atomic config replacement and graceful reload.

The proxy should overwrite `X-Forwarded-For` with the actual peer address at
the trusted public edge. If another trusted proxy or CDN is in front, retain
its separately verified real-IP configuration rather than trusting arbitrary
client headers. Restrict direct backend access to trusted ingress.

## Verification

Run `test_production_api_docs_2026_10_14.py` for production-token variants,
development documentation, query strings, trailing slashes, and the Swagger
OAuth redirect. These tests do not enter the service lifespan.

After deployment, verify HTTP 404 for the schema, both documentation UIs,
trailing-slash variants, `/docs/oauth2-redirect`, and any `/api/` aliases. Check
that the five nginx headers appear once on an ordinary API response, rejected
login, docs 404, login 429, and an isolated upstream-error probe. Recheck the
allowed-origin OPTIONS preflight and one legitimate authenticated login.

The login performance and limiter smoke test must use a synthetic, invalid
vault identifier, never a real user's credentials. Confirm the supplied
malformed-lookup reproduction returns HTTP 400 in less than one second, then
send twenty rapid attempts and confirm 429 responses with a finite retry
period. Do not turn a temporary rate-limit failure into a persisted PIN strike
or permanent vault lockout.
