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
  var hadControllerAtBootstrap =
    !!(navigator.serviceWorker && navigator.serviceWorker.controller);

  // TEMP diag 2026-07-17
  console.log('[vaultai-sw-bootstrap] loaded; RELEASE=' + RELEASE);

  if (!('serviceWorker' in navigator)) {
    console.log('[vaultai-sw-bootstrap] navigator.serviceWorker unsupported; abort'); // TEMP diag 2026-07-17
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

  // Per-runtime dedupe. Previously this handled a race between the
  // controllerchange listener and the SW's own client.navigate()
  // — the SW no longer navigates (Round 13 fix, 2026-07-17), so
  // this flag is now belt-and-braces against a browser that fires
  // controllerchange more than once for a single activation.
  var reloaded = false;

  function safeReload() {
    // A first visit was loaded directly from this release. Claiming that
    // uncontrolled page is safe and does not justify a full Flutter restart.
    if (!hadControllerAtBootstrap) {
      writeReloadedTarget(RELEASE);
      console.log('[vaultai-sw-bootstrap] first controller claim, skip reload');
      return;
    }
    if (reloaded) {
      console.log('[vaultai-sw-bootstrap] safeReload: runtime flag set, skip'); // TEMP diag 2026-07-17
      return;
    }
    var target = readReloadedTarget();
    if (target === RELEASE) {
      console.log('[vaultai-sw-bootstrap] safeReload: sessionStorage=RELEASE, skip'); // TEMP diag 2026-07-17
      return;
    }
    reloaded = true;
    writeReloadedTarget(RELEASE);
    console.log('[vaultai-sw-bootstrap] safeReload: reloading NOW for release=' + RELEASE); // TEMP diag 2026-07-17
    try {
      window.location.reload();
    } catch (_) { /* nothing more to do */ }
  }

  navigator.serviceWorker.addEventListener(
    'controllerchange', function () {
      console.log('[vaultai-sw-bootstrap] controllerchange fired'); // TEMP diag 2026-07-17
      safeReload();
    },
  );

  function attachInstalledHandler(worker) {
    if (!worker) return;
    try {
      worker.addEventListener('statechange', function () {
        // TEMP diag 2026-07-17
        console.log('[vaultai-sw-bootstrap] SW state=' + worker.state);
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
      console.log('[vaultai-sw-bootstrap] register(' + SW_URL + ')'); // TEMP diag 2026-07-17
      navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE })
        .then(function (reg) {
          if (!reg) return;
          // TEMP diag 2026-07-17
          console.log('[vaultai-sw-bootstrap] register ok; installing=' +
            !!reg.installing + ' waiting=' + !!reg.waiting +
            ' active=' + !!reg.active);
          if (reg.installing) attachInstalledHandler(reg.installing);
          if (reg.waiting) attachInstalledHandler(reg.waiting);
          reg.addEventListener('updatefound', function () {
            console.log('[vaultai-sw-bootstrap] updatefound'); // TEMP diag 2026-07-17
            attachInstalledHandler(reg.installing);
          });
          try { reg.update(); } catch (_) {}
        })
        .catch(function (err) {
          console.warn('[vaultai-sw-bootstrap] register failed:', err); // TEMP diag 2026-07-17
        });
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
