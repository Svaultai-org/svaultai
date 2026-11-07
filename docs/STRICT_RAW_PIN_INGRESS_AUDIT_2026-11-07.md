# Strict raw-PIN ingress audit (design only)

Source: isolated code commit `224db39`, parsed from FastAPI's registered route
models under synthetic environment settings. This is a **read-only design
audit**. No strict ingress flag or middleware was enabled, and no production
request, vault, or secret was inspected.

## Exact route inventory

The current application registers **61 method/path entries** whose body model
accepts an authentication `pin` field. Enabling the existing
`VAULTAI_CHUNKED_UPLOADS` flag registers **three more**, for **64 total**.
Optional PIN fields count because a legacy client can still send them.
`pin_value` in a saved login is content, but `/manage/login` also has a
separate authentication `pin`, so it is included. These are registered paths,
including the `/manage` router prefix, not only source decorators.

### Authentication and metadata — 5

- `POST /auth/login`
- `POST /get-or-create-vault-meta`
- `POST /verify-pin`
- `POST /rotate-vault-kdf`
- `POST /vault-stats`

### Legacy saved items and crypto records — 12

- `POST /list-login-names`
- `POST /get-login`
- `POST /delete-login`
- `POST /login-count`
- `POST /update-secure-item`
- `POST /get-secure-item`
- `POST /delete-secure-item`
- `POST /list-secure-items`
- `POST /crypto/save-wallet-profile`
- `POST /crypto/save-sensitive-backup`
- `POST /crypto/reveal-sensitive-backup`
- `POST /crypto/save-note`

### Vault management aliases — 9

- `POST /manage/list-login-names`
- `POST /manage/list-secure-items`
- `POST /manage/logins-full`
- `PATCH /manage/login`
- `DELETE /manage/login`
- `POST /manage/login/delete`
- `PATCH /manage/file`
- `DELETE /manage/file`
- `POST /manage/file/delete`

### Device approval and Security Center — 3

- `POST /devices/request-self-approval`
- `POST /devices/finalize-self-approval`
- `POST /security-center/analyze-passwords`

### Memory — 4

- `POST /memory/list`
- `POST /memory/create`
- `POST /memory/update`
- `POST /memory/delete`

### Files and related lookup — 11

- `POST /download-file/manifest`
- `POST /vault/file/{file_id}/text`
- `POST /files/{file_id}/related`
- `POST /upload-file` (multipart form)
- `POST /name-file` (multipart form)
- `POST /list-files`
- `POST /download-file`
- `DELETE /delete-file`
- `POST /upload-file/init` (registered only when chunked uploads are enabled)
- `POST /upload-file/finalize` (same condition)
- `POST /upload-file/abort` (same condition)

### Imports and analysis — 10

- `POST /imports/start`
- `POST /imports/{import_id}/cancel`
- `POST /imports/{import_id}/complete`
- `POST /vault-analysis/coverage`
- `POST /vault-analysis/drain-text-extraction`
- `POST /vault-analysis/backfill-chunked-text-extraction`
- `POST /vault-analysis/backfill-archive-signals`
- `POST /vault-analysis/deep-answer`
- `POST /vault-analysis/deep-answer/{job_id}/poll`
- `POST /vault-analysis/deep-answer/{job_id}/debug`

### Chat, beneficiary, and vault deletion — 10

- `POST /chat`
- `POST /beneficiary/create`
- `POST /beneficiary/link`
- `POST /beneficiary/list-mine`
- `POST /beneficiary/list-inheritances`
- `POST /beneficiary/request-transfer`
- `POST /beneficiary/cancel-transfer`
- `POST /beneficiary/claim-transfer`
- `POST /beneficiary/delete`
- `POST /vault/delete/confirm`

## Current ingress coverage and bypasses

With every signed-offer bit set, `SignedPrivateChatPreBodyGate` rejects **17
of the 64** entries before calling ASGI `receive`; **47** can still reach
FastAPI body parsing. The 17 are Security Center password analysis; download
manifest; upload-file, init, finalize and abort; deep-answer start, poll and
debug; related-file lookup; beneficiary create, link, request-transfer and
claim-transfer; list-files, download-file and chat. Its check runs only for
`POST`. Other signed-offer route checks in `verify_session_token` run after
FastAPI parses the body. For example, signed item reads protect
`/list-secure-items` and `/get-secure-item` after parsing, not before it.

The signed-offer bits are **feature eligibility**, not a complete OPAQUE vault
identity. An OPAQUE session can have no offer for a feature that lacks parity,
so checking only the bit mask would leave raw-PIN routes open. Any strict
OPAQUE-only policy needs a verified bearer and a database-backed account
classification *before* body parsing. Missing, malformed, duplicate, or
revoked Authorization fields must fail closed on an inventoried route.

`/auth/login` has no authenticated bearer. Its target account is identified
inside the request body, so an account-scoped prebody fence cannot safely
decide whether it is an OPAQUE account without reading that body. A complete
strict cutover must block this legacy endpoint globally, or first build a
separate, explicitly bounded legacy migration protocol.

Several routes accept **either** a raw PIN or a one-time OPAQUE proof on the
same path: beneficiary list/request-transfer/cancel/delete; device self-approval; imports;
vault/file deletion; deep-answer debug; and vault deletion. A path-only
prebody fence cannot allow their proof form while excluding a PIN-bearing
form. To preserve those actions, move proof-only contracts to separate paths
and reject the old mixed path in strict mode. A header that simply claims
“PIN-free” is client-controlled and must not bypass the fence.

Existing multipart upload/name actions and `PATCH`/`DELETE` aliases require
method-aware matching. Do not limit a new gate to JSON `POST` requests or to
literal paths without `{id}` matching. A reverse proxy may already have
received bytes from the client before ASGI rejects them; “prebody” means the
Python application does not call `receive` or parse the request body. Client
network checks remain necessary to prove the client did not transmit a PIN.

The inventory covers the authentication `pin` field in registered request
models and form parameters. Other endpoints may ignore unexpected extra
JSON fields; rejecting such extras needs separate model validation and client
transport tests. `/auth/zk-register-finalize` can receive a `pin_verifier`
(an offline PIN-guessing oracle), which is a separate cutover concern and is
not counted among the 64 raw-PIN routes.

## Safe default-off implementation strategy

1. Introduce a **new backend flag defaulting to false**. With it off, preserve
   every current route and client. Do not tie it to a client-supplied header.
2. Generate an audited startup manifest of `(method, path template)` pairs
   from the 64 request models, including inherited fields and form parameters.
   Check it against a reviewed explicit manifest in a test so a newly added
   PIN route cannot silently escape the gate. Include both chunked-upload
   registration states.
3. In strict mode, an outer ASGI middleware matches method and route template,
   then responds with a neutral `409` and `Cache-Control: no-store` **without
   calling `receive`**. The simplest complete policy blocks all 64, including
   `/auth/login`, regardless of account. This intentionally pauses legacy
   features and must remain off until clients and migrations are ready.
4. If an interim OPAQUE-only policy is required, verify the bearer and look up
   vault type before reading the body; fail closed for invalid or unclassified
   sessions. It still cannot safely exempt `/auth/login` by account, and it
   cannot share old mixed PIN/proof paths. Keep the global strict stage as the
   final acceptance gate.
5. Test every route with a synthetic body and an ASGI `receive` spy: zero body
   reads in strict mode, unchanged behavior with the flag off. Cover JSON,
   multipart, `POST`/`PATCH`/`DELETE`, dynamic IDs, trailing slashes, old and
   signed bearers, duplicate Authorization headers, and both chunked-upload
   configurations. No PIN, token, or content should be logged in failures.

No existing feature or production account was modified by this audit.
