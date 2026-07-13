// 2026-07-14 (Round 12 — explicit SW retirement bootstrap): this
// file is the TEMPLATE. Build scripts substitute the literal
// `__VAULTAI_APP_RELEASE__` token below with the full 40-char
// commit SHA at release time, then copy the result to
// `build/web/vaultai-sw-bootstrap.js`. `web/index.html` loads
// this file synchronously BEFORE `flutter_bootstrap.js` so the
// service-worker migration runs regardless of Flutter's
// `--pwa-strategy=none` bootstrap (which otherwise never
// registers any SW at all).
//
// Contract:
//
//   * Registers `/flutter_service_worker.js?v=<full-sha>` at
//     scope `/`.
//   * Uses a *versioned* URL so every deploy is treated by the
//     browser as a distinct SW resource. The `?v=` query string
//     changes on every release, forcing the browser to fetch a
//     fresh SW and install the migration worker even if its byte
//     content happened to be identical to a prior deploy.
//   * Loop guard via `sessionStorage['vaultai_sw_migration_reloaded']`:
//     stores the release SHA we last reloaded for; a
//     `controllerchange` event whose target release matches the
//     stored SHA does NOT reload again.
//   * Reload trigger:
//       (a) FIRST-migration for a client controlled by the pre-
//           Round-11 offline-first Flutter SW: the migration SW's
//           `activate` handler calls `client.navigate(client.url)`
//           — that reload happens WITHOUT this bootstrap running,
//           because the OLD JS on the tab has no such listener.
//       (b) SUBSEQUENT updates: this bootstrap listens for
//           `controllerchange` and reloads once per session per
//           release. When the migration SW subsequently activates
//           on a NEW deploy, it calls `client.navigate` AND we
//           also see `controllerchange`; we deduplicate via the
//           sessionStorage guard + an in-scope `reloaded` flag.
//   * NEVER touches localStorage / IndexedDB / cookies / wallet
//     ciphertext. Only touches `sessionStorage` under one key.
//   * Safari (WebKit), Chrome (Blink), and Firefox (Gecko) all
//     support `navigator.serviceWorker` + `controllerchange`;
//     mobile and desktop UAs both dispatch it identically. Older
//     UAs without `navigator.serviceWorker` are handled with a
//     capability check and short-circuit — the bootstrap becomes
//     a no-op, and the app runs against no SW at all.

(function () {
  'use strict';

  var RELEASE = '__VAULTAI_APP_RELEASE__';
  // If the template substitution didn't happen (e.g. someone tried
  // to load this file raw), bail — never register with the literal
  // token in the URL.
  if (RELEASE.charAt(0) === '_' && RELEASE.charAt(1) === '_') {
    return;
  }

  var SW_URL = '/flutter_service_worker.js?v=' + RELEASE;
  var SW_SCOPE = '/';
  var RELOAD_KEY = 'vaultai_sw_migration_reloaded';

  if (!('serviceWorker' in navigator)) {
    return;
  }

  function readReloadedTarget() {
    try {
      return sessionStorage.getItem(RELOAD_KEY);
    } catch (_) {
      return null;
    }
  }

  function writeReloadedTarget(target) {
    try {
      sessionStorage.setItem(RELOAD_KEY, target);
    } catch (_) { /* private mode / disabled */ }
  }

  // Per-runtime dedupe. A `controllerchange` handler and the SW's
  // own `client.navigate` can both fire during the same activation
  // — this flag ensures we only ever reload ONCE from this JS
  // runtime.
  var reloaded = false;

  function safeReload() {
    if (reloaded) return;
    if (readReloadedTarget() === RELEASE) return;
    reloaded = true;
    writeReloadedTarget(RELEASE);
    try {
      window.location.reload();
    } catch (_) { /* nothing more to do */ }
  }

  navigator.serviceWorker.addEventListener(
    'controllerchange', function () { safeReload(); },
  );

  function attachInstalledHandler(worker) {
    if (!worker) return;
    try {
      worker.addEventListener('statechange', function () {
        // The migration SW calls self.skipWaiting() on install,
        // so we don't need to postMessage it. State transitions:
        //   installing -> installed -> activating -> activated
        // On `activated`, `controllerchange` fires on the client
        // if this SW claimed it — safeReload() handles the reload.
      });
    } catch (_) {}
  }

  function registerNow() {
    try {
      navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE })
        .then(function (reg) {
          if (!reg) return;
          if (reg.installing) attachInstalledHandler(reg.installing);
          if (reg.waiting) attachInstalledHandler(reg.waiting);
          reg.addEventListener('updatefound', function () {
            attachInstalledHandler(reg.installing);
          });
          try { reg.update(); } catch (_) {}
        })
        .catch(function () { /* SW registration blocked — no-op */ });
    } catch (_) { /* very old UA — no SW support */ }
  }

  // Register on `load` so Flutter's bootstrap can start fetching
  // in parallel and the initial paint isn't blocked. On very old
  // UAs without addEventListener (guarded above) we've already
  // returned.
  if (document.readyState === 'complete') {
    registerNow();
  } else {
    window.addEventListener('load', registerNow, { once: true });
  }
})();
