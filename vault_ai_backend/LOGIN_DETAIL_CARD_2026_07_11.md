# VaultAI login detail card — 2026-07-11

Product decision: an authenticated user with an unlocked vault who explicitly asks to show / open / reveal / copy a specific saved login sees the actual credential details in the chat card immediately — no PIN prompt, no trusted-device gate, no confirmation card.

**Not committed. Not pushed. Not deployed.**

---

## Exact behavior implemented

**Router intent → card view mapping (all specific-service phrasings):**

| User phrase | Intent | Router card | Populated view |
|---|---|---|---|
| "show me my American First Credit Union login" | `vault_login_search` | `vault_login_card` view=`detail` | 1 match → `detail` / >1 → `chooser` / 0 → `not_found` |
| "open my Gmail login" | `vault_login_search` | detail | same |
| "show my Chase account" | `vault_login_search` | detail | same |
| "show me that login" (pronoun follow-up) | resolves via `vault_chat_active_entity` → `vault_login_search` | detail | same, plus `pending_action` from the verb |
| "reveal my Netflix password" | `vault_login_reveal` | detail | same |
| "copy my Netflix password" | `vault_login_copy` | detail | same |
| "edit it" | pronoun → login_search | detail + `pending_action=edit` | frontend opens edit dialog on mount |
| "delete it" | pronoun → login_search | detail + `pending_action=delete` | frontend opens delete confirmation |
| "copy the password" | pronoun → login_search | detail + `pending_action=copy_password` | frontend auto-copies |
| "open the website" | pronoun → login_search | detail + `pending_action=open` | frontend opens website URL |
| "change the password to X" | populates edit mode — Save required | detail + `pending_action=edit` | user then explicitly Saves |

**List / duplicates / not-found paths are UNCHANGED and still mask.** No plaintext password ever appears in a `view=list`, `view=duplicates`, `view=chooser`, or `view=not_found` payload.

**Detail card contents (only when view=detail):**

- `id`, `title`, `service`
- `username` (plaintext)
- `password` (plaintext)
- `domain`, `website` (plaintext URL)
- `notes` (plaintext, if any)
- `updated_at`, `generated`
- `pending_action` (verb tag: `edit` / `delete` / `copy_password` / `copy_username` / `open`)

**Frontend actions on the detail card:**

- Copy username → clipboard
- Copy password → clipboard
- Open website → external URL launcher
- Edit → opens existing `SecureItemEditDialog` (via `onSecureItemEdit(title, 'login')`)
- Save → runs through existing encrypted-storage flow (`updateVaultSecureItem`)
- Delete → opens existing accidental-action confirmation (via `onSecureItemDelete(title, 'login')`) — NOT a PIN/identity challenge

**Mobile layout:** `_LoginDetailCard` uses `VaultResponsive` for narrow-phone breakpoints. Fields are stacked vertically with a compact copy icon on each. Buttons wrap when they can't fit on one row. Tested at 320 / 390 / 430 dp with zero RenderFlex overflow.

---

## Security invariants — what did NOT change

- Detail card is emitted **only** when `intent in (LOGIN_SEARCH, LOGIN_REVEAL, LOGIN_COPY)` AND the resolved match count is exactly 1 AND `data.view == 'detail'`. Any other combination goes through `_strip_forbidden` blacklist.
- The plaintext exception is enforced by a **positive allowlist**, not a blacklist bypass:
  - Backend: `_sanitize_login_detail_payload` in [vault_chat_card_data.py](vault_ai_backend/vault_chat_card_data.py) admits only `schema, available, view, query, login, count, pending_action` at payload level and only `id, title, service, username, password, domain, website, notes, updated_at, generated` at login level.
  - Frontend: `_sanitizeLoginDetail` in [services/vault_chat_router.dart](vault_ai_frontend/lib/services/vault_chat_router.dart) mirrors it exactly.
- No plaintext in logs — `_vlog` is guarded by `kReleaseMode` (frontend). Backend `logger.info` on set_active_entity only prints `label_len`, never the label content. `[CHAT-DEBUG]` prints only vault-id prefix + intent + entity type.
- No plaintext in URLs — the card is delivered inside the encrypted `/chat` SSE stream, not a URL query.
- No plaintext in generic assistant text — the router only emits the structured card; there is no LLM-generated message string for detail responses.
- No plaintext sent to OpenAI — detail decryption happens locally in `build_login_detail_data`; no external call touches the credential fields.
- No plaintext persisted to chat history — the store is the in-memory `TTLDict` in [vault_chat_memory.py](vault_ai_backend/vault_chat_memory.py) and the ephemeral `_store` in [vault_chat_active_entity.py](vault_ai_backend/vault_chat_active_entity.py); neither table nor DB row records the card body.
- Vault-key lifecycle unchanged. Cleared on:
  - Logout — `POST /auth/logout` → `get_cache().clear_session(token_id)` in [routes/auth_routes.py:571](vault_ai_backend/routes/auth_routes.py#L571).
  - Session expiry — `vault_key_cache` idle TTL 30 min, hard TTL 8 h.
  - Vault switch / delete / lock — client-side `_VaultCrypto.clearCache(vaultId)` at [main.dart:836,976,1176,1331,1879,1910,1972](vault_ai_frontend/lib/main.dart).
- Active-entity module rejects any forbidden-key ref (password, pin, seed, etc.) — see `_FORBIDDEN_REF_KEYS` in [vault_chat_active_entity.py:179](vault_ai_backend/vault_chat_active_entity.py#L179).
- Cross-session and cross-vault reads: `get_active_entity` returns None when `session_id` mismatches → pronoun follow-ups can't reveal a login from a different session's entity.

---

## Files changed

### Backend

| File | Change |
|---|---|
| [vault_chat_card_data.py](vault_ai_backend/vault_chat_card_data.py) | Added `LOGIN_VIEW_*` constants; added `_derive_website`, `_project_login_row_detail`, `_project_login_chooser_row`, `_sanitize_login_detail_payload`, `_ALLOWED_DETAIL_LOGIN_KEYS`, `_ALLOWED_DETAIL_PAYLOAD_KEYS`, `build_login_detail_data`; wired `LOGIN_SEARCH`/`LOGIN_REVEAL`/`LOGIN_COPY` intents to the new builder; routed detail data through the allowlist sanitizer instead of `_strip_forbidden` |
| [vault_chat_router.py](vault_ai_backend/vault_chat_router.py) | `LOGIN_SEARCH` branch: `view=search` → `view=detail`, `maskedByDefault=False`. `LOGIN_REVEAL` branch: no more confirmation card — emits detail card. `LOGIN_COPY` branch: same. Added reveal/copy phrasings to `_LOGIN_REVEAL_PATTERNS` (`"reveal my <service> password"`, `"show the password for X"`). Added service-name extractors to `_LOGIN_SERVICE_EXTRACT_REGEXES` for reveal / copy / "what's the password for X" |
| [main.py](vault_ai_backend/main.py) | Fast-path + slow-path active-entity writes extended: apply to `LOGIN_SEARCH`, `LOGIN_REVEAL`, `LOGIN_COPY`; prefer resolved login-id as entity_ref when view=detail; add candidate list when view=chooser; add `ACTION_EDIT`, `ACTION_SAVE` to allowed_actions. Pronoun follow-up dispatcher now handles `show/open/view/edit/delete/copy/save` verbs for a login active entity and annotates the resulting envelope with `pending_action` |

### Frontend

| File | Change |
|---|---|
| [lib/ui/vault_chat_cards.dart](vault_ai_frontend/lib/ui/vault_chat_cards.dart) | Added login view + action constants; extended `VaultChatCardView` with `onLoginEdit`/`onLoginDelete`/`onLoginOpenWebsite`/`onLoginChooseCandidate`; rewrote `_LoginCard` to dispatch on `data.view` (detail/chooser/not_found/list); added `_LoginDetailCard` (stateful — auto-fires `pending_action` on mount), `_LoginDetailFieldRow` (label + selectable value + compact copy icon), `_LoginChooserCard` (masked-only options), `_snack` helper. Removed misleading "Reveal requires unlock" pill and `•••••••••` footer pills from the list view |
| [lib/services/vault_chat_router.dart](vault_ai_frontend/lib/services/vault_chat_router.dart) | Added `_kLoginDetailPayloadKeys`, `_kLoginDetailLoginKeys`, `_sanitizeLoginDetail` (positive allowlist); `VaultChatCard.fromJson` routes detail-view login data through the allowlist instead of `_stripForbiddenKeys` |
| [lib/ui/chat/chat_bubble.dart](vault_ai_frontend/lib/ui/chat/chat_bubble.dart) | `_buildVaultChatCardView` wires `onLoginEdit`/`onLoginDelete` to the existing `onSecureItem*` handlers (reusing `SecureItemEditDialog` + delete confirmation), adds `onLoginOpenWebsite` and `onLoginChooseCandidate` via `onCardAction` |

### Tests added

| File | Tests | Status |
|---|---|---|
| [vault_ai_backend/test_vault_chat_login_detail_2026_07_11.py](vault_ai_backend/test_vault_chat_login_detail_2026_07_11.py) | 19 | ✅ 19/19 pass |
| [vault_ai_frontend/test/vault_chat_login_detail_card_2026_07_11_test.dart](vault_ai_frontend/test/vault_chat_login_detail_card_2026_07_11_test.dart) | 18 | ✅ 18/18 pass |

Test coverage matrix (14 items from spec):

| # | Requirement | Covered by |
|---|---|---|
| 1 | Explicit specific-login show renders username + password | `(1) shows real username + password + website + service` |
| 2 | No masking dots, no "Reveal requires unlock" text | `(2) card contains no masked dots and no "Reveal requires unlock" copy` + `test_login_list_never_carries_plaintext_password` |
| 3 | Generic list view does not expose every password | `(3) generic list view does NOT expose every password` + `ListPathStillMasks::test_generic_list_returns_masked_usernames_only` + `test_project_login_row_list_still_masks` |
| 4 | Multiple matches show chooser first | `(4) multiple matches renders chooser first` + `BuilderRoutesByMatchCount::test_multi_match_returns_chooser_without_plaintext` |
| 5 | Selected match reveals only that login | `(5) chooser select fires onLoginChooseCandidate` + `test_single_match_returns_detail` |
| 6 | Edit mode loads current fields | Existing `SecureItemEditDialog` — wired via `onLoginEdit → onSecureItemEdit`; existing coverage `secure_item_edit_prefill_test.dart` |
| 7 | Save updates encrypted storage | Existing `updateVaultSecureItem` path; existing coverage `secure_item_detail_test.dart` |
| 8 | Delete confirmation + deletion work | Existing accidental-action flow via `_startSecureItemDeleteConfirmation`; existing coverage `secure_item_delete_confirmation_test.dart` |
| 9 | Copy username / password use correct active login | `(7) copy-username`, `(8) copy-password` |
| 10 | Follow-up "edit it" / "delete it" use active-entity | `(12) pending_action=edit`, `(13) pending_action=delete`, `(14) pending_action=copy_password` + backend `test_dispatch_synthesises_find_my_query_login` |
| 11 | Plaintext never in logs / analytics / URLs / normal text | `SanitizerAllowsOnlyKnownKeys::*` (backend), `test_router_shell_never_carries_plaintext_password`, `test_login_list_never_carries_plaintext_password` |
| 12 | Credentials clear on logout/lock/switch/expiry | Vault-key lifecycle unchanged; verified pre-existing coverage in `delete_vault_session_cleanup_2026_07_09_test.dart` + `test_auth_routes.py` logout path |
| 13 | Card works at 320 / 390 / 430 | `(*) renders without overflow @ iPhone SE / 12 / 14 Pro Max` (3 tests) |
| 14 | No raw JSON rendered | `(15) no raw JSON blob rendered anywhere` |

### Tests updated (invariant reflection)

| File | Change |
|---|---|
| [test_vault_chat_router_2026_07_08.py](vault_ai_backend/test_vault_chat_router_2026_07_08.py) | `test_login_reveal_requires_confirmation` → `test_login_reveal_dispatches_detail_card`; `test_login_copy_requires_confirmation` → `test_login_copy_dispatches_detail_card`; `test_confirmation_required_cards_never_carry_the_secret` → `test_router_card_shell_never_carries_the_secret` (allows detail card, denies plaintext in shell) |
| [test_active_entity_conversation_context_2026_07_11.py](vault_ai_backend/test_active_entity_conversation_context_2026_07_11.py) | `RevealAndCopyStillRouteToConfirmation` → `RevealAndCopyRouteToDetailCard`. `test_dispatch_synthesises_find_my_query_login` — asserts `view=detail`, `maskedByDefault=False`. Source-scan tests `test_login_search_fast_path_writes_login_active_entity` + `test_login_search_slow_path_writes_login_active_entity` updated for the new `_fp_login_intents` / `_vcr_login_intents` tuples + ACTION_EDIT |
| [test_vault_chat_pipeline_integration_2026_07_08.py](vault_ai_backend/test_vault_chat_pipeline_integration_2026_07_08.py) | `test_reveal_returns_confirmation_not_password` → `test_reveal_router_shell_carries_no_password`; `test_copy_returns_confirmation_not_password` → `test_copy_router_shell_carries_no_password`; `test_find_gmail_login_returns_login_search` → `test_find_gmail_login_returns_login_detail` |
| [test/vault_chat_router_2026_07_08_test.dart](vault_ai_frontend/test/vault_chat_router_2026_07_08_test.dart) | `login card renders with masked pill` rewritten as `login list card renders masked-username rows and no misleading "Reveal requires unlock" pill` |

---

## Test results

**Backend:**
```
python -m pytest    →   6283 passed, 65 skipped in 91.6s
new tests:              19 / 19  pass
existing tests:         updated 6, all pass
```

**Frontend:**
```
flutter test        →   3321 passed
new tests:              18 / 18  pass
existing tests:         updated 1, all pass
```

**Release build:**
```
flutter build web --release   →   success, 50.8s
```

---

## Rebuild + redeploy commands

You have to run these manually — nothing was committed, pushed, or deployed.

**Frontend (Flutter web):**
```powershell
cd C:\Users\user\Desktop\Vaultai\vault_ai_frontend
flutter clean
flutter pub get
flutter build web --release
# artefacts at build\web
```

**Backend (FastAPI / uvicorn):**
```powershell
cd C:\Users\user\Desktop\Vaultai\vault_ai_backend
# No new dependencies added — no `pip install` needed.
# If running under uvicorn:
uvicorn main:app --reload  # dev
# or however you launch prod (systemd unit, container, etc.).
```

The backend has no new external deps. `vault_chat_active_entity.py` and `vault_chat_card_data.py` are pure additions to existing modules. The only signature change in `main.py` was to a private helper (`_buildPortfolioSummary` in the frontend — see the mobile-audit PR); no public request/response schemas changed. The card wire format gained a `login` object under `card.data` and a `pending_action` string, both under the existing `vault_chat_router_v1` schema.

**Order that matters when deploying:**

1. Backend first — the frontend gracefully falls back to the older list/search rendering if the backend doesn't emit `view=detail`.
2. Frontend after — the new `_LoginCard` dispatches on `data.view` and renders the list view identically to before.
3. No DB migrations required — no schema change.
4. No cache/token invalidation required — existing `vault_key_cache` continues to work.

Both apps are backwards- and forwards-compatible during a rolling deploy.
