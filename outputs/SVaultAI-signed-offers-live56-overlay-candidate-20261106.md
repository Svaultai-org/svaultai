# SVaultAI signed-offer live-schema candidate — 2026-11-06

Status: **local candidate only; not deployed and not a complete raw-PIN retirement**.

## Scope

- Branch `fix/pin-signed-offers-live56-20261106` starts at `1013fff` (live schema 0056).
- Successful OPAQUE login may negotiate an authenticated v3 bearer (50 decoded bytes) with exact read and new-upload PIN-fence bits. Existing, non-negotiating clients retain the 48-byte bearer and current access. New client/server flags default off.
- The server checks signed bits on every request for legacy saved-item reads, file list/download, and new old-style upload starts. Pending old upload finalize/abort remain available. The Flutter HTTP boundary checks the same routes and blocks PIN-bearing requests before transmission.
- `main.py` was copied from the read-only live snapshot SHA256 `49af24c9115aeea691b38cbd9eb779ab01a4abcb4ea7809fada4bcc0d7acf8f7`, then changed only to permit two new CORS capability headers. It preserves live error-log redactions and sync `/health`.
- Runtime backend overlay changes only `/app/auth_local.py`, `/app/routes/auth_zk_routes.py`, and `/app/main.py`; `Dockerfile.signed-offers-live56-overlay` pins exact current base image `sha256:db07d4719ba70581eaa934f78eecd0ce3ddc8d7219d991770abd215240f8e207` and copies only those modules. It is unbuilt because that base image is absent from local Docker.

## Checks completed

- 123 focused backend tests passed using synthetic accounts: signed/old bearer, offer negotiation, route boundaries, CORS, V2 compatibility, and new V2 upload.
- Two schema-0056 UUID/text file-metadata tests passed against disposable PostgreSQL 16; the container was removed. No production database was used.
- 23 focused Flutter transport/login tests passed. A signed-offer web release build completed with four coordinated client flags. The analyzer showed no errors; existing warnings and information notices remain.
- `main.py` minus the two new CORS lines exactly equals the read-only live snapshot. `auth_local.py`, `routes/auth_zk_routes.py`, `zk_migration_flags.py`, `file_v2_client_capability.py`, `device_gate.py`, and `device_monitor.py` at base `1013fff` match the live 349-file manifest.

## Required before release

1. Obtain/load the exact base image, build the three-file overlay locally, validate imports and OPAQUE login against disposable schema 0056, and compare the derived image to the live manifest to prove only three intended runtime files changed. A whole-image build from `1013fff` is unsafe: 32 live Python files differ and 3 are absent from that source tree.
2. Roll out parser-capable backend to **all** instances with issuance flags off. Then enable server offer flags, and only afterward release capable web clients. Mixed old/new backend instances would reject v3 bearers on old nodes.
3. Rollback must keep v3 parsing until negotiated sessions expire or sign out. Reverting to the old parser immediately would log out those sessions; it would not delete vault data.
4. This is partial: unoffered old/mobile sessions, new registration sessions, legacy write/chat routes, and pending upload completion retain older PIN behavior. Finish the broader migration before claiming the vulnerability fully fixed.

The older `test_zk_login_connection_scope_2026_10_14.py` fixture fails six tests already on base `1013fff` because it omits live `pin_verifier` and `file_v2_records`; after a temporary fixture repair, two stale transaction expectations still failed. Those temporary changes were reverted. No production flag, database, running container, or tag was changed.
