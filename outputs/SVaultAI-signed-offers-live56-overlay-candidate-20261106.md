# SVaultAI signed-offer live-schema candidate — 2026-11-06

Status: **local candidate only; not deployed and not a complete raw-PIN retirement**.

## Scope

- Branch `fix/pin-signed-offers-live56-20261106` starts at `1013fff` (live schema 0056).
- Successful OPAQUE login may negotiate an authenticated v3 bearer (50 decoded bytes) with exact read and new-upload PIN-fence bits. Existing, non-negotiating clients retain the 48-byte bearer and current access. New client/server flags default off.
- The server checks signed bits on every request for legacy saved-item reads, file list/download, and new old-style upload starts. Pending old upload finalize/abort remain available. The Flutter HTTP boundary checks the same routes and blocks PIN-bearing requests before transmission.
- `main.py` was copied from the read-only live snapshot SHA256 `49af24c9115aeea691b38cbd9eb779ab01a4abcb4ea7809fada4bcc0d7acf8f7`, then changed only to permit two new CORS capability headers. It preserves live error-log redactions and sync `/health`.
- Runtime backend overlay changes only `/app/auth_local.py`, `/app/routes/auth_zk_routes.py`, and `/app/main.py`. The exact current base image `sha256:db07d4719ba70581eaa934f78eecd0ce3ddc8d7219d991770abd215240f8e207` was loaded into local Docker under the QA-only tag `svaultai-live-base-qa:db07d471`. `Dockerfile.signed-offers-live56-overlay` copies only those modules. The derived local linux/amd64 image is `sha256:3b93acd0d74f7343b0a4beae6e8e8836b7251c1cb2c4034fd350757707dfb804`.
- The QA-only image tag is `svaultai-signed-offers-qa:20261106`. Its verified gzip Docker archive is `/tmp/svaultai-signed-offers-overlay-20261106.tar.gz` (SHA256 `2c2a4a47ae87b184f6af8302b3946a610aa510c3b6ac8dbf78af0e579e3dc673`, 277 MiB). Source SHA256: `auth_local.py` `2fd3dd61a00b11fb973308a039680d82de640c7a90185c76d72b1bf6795ea1e4`; `routes/auth_zk_routes.py` `6f46c915259057d0e116f4825bbb5335295f3971ade4397b6135cf7b703cd586`; `main.py` `7765554fce39dde37b6240fed1902c689c58d06d331b5ceda2a389a91f99178f`.

## Checks completed

- 123 focused backend tests passed using synthetic accounts: signed/old bearer, offer negotiation, route boundaries, CORS, V2 compatibility, and new V2 upload.
- Two schema-0056 UUID/text file-metadata tests passed against disposable PostgreSQL 16; the container was removed. No production database was used.
- 23 focused Flutter transport/login tests passed. A signed-offer web release build completed with four coordinated client flags. The analyzer showed no errors; existing warnings and information notices remain.
- `main.py` minus the two new CORS lines exactly equals the read-only live snapshot. `auth_local.py`, `routes/auth_zk_routes.py`, `zk_migration_flags.py`, `file_v2_client_capability.py`, `device_gate.py`, and `device_monitor.py` at base `1013fff` match the live 349-file manifest.
- The derived image has the same 349 Python paths as the live image. Hashes differ on exactly the three intended runtime files; no Python file was added or removed.
- In the derived image, imports succeeded and 235 routes mounted. `/health` returned 200 against disposable PostgreSQL 16 with the exact live migration chain upgraded through 0056. A synthetic OPAQUE-finalize route check (protocol proof mocked, real database session issuance) produced signed offer bits `15`; legacy file list and upload-init returned 409 before PIN verification; a non-negotiating old client received the 48-byte bearer; its new login revoked the earlier signed session (401). Browser CORS preflight returned 200 and allowed both new headers. The disposable database and network were removed.
- A separate writer-off read-only web release build passed with `VAULTAI_ENABLE_FILE_V2_UI_READ=true`, `VAULTAI_ENABLE_NEW_FILE_V2_UPLOAD=false`, `VAULTAI_ENABLE_SIGNED_READ_OFFERS=true`, and `VAULTAI_ENABLE_SIGNED_FILE_CREATE=false`. It is local at `/tmp/svaultai-signed-read-only-web-20261106` and was not published.

## Required before release

1. Review the exact-live overlay and its remaining security scope. A whole-image build from `1013fff` remains unsafe: 32 live Python files differ and 3 are absent from that source tree. The local image test used a mocked OPAQUE proof with real session and route handling; it did not establish a production login or physical-device result.
2. Roll out parser-capable backend to **all** instances with `VAULTAI_SIGNED_READ_OFFERS_ENABLED=false` and `VAULTAI_SIGNED_FILE_CREATE_ENABLED=false`. Verify old-client login and health on the deployed image. Mixed old/new backend instances would reject v3 bearers on old nodes.
3. For a read-only first phase, leave signed file-create issuance **off** and use the writer-off web build above. Enable `VAULTAI_SIGNED_READ_OFFERS_ENABLED=true` only after every backend instance parses v3, then publish the matching read-only web build. Do not enable `VAULTAI_SIGNED_FILE_CREATE_ENABLED` or the web `VAULTAI_ENABLE_SIGNED_FILE_CREATE` flag in that phase. Old uploads remain available and may still send PINs, so this is not a full PIN fix.
4. To roll back after any v3 issuance, first restore a web build that does not request signed offers, then disable server issuance flags. Keep the v3 parser backend until all issued sessions expire or users sign out. The default session lifetime is seven days and the configured maximum is 30 days; check the actual server TTL before setting a removal date. Reverting immediately to the old parser would log out v3 sessions, without deleting vault data.
5. This is partial: unoffered old/mobile sessions, new registration sessions, legacy write/chat routes, and pending upload completion retain older PIN behavior. Finish the broader migration before claiming the vulnerability fully fixed.

The older `test_zk_login_connection_scope_2026_10_14.py` fixture fails six tests already on base `1013fff` because it omits live `pin_verifier` and `file_v2_records`; after a temporary fixture repair, two stale transaction expectations still failed. Those temporary changes were reverted. No production flag, database, running container, or tag was changed.

**Decision:** GO for local technical overlay viability; NO-GO for claiming the full vulnerability fixed or activating negotiated offers in production. Backend parser rollout can be assessed separately with all issuance flags off after review.
