# Manual Browser Checks — after 2026-07-11 fixes

Run this checklist against a release web build (`flutter build web --release`
served from `vault_ai_frontend/build/web/`) on Chromium and Safari before
signing off on the ship. None of the widget tests or backend tests replace
these — they are source-shape guards, not user flows.

**IMPORTANT — the media Close/reload root cause is NOT proven.**
The `MediaError → shell reload` theory is an inference from code shape.
The fix is defense-in-depth against every plausible trigger the search
surfaced. These browser checks are how we actually verify the reload is
gone.

---

## Setup

1. Deploy the release build to your target environment (staging).
2. Open Chrome / Edge / Safari.
3. DevTools → Network tab open, **Preserve log** checked. This is how
   you confirm no page reload happened (a reload wipes the log).
4. Sign in with two test accounts:
   - **`free@vaultai.test`** — no billing / no purchased storage.
   - **`upgraded@vaultai.test`** — at least one storage block purchased
     (Stripe active or in-grace).

---

## 1. Crypto Vault chat entitlement — free user

- [ ] Sign in as `free@vaultai.test`. Complete PIN.
- [ ] Open VaultAI chat. Type: `can i access the crypto vault`
- [ ] **Expected**: Crypto Vault card appears with an **Upgrade required**
      CTA. No **Open Crypto Vault** button.
- [ ] Send follow-up: `open it`
- [ ] **Expected**: Same Crypto Vault card with **Upgrade required** CTA.
      NOT nothing. NOT an enabled Open.
- [ ] Repeat with each variant: `take me there`, `use it`, `go there`,
      `launch it`, `open the vault`. Each must produce the locked card.
- [ ] Tap the sidebar **Crypto Vault** link.
- [ ] **Expected**: `CryptoVaultLockedCard` renders. NOT the wallet
      engine page.
- [ ] In DevTools console: `fetch('/crypto/wallet/accounts', {credentials:
      'include'}).then(r => r.status)` (with a valid session).
- [ ] **Expected**: `403`. Response body carries
      `{"detail":{"code":"crypto_vault_upgrade_required", ...}}` and
      never leaks `purchased_bytes`, `block_count`, or Stripe internals.
- [ ] Repeat the direct-API check for `/crypto/wallet/ETH/receive`,
      `/crypto/wallet/ETH/balance`, `/crypto/wallet/ETH/send/draft`,
      `/crypto/wallet/xmr/scanner/status`. All must return `403`.

## 2. Crypto Vault chat entitlement — upgraded user

- [ ] Sign in as `upgraded@vaultai.test`.
- [ ] In VaultAI chat: `can i access the crypto vault`
- [ ] **Expected**: Top-line message says **yes** and briefly mentions
      Open, selecting an asset, Receive, Send. Crypto Vault card renders
      with the **Open Crypto Vault** button enabled.
- [ ] Follow-up: `open it` — same card, still enabled Open.
- [ ] Tap **Open Crypto Vault**. Wallet engine page loads.
- [ ] Select ETH → **Receive** → address + QR render (calling
      `/crypto/wallet/ETH/receive` — must return `200`).
- [ ] Back → **Send** panel opens — enter test address + `0` amount —
      draft returns `200`.

## 3. Media viewer Close — image

- [ ] Sign in, unlock a vault that contains an image file.
- [ ] Open chat → ask VaultAI to find the image → open the image card.
- [ ] Tap **Close**.
- [ ] **Check DevTools Network tab** — **Preserve log** must show NO new
      request for the root document (i.e. no reload). The chat log
      remains visible.
- [ ] **Expected**: You return to the chat with your chat history
      intact. You are NOT sent to `/pin`.
- [ ] Reopen the same image — should work.
- [ ] Tap browser **Back** while the image is open — dialog dismisses,
      chat is preserved, no reload.

## 4. Media viewer Close — video

- [ ] With the same vault, find a saved video (or upload a short MP4).
- [ ] Open the video card → video element loads and can be played.
- [ ] Tap **Close** during playback.
- [ ] **Check DevTools Network tab** — no root-document reload.
- [ ] **Expected**: You remain on the chat, PIN state preserved.
- [ ] Repeat: reopen the same video, close, reopen. Playback keeps
      working — the blob URL lifecycle is not leaking.
- [ ] Force a decode error: upload a garbage-body `.mp4`. Open it.
      **Expected**: the error banner renders inside the dialog with
      "This file could not be decoded by the browser." (or similar).
      Close still works. No reload.

## 5. Inheritance page mobile

- [ ] Open DevTools → Device Toolbar → set width to **320 px**.
- [ ] Navigate to Inheritance.
- [ ] **Expected**: "Vaults I'll inherit" heading renders as a normal
      line — NOT one character per line. Refresh + Enter code buttons
      wrap below the heading, both tappable.
- [ ] Repeat at **390 px** and **430 px**. No RenderFlex overflow in
      the DevTools console.
- [ ] Resize to a desktop width (>= 1024). Layout returns to the
      side-by-side heading + buttons row.

## 6. Regression — did anything else break?

- [ ] Type `find my Gmail login` → login search still works.
- [ ] Type `show my recent activity` → activity card renders.
- [ ] SSE streaming: type a long chat prompt. Confirm the streamed
      response appears token-by-token. (Do not regress live streaming.)

---

## If any check fails

Do NOT deploy. Capture:

1. DevTools console log (whole session).
2. DevTools Network log (whole session — use "Export HAR" while
   "Preserve log" is checked).
3. Screen recording of the failing step.

Share the HAR + recording so the reload/redirect trigger can be
identified before we ship.

## What these checks establish

- Chat card + backend API entitlement gates behave identically at the
  UI and the wire.
- The direct-API bypass we closed in this iteration actually returns
  `403` at every gated route.
- The media Close reload is gone in practice (not just in the widget
  test), which is the only way to actually retire the "reload"
  bug — since we never had a proven root cause, only a covered
  candidate trigger.
