# Zero-knowledge migration non-regression baseline

Date: 2026-08-07 (Asia/Singapore)

## Scope and safety boundary

This document records the pre-migration behavior and release gates required by the zero-knowledge migration preservation rule. No crypto, authentication, persistence, production configuration, or production data was changed while producing this baseline. No migration was run.

The migration objective is narrowly limited to removing operator access to plaintext and plaintext-capable keys. It must not redesign unrelated product behavior.

## Source and release state

- Local HEAD: `ee4ec6d1ec4c182d08410996b7a65ffa2dd75971`
- `origin/main`: `ee4ec6d1ec4c182d08410996b7a65ffa2dd75971`
- Last deployment explicitly reported by the owner: `d99a6213d634c90b5cc17188ee3b782fa2ea1fa1`
- The ignored local production build configuration currently embeds release `52d06a51edb8d8217d7d305b019662638357c800`, which does not match HEAD. This is a release-metadata gate; the local configuration was not edited.
- Existing untracked release, staging, local configuration, and test-failure directories were preserved and were not added to source control.

## Test and build baseline

| Gate | Result | Evidence |
|---|---|---|
| Backend full suite (backend working directory) | PASS | 8,289 passed, 140 skipped, 9,632 subtests passed; 224.15 s; one PyPDF2 deprecation warning |
| Backend suite invoked from repository root | HARNESS FAILURE | Five collection-time structural tests assume the backend working directory and cannot find `routes/login_routes.py`; the same full suite passes from the supported backend directory |
| OPAQUE wrapper/API focused tests | PASS / PLATFORM SKIP | 15 passed; native wire interop skipped because the `vaultai_opaque_server` wheel is intentionally unavailable on this Windows host and is installed in the Linux/Docker builder |
| Flutter complete suite | INCOMPLETE / GATE | `flutter test` became idle with no CPU progress and no output for more than 12 minutes; the owned stalled test process was terminated |
| Flutter protected-domain focused run | FAIL | 403 passed, 28 failed; each of the four affected files was rerun in a fresh process and remained reproducibly failing |
| OPAQUE typed-failure focused file | FAIL | 8 passed, 1 failed |
| ZK lifecycle crypto-context focused file | FAIL | 14 passed, 1 failed |
| FAQ completeness/naming focused file | FAIL | 6 passed, 13 failed |
| Help Center FAQ i18n focused file | FAIL | 10 passed, 13 failed |
| Wallet/network/local-signing focused run | FAIL | 745 passed, 1 failed; failure reproduces alone in mobile mixed-items overflow test (17 passed, 1 failed in its file) |
| Production web build | PASS | `flutter build web --release --dart-define-from-file=.config/production.json`; JavaScript release built successfully; WebAssembly dry-run advisories only |
| Signed Android APK | PASS (build/signature only) | Release APK built (94,056,367 bytes); APK Signature Scheme v2 verified; not installed or uploaded |
| Signed Android AAB | PASS (build/signature only) | Release AAB built (64,368,406 bytes); JAR signature verified; expected self-signed/timestamp and current JDK Zip/JAR consistency warnings recorded; not uploaded |
| Android runtime regression | NOT RUN / ENVIRONMENT GAP | No connected Android device or emulator was available |
| iOS simulator regression | NOT RUN / ENVIRONMENT GAP | iOS simulator is unavailable on this Windows host |

### Reproducible focused failures

1. Typed `OpaqueAuthenticationFailed` handling test reports that the failure path falls through to legacy `/auth/login` behavior.
2. ZK lifecycle crypto-context test reports a mismatch in the login/chat/rotate/logout/restore lifecycle contract.
3. FAQ and Help Center tests report backend/frontend ID drift, naming/copy drift, missing localized entries/search matches, category/content coverage differences, and missing localized page text.
4. `logins_page_crypto_wallet_leak_fix_2026_07_08_test.dart` reports two unexpected layout exceptions at 400x900 with mixed items.

These failures predate any migration implementation in this task. They are not waived: all remain release gates until fixed or replaced with evidence-backed current behavioral contracts.

## Current crypto-version characterization

- OPAQUE and client-held vault-key flows exist alongside legacy compatibility behavior.
- Inheritance credential packages explicitly use `crypto_version = 1` and validate that wire format.
- No general record-level `legacy_v1` / `client_mvk_v2` discriminator was found for files, credentials, memories, wallet records, or general chat-related encrypted records.
- No proven dual-read/new-write, item-level rollback, or interrupted-migration state machine exists for the requested content migration.

Therefore migration implementation must stop before changing record encryption or reads. Adding a new path without explicit versioning and rollback would make old/new records ambiguous and violate the preservation rule.

## Protected-feature matrix

| Domain | Legacy/current baseline | New `client_mvk_v2` path | Web | Android | iOS | Rollback |
|---|---|---|---|---|---|---|
| OPAQUE login, device approval, sessions | Backend suite passes; focused Flutter has two reproducible contract failures | Not implemented | Build only | Build only | Not available | Not tested |
| Chat, multilingual routing, correlation, cancel/retry | Backend suite passes; selected Flutter chat tests included in combined run | Not applicable yet | Build only | Build only | Not available | Not tested |
| Files/uploads/previews/deletes | Backend suite passes; selected Flutter tests included | Not implemented | Build only | Build only | Not available | Not tested |
| Credentials/login fields/reveal/copy/edit | Backend suite passes; selected Flutter tests included | Not implemented | Build only | Build only | Not available | Not tested |
| Memories | Backend suite passes; selected Flutter tests included | Not implemented | Build only | Build only | Not available | Not tested |
| Wallet: EVM, Solana, TRON, Monero | 745/746 focused tests pass; mobile mixed-items layout fails | Not implemented | Build only | Build only | Not available | Not tested |
| Inheritance, X25519 escrow/reveal/video | Backend suite passes; focused Flutter coverage included; current wire crypto version is 1 | Not implemented | Build only | Build only | Not available | Not tested |
| Video recorder/viewer and navigation cleanup | Focused Flutter test included in combined run | Not applicable | Build only | Build only | Not available | Not tested |
| Help/FAQ/SEO/public metadata | Backend passes; 26 isolated FAQ/Help failures | Not applicable | Build only | Build only | Not available | Not applicable |

“Build only” is intentionally not recorded as runtime acceptance.

## Required migration contract before implementation

1. Define an immutable per-item crypto discriminator with explicit values `legacy_v1` and `client_mvk_v2`.
2. Specify authenticated metadata, key derivation, nonce rules, algorithms, and corruption behavior for `client_mvk_v2`.
3. Implement dual-read without changing legacy records; make new writes use the new format only behind an off-by-default scoped feature gate.
4. Add characterization tests for every protected domain before switching its write path.
5. Define reversible item states such as `legacy`, `migration_started`, `v2_verified`, and `legacy_retained`; never migrate during login.
6. Require client-side decrypt/re-encrypt/verify per item, with resumability, idempotency, explicit user action, and no server plaintext/key visibility.
7. Preserve the legacy ciphertext until the client verifies the new ciphertext and the rollback window closes under an owner-approved policy.
8. Exercise rollback at each phase and prove old clients either read safely or fail with an explicit unsupported-version response.
9. Re-run the entire matrix on web, authenticated Android, and iOS before any production migration or deployment.

## Stop conditions

Stop immediately if any record lacks an unambiguous version, rollback cannot restore the prior readable item, a client must expose plaintext/key material to the server, login would trigger migration, a protected route changes semantics, or any baseline gate regresses. Production mutation and deployment require separate owner review and authorization.
