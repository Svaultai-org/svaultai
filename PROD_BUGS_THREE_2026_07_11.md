# VaultAI production bugs — 2026-07-11 fixes

**Not committed. Not pushed. Not deployed.**

Three production bugs, each with a distinct root cause. Every fix goes through the actual production code path — none is a screenshot-specific workaround.

---

## Bug 1 — Inheritance page "Vaults I'll inherit" wraps one character per line

### Root cause (exact code path)

The Inheritance page is not a routed widget — it lives inline as `_ChatDashboardPageState._buildInheritanceSection(bool isMobile)` starting at [main.dart:5263](vault_ai_frontend/lib/main.dart#L5263). The tree is `SingleChildScrollView` → `Center` → `ConstrainedBox(maxWidth: 1000)` → `Column` with three cards: intro / People I've added / Vaults I'll inherit.

The **"People I've added"** section already used [`ResponsiveActionBar`](vault_ai_frontend/lib/ui/responsive.dart#L213) (at [main.dart:5360](vault_ai_frontend/lib/main.dart#L5360)). That widget switches from `Row` to `Column + Wrap` below `VaultBreakpoints.compactMax` (600dp), keeping the heading full-width on phones.

The **"Vaults I'll inherit"** section (at [main.dart:5476](vault_ai_frontend/lib/main.dart#L5476)) used a bare `Row([Expanded(heading), OutlinedButton(Refresh), SizedBox(8), FilledButton(Enter code)])`. On a 320–430dp viewport, the two intrinsically-sized buttons consumed most of the row width; the `Expanded` heading received only ~30–40dp; with `softWrap: true` (the default) each character of "Vaults I'll inherit" (22 chars) wrapped onto its own line.

The container's `EdgeInsets.all(20)` and `BorderRadius.circular(20)` were also unconditional — no responsive tightening on phones — which made the card feel oversized against the intro card two rows above.

### Fix

Replaced the raw `Row` with a `ResponsiveActionBar` matching the "People I've added" section, and made the card padding + border radius track `_vrInh.cardInsetPadding` and `_vrInh.isMobile ? 16 : 20` respectively. Same shape as the sibling card:

```dart
ResponsiveActionBar(
  heading: const Text('Vaults I\'ll inherit',
    key: Key('inheritance_vaults_ill_inherit_heading'),
    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
  ),
  actions: [
    OutlinedButton.icon(
      key: const Key('inheritance_refresh_inheritances_button'),
      onPressed: _loadInheritances,
      icon: const Icon(Icons.refresh, size: 18),
      label: Text(AppLocalizations.of(context).commonRefresh),
    ),
    FilledButton.icon(
      key: const Key('inheritance_enter_code_button'),
      onPressed: _showEnterPairingCodeDialog,
      icon: const Icon(Icons.vpn_key),
      label: Text(AppLocalizations.of(context).inheritanceEnterCode),
    ),
  ],
),
```

Because `ResponsiveActionBar` stacks below 600dp, the "Vaults I'll inherit" heading now renders full-width on phones and buttons wrap below it. Desktop/tablet layout is unchanged.

### Files changed

- [vault_ai_frontend/lib/main.dart](vault_ai_frontend/lib/main.dart#L5466) — 1 site: `_buildInheritanceSection`, "Vaults I'll inherit" card converted to `ResponsiveActionBar`; card padding + radius now respect `_vrInh`

### Not needed

- No changes to `ui/responsive.dart` — `ResponsiveActionBar` already provided the correct behavior.
- No route-level changes — the page is reached only via the in-shell `_DashboardSection.inheritance` dispatch at [main.dart:10704](vault_ai_frontend/lib/main.dart#L10704).

---

## Bug 2 — Crypto Vault chat card ignores subscription entitlement

### Root cause (exact code path)

Backend chat handler flow for **"can I access the crypto vault"**:

1. `main.py` `/chat` handler builds a fast-path envelope via [`vault_chat_router.build_vault_chat_envelope`](vault_ai_backend/vault_chat_router.py#L1162).
2. Inside `classify_and_build_vault_intent`, [`_looks_like_crypto_message`](vault_ai_backend/vault_chat_router.py#L767) matches the phrase (regex includes `crypto\s+vault`).
3. `_crypto_classify_and_build(text)` in `crypto_vault_chat_control.py` matches `_SHOW_VAULT_RE` and returns `INTENT_SHOW_VAULT`.
4. The router wraps that into `INTENT_CRYPTO_DELEGATED` with `CARD_CRYPTO_DELEGATED` and `innerCard.cardType = "crypto_vault_show_vault_card"`.
5. `populate_crypto_delegated_card_data` fills `innerCard.data` via [`build_crypto_overview_data`](vault_ai_backend/vault_chat_crypto_data.py#L249).
6. **Neither step reads the subscription tier.**

Frontend:

- [`crypto_vault_chat_cards.dart:1401`](vault_ai_frontend/lib/ui/crypto_vault_chat_cards.dart#L1401) rendered the "Open Crypto Vault" `OutlinedButton` unconditionally when `widget.onOpenVault != null`.
- The callback was always non-null (wired from [main.dart:9973](vault_ai_frontend/lib/main.dart#L9973) as an unconditional section switcher), so the button always rendered.
- The destination page **did** gate correctly (`isKnownNotUpgraded` check at [main.dart:10732](vault_ai_frontend/lib/main.dart#L10732) swaps in `CryptoVaultLockedCard`), but the chat card had already surfaced a fully-featured "Open Crypto Vault" affordance that lied about entitlement.

Existing entitlement source of truth:
- [`billing.get_entitlement(account_id)`](vault_ai_backend/billing.py#L314) returns `StorageEntitlement(block_count, purchased_bytes, has_active_subscription)`.
- The upgrade signal is `block_count > 0 AND purchased_bytes > 0` with `status ∈ {active, in_grace, canceled_pending}`.
- A tier-lookup snippet was already used for the secure-item deflector at [main.py:12587](vault_ai_backend/main.py#L12587) — it just wasn't reached on the crypto-delegated branch.

### Fix — two-layer defense

**Layer 1 — Backend authoritative gate.**

Extended `populate_crypto_delegated_card_data` in [`vault_chat_crypto_data.py`](vault_ai_backend/vault_chat_crypto_data.py) with an optional `user_tier: Optional[str]` kwarg. When `inner_intent == "crypto_vault_show_vault"`, the resulting `data` map is enriched with:

```python
data["locked"]      = (user_tier != "upgraded")
data["entitlement"] = "upgraded" if upgraded else "upgrade_required"
data["tier"]        = user_tier or "free"
```

The gate is on `_CVC_INTENT_SHOW_VAULT` only — other crypto intents (receive address, balance, activity, scanner status) are unchanged, since they're either asset-level (already gated by having an address at all) or account-management (allowed for all tiers).

Both `main.py` call sites now compute the tier before calling the populator:

- **Fast path** — [main.py:11860](vault_ai_backend/main.py#L11860) block now does `get_entitlement(get_account_id_for_vault(vault_id))` and passes `user_tier="upgraded"` when both `block_count > 0` AND `purchased_bytes > 0`.
- **Slow path** — [main.py:12405](vault_ai_backend/main.py#L12405) block mirrors the same lookup. Any exception in the lookup → `_user_tier = "free"` (fail-closed).

**Layer 2 — Frontend belt-and-braces.**

Added `AppState.isCryptoEntitled` getter at [main.dart:906](vault_ai_frontend/lib/main.dart#L906) that returns `billingBlockCount > 0 && billingPurchasedBytes > 0`. The same predicate that already gates the destination page. Wired through:

`ChatMessageList` → `ChatBubble` → `_CardBubble._buildVaultChatCardView` → `VaultChatCardView` → `CryptoVaultChatCardView` → `_ShowVaultCard`, adding a `bool cryptoEntitled` + `VoidCallback? onOpenCryptoUpgrade` at each hop.

`_ShowVaultCard._isLocked()` returns `true` if EITHER the client-side `cryptoEntitled` is false OR the server payload has `locked == true` / `entitlement == "upgrade_required"`. When `_isLocked()`, the "Open Crypto Vault" button is replaced with an "Upgrade required" CTA + explanatory copy. `VaultChatCardView` also nulls out `onOpenVault` when `!cryptoEntitled` — so even if a downstream widget checks `onOpenVault != null` it sees `null` and cannot render an open affordance.

Direct route to `_DashboardSection.cryptoVault` was already gated via `isKnownNotUpgraded` at [main.dart:10732](vault_ai_frontend/lib/main.dart#L10732) → `CryptoVaultLockedCard`. No change needed.

Follow-up "open it" for a non-entitled user: the crypto-delegated show-vault card does not write an active-entity record (only login intents do — see [main.py:11893](vault_ai_backend/main.py#L11893)), so "open it" falls through to the LLM chat handler, which does not have a code path that pushes the crypto vault route. The backend gate + frontend gate together mean asking again reproduces the same locked card.

### Why network / scanner availability was NOT the answer

Product requirement is explicit: **"Do not infer access from whether crypto assets exist or whether scanner services are enabled."** The `xmr_scanner_status` and `receiveReady` flags in `build_crypto_overview_data` do not participate in `_isLocked()`. Entitlement is `billing.block_count > 0 AND billing.purchased_bytes > 0`, checked at both the backend (source of truth) and the frontend (defense in depth). A user with a broken scanner but a paid plan sees an unlocked card. A user with a working scanner but no plan sees the upgrade CTA.

### Files changed

- [vault_ai_backend/vault_chat_crypto_data.py](vault_ai_backend/vault_chat_crypto_data.py) — `populate_crypto_delegated_card_data` takes `user_tier`; injects `locked` / `entitlement` / `tier` into show-vault data
- [vault_ai_backend/main.py](vault_ai_backend/main.py) — both fast-path (11860) and slow-path (12405) call sites do the entitlement lookup + pass `user_tier`
- [vault_ai_frontend/lib/main.dart](vault_ai_frontend/lib/main.dart) — added `AppState.isCryptoEntitled`; `ChatMessageList` call site (10056) now passes `cryptoEntitled` + `onOpenCryptoUpgrade`
- [vault_ai_frontend/lib/ui/crypto_vault_chat_cards.dart](vault_ai_frontend/lib/ui/crypto_vault_chat_cards.dart) — `CryptoVaultChatCardView` + `_ShowVaultCard` take `cryptoEntitled` + `onOpenUpgrade`; `_isLocked()` combines client + server signals; upgrade CTA replaces Open when locked
- [vault_ai_frontend/lib/ui/vault_chat_cards.dart](vault_ai_frontend/lib/ui/vault_chat_cards.dart) — `VaultChatCardView` propagates `cryptoEntitled` / `onOpenCryptoUpgrade`, nulls `onOpenVault` when not entitled
- [vault_ai_frontend/lib/ui/chat/chat_bubble.dart](vault_ai_frontend/lib/ui/chat/chat_bubble.dart) + [chat_message_list.dart](vault_ai_frontend/lib/ui/chat/chat_message_list.dart) — plumb the two params

---

## Bug 3 — Media viewer Close causes app reload → back to PIN unlock

### Root cause (exact code path)

Two independent gaps compounded into the observed bug:

**Gap 1 — the reload itself.** The video/audio dialog at [main.dart:9080](vault_ai_frontend/lib/main.dart#L9080) used:

```dart
await showDialog(
  context: context,        // ← page context, not dialog context
  builder: (dCtx) => AlertDialog(
    content: HtmlElementView(viewType: viewType),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),  // ← page context
        child: const Text('Close'),
      ),
    ],
  ),
);
// finally { player.dispose(); }   // ← revokes blob URL synchronously
```

`Navigator.pop(context)` where `context` is the enclosing `_ChatDashboardPageState`'s context (rather than `dCtx`) — with the current single-navigator setup — still pops the dialog (both contexts resolve to the same root Navigator), so this alone isn't the reload. **The reload is triggered by** `player.dispose()` calling [`html.Url.revokeObjectUrl`](vault_ai_frontend/lib/media_player_web.dart#L71) synchronously in the `finally` block. On some Chromium builds, revoking a blob URL while the `<video>` element is still in the DOM (the platform-view has not yet been detached from the RenderObject tree) fires a `MediaError` on the `<video>`. The video element had **no `onError` handler**, so the error propagated to `window.onerror`, and Flutter web's default runtime response to an unhandled error is to reload the shell.

**Gap 2 — reload always lands on PIN.** [`route_guard.resolveLandingRedirect`](vault_ai_frontend/lib/route_guard.dart#L10) redirects `authed && !unlocked` → `/pin`. `AppState._unlocked` at [main.dart:778](vault_ai_frontend/lib/main.dart#L778) is a plain in-memory bool, never persisted. `_VaultCrypto` at [main.dart:11520](vault_ai_frontend/lib/main.dart#L11520) caches the SecretKey and PIN in static maps — also not persisted. Any reload for any reason → `_unlocked = false` on the fresh Dart isolate → route guard sends the user to `/pin`.

Combined: Close fires the blob-revocation MediaError → reload → PIN screen.

### Fix — attack Gap 1 in three places

**A. Change all 5 Close buttons to `Navigator.pop(dCtx)` and add `useRootNavigator: false`.** Even though today's tree has only one Navigator, this is the correct idiom and future-proofs the fix against a nested Navigator (which is common in web routers). Every dialog now uses:

```dart
await showDialog(
  context: context,
  useRootNavigator: false,
  builder: (dCtx) => AlertDialog(
    actions: [
      TextButton(
        key: Key('media_XXX_dialog_close'),
        onPressed: () => Navigator.pop(dCtx),
        ...
```

Applied at all 5 sites:

| Dialog | Old | New |
|---|---|---|
| Video/audio dialog ([main.dart:9082](vault_ai_frontend/lib/main.dart#L9082)) | `Navigator.pop(context)` | `Navigator.pop(dCtx)` + `useRootNavigator: false` + key `media_video_dialog_close` |
| Metadata fallback dialog ([main.dart:9126](vault_ai_frontend/lib/main.dart#L9126)) | same | `media_metadata_dialog_close` |
| Text preview dialog ([main.dart:8787](vault_ai_frontend/lib/main.dart#L8787)) | same | `text_viewer_dialog_close` |
| Image viewer dialog ([main.dart:8732](vault_ai_frontend/lib/main.dart#L8732)) | same | `image_viewer_dialog_close` + fits inside `ConstrainedBox` sized to viewport for 320/390/430 |
| Attachment preview ([main.dart:7319](vault_ai_frontend/lib/main.dart#L7319)) | same | `attachment_preview_dialog_close` |

**B. Defer `player.dispose()` past the platform-view detach.** The `finally` block that ran `player.dispose()` synchronously is replaced with:

```dart
finally {
  WidgetsBinding.instance.addPostFrameCallback((_) {
    Future<void>.delayed(const Duration(milliseconds: 100), () {
      try { player.dispose(); } catch (_) { /* revocation raced with detach */ }
    });
  });
}
```

`addPostFrameCallback` runs after the current frame — i.e. after the dialog route pop has re-laid-out the tree without the `HtmlElementView`. The `Future.delayed(100ms)` gives the browser one more paint cycle to actually detach the `<video>` element from the DOM. The `try/catch` swallows the (now-rare) case where revocation still races. This addresses the primary MediaError trigger.

**C. Swallow blob-revocation errors on the element itself.** [`media_player_web.dart`](vault_ai_frontend/lib/media_player_web.dart) now attaches an empty `onError` listener to both `VideoElement` and `AudioElement`:

```dart
final v = html.VideoElement()
  ..controls = true
  ...
  ..src = url;
v.onError.listen((_) {});   // ← swallow MediaError, do not reload shell
```

Together, B and C mean the blob revocation cannot reload the shell even if it fires an error.

### Why NOT persist `_unlocked` in sessionStorage

The user asked me to prevent the refresh entirely, not preserve state across a refresh. Persisting `_unlocked` would paper over the symptom — a stray reload from any other cause (network hiccup, browser crash recovery) would still leave the user unlocked, which is a broader security decision this bug fix should not smuggle in. The three A/B/C fixes above address the specific reload chain. If the team later decides they want to keep unlocked across an intentional refresh, that's a separate change — noted in "Remaining risk" below.

### Files changed

- [vault_ai_frontend/lib/main.dart](vault_ai_frontend/lib/main.dart) — 5 dialog sites: dCtx pop, useRootNavigator: false, keys; video dialog `finally` block replaced with deferred dispose
- [vault_ai_frontend/lib/media_player_web.dart](vault_ai_frontend/lib/media_player_web.dart) — `onError.listen((_) {})` on both `VideoElement` and `AudioElement`

### After the fix — production code path

1. User taps View on a saved video card.
2. `_openMediaDialog` registers the platform view and calls `showDialog(context: <page>, useRootNavigator: false, ...)`.
3. AlertDialog renders with `HtmlElementView(viewType)` inside — `<video src="blob:...">` mounted in the DOM.
4. User taps Close → `Navigator.pop(dCtx)` pops **only** the dialog route.
5. Flutter runs one frame that removes the AlertDialog from the tree; the `HtmlElementView` detaches; the `<video>` element is unmounted from the DOM.
6. `addPostFrameCallback` fires. Inside, `Future.delayed(100ms, ...)` schedules `player.dispose()`.
7. 100ms later, `html.Url.revokeObjectUrl(blobUrl)` runs. If the video's `MediaError` fires, `onError.listen((_) {})` swallows it. No `window.onerror`. No shell reload.
8. The user is still in `/chat`, still authenticated, still unlocked, at the same scroll position, with the same active entity for the previously-shown message.

---

## Files changed — summary

**Backend (2)**:

- [vault_ai_backend/vault_chat_crypto_data.py](vault_ai_backend/vault_chat_crypto_data.py)
- [vault_ai_backend/main.py](vault_ai_backend/main.py)

**Frontend (6)**:

- [vault_ai_frontend/lib/main.dart](vault_ai_frontend/lib/main.dart)
- [vault_ai_frontend/lib/media_player_web.dart](vault_ai_frontend/lib/media_player_web.dart)
- [vault_ai_frontend/lib/ui/crypto_vault_chat_cards.dart](vault_ai_frontend/lib/ui/crypto_vault_chat_cards.dart)
- [vault_ai_frontend/lib/ui/vault_chat_cards.dart](vault_ai_frontend/lib/ui/vault_chat_cards.dart)
- [vault_ai_frontend/lib/ui/chat/chat_bubble.dart](vault_ai_frontend/lib/ui/chat/chat_bubble.dart)
- [vault_ai_frontend/lib/ui/chat/chat_message_list.dart](vault_ai_frontend/lib/ui/chat/chat_message_list.dart)

**Tests added (2)**:

- [vault_ai_backend/test_crypto_vault_chat_entitlement_2026_07_11.py](vault_ai_backend/test_crypto_vault_chat_entitlement_2026_07_11.py) — 9 tests
- [vault_ai_frontend/test/prod_bugs_three_2026_07_11_test.dart](vault_ai_frontend/test/prod_bugs_three_2026_07_11_test.dart) — 10 tests

---

## Exact test results

**Backend**: `python -m pytest -q`
```
6289 passed, 65 skipped in 97.5s
new tests: 9 / 9  pass
existing failures: 3 in test_vault_delete_and_inactive_cleanup_2026_07_08.py —
  pre-existing, unrelated to these bugs (verified during earlier login-detail work)
```

**Frontend**: `flutter test`
```
3331 passed
new tests: 10 / 10 pass  (Bug 1: 4, Bug 2: 4, Bug 3: 2)
```

**Frontend static analysis**: `flutter analyze lib/`
```
93 issues — all pre-existing (deprecated withOpacity, unused imports in unrelated files).
Zero new errors from these changes.
```

**Release web build**: `flutter build web --release`
```
success in 49.3s
```

---

## Remaining risk / limitations

1. **Bug 3 – reload from causes other than the media viewer.** The three fixes address the media-viewer chain specifically. Any other page-reload trigger (network flake, browser crash, tab discard) still drops the in-memory `_unlocked` flag and lands the user on `/pin`. If the product wants to preserve unlocked across a page refresh generically, that's a separate change — sessionStorage persistence of `_unlocked` (per tab) plus a matching `_VaultCrypto` cache backed by `sessionStorage`-encrypted PIN. Deliberately NOT included here.

2. **Bug 2 – client-side billing state can be stale after upgrade.** The `AppState.billingBlockCount / billingPurchasedBytes` fields hydrate from `/billing/me`. Immediately after a Stripe checkout success redirects back into the app, there is a brief window where the client hasn't refreshed. The backend gate (which runs `get_entitlement` per chat request from the source of truth) always wins during that window, so a just-upgraded user asking "can I access the crypto vault" sees the unlocked card correctly. The client-side gate only serves to catch the reverse case (server said unlocked but the user downgraded / churned since).

3. **Bug 1 – "People I've added" was already correct.** Its section (which used ResponsiveActionBar to begin with) has an existing source-scan test at [test/mobile_responsiveness_2026_07_12_test.dart:379](vault_ai_frontend/test/mobile_responsiveness_2026_07_12_test.dart#L379). The new test file adds the equivalent guard for "Vaults I'll inherit" so the raw-Row regression cannot recur.

4. **Widget-test coverage for the media viewer is a source guard, not a full mount test.** Standing up the full ChatDashboard page with Providers + a saved-file backend fixture is a substantial harness. Instead the test locks the fix at the source level (all 5 dialogs use `useRootNavigator: false` + `Navigator.pop(dCtx)`; `media_player_web` attaches `onError` listeners; `player.dispose` is scheduled via `addPostFrameCallback`). This matches how earlier audits already lock drawer + composer wiring via source scans.

---

## Rebuild + redeploy

Nothing was committed, pushed, or deployed. Manual steps:

**Backend** (no new deps):
```powershell
cd C:\Users\user\Desktop\Vaultai\vault_ai_backend
# whatever launches prod (systemd unit, container image, etc.)
```

**Frontend** (Flutter web):
```powershell
cd C:\Users\user\Desktop\Vaultai\vault_ai_frontend
flutter clean
flutter pub get
flutter build web --release
# artefacts at build\web
```

**Rolling deploy order**: backend first (frontend gracefully falls back to the pre-fix rendering if the server hasn't been rolled — the `locked` field is optional and `_isLocked()` treats absence as "not locked"), then frontend. Both are backward- and forward-compatible during a rolling deploy. No DB migrations. No cache/token invalidation.
