// 2026-07-14 (Round 11 — real service-worker retirement):
// migration Flutter service worker.
//
// PROBLEM this file solves:
//
//   Users installed the previous offline-first Flutter service
//   worker. That SW controls their tab and serves the old
//   `main.dart.js` from Cache Storage on every navigation. Simply
//   deploying a new bundle does NOT change what code runs in that
//   tab — the OLD JS has no AppReleaseController, cannot detect
//   `release.json` changes, and cannot trigger a reload. `flutter
//   build web --pwa-strategy=none` writes an empty SW body that
//   ALSO does nothing for existing controlled tabs: without
//   `skipWaiting()` it sits in the "waiting" state until every
//   controlled client closes, and without `clients.claim()` the
//   old SW keeps intercepting fetches.
//
// SW LIFECYCLE (browser-mandated):
//
//   1. On tab navigation / 24-hour tick, the browser fetches this
//      file from the network (SW-update requests skip the HTTP
//      cache per spec — reinforced by our Nginx `no-store`
//      header).
//   2. Byte-diff against the currently-installed SW body. If
//      different, install this one as the "waiting" SW.
//   3. `install` handler fires → we call `self.skipWaiting()` so
//      the browser activates us immediately, without waiting for
//      controlled clients to close.
//   4. `activate` handler fires → we call `self.clients.claim()`
//      so all existing controlled clients start routing through
//      us (a passthrough SW: no fetch handler = network).
//   5. `activate` handler drains every `flutter*` cache from
//      Cache Storage.
//   6. `activate` handler enumerates controlled window clients and
//      calls `client.navigate(client.url)` on each — a one-time
//      reload that brings the NEW `main.dart.js` (containing
//      `AppReleaseController`) into the tab. From then on, every
//      subsequent update is handled by the AppReleaseController's
//      `/release.json` detector — no further SW involvement.
//
// LIFECYCLE OF THIS SW ACROSS FUTURE DEPLOYMENTS:
//
//   The body of this file is stable across releases (no version
//   string here). Nginx serves it with `Cache-Control: no-store`
//   AND the SW-update request bypasses HTTP cache anyway, so
//   browsers still re-fetch periodically — but they see the same
//   bytes, do nothing, and the AppReleaseController continues to
//   drive every release rollout.
//
// SECURITY / DATA-LOSS INVARIANTS:
//
//   * NEVER touch localStorage / sessionStorage / IndexedDB /
//     cookies. This SW only deletes Cache Storage entries whose
//     name starts with 'flutter'. Auth session, wallet ciphertext,
//     user prefs are all untouched.
//   * NEVER call `client.navigate` twice per session — the
//     activate handler only fires when this SW becomes active,
//     and we only mint the reload on the first activation.
//   * Fetch handler is intentionally omitted. A pass-through SW
//     lets the browser make ordinary network fetches, which
//     Nginx's `no-store` header on shell files then guarantees
//     fresh code on every navigation.
//
// Do NOT check in a fetch handler here. Do NOT precache anything.

'use strict';


self.addEventListener('install', function (event) {
  // Activate immediately without waiting for old tabs to close.
  console.log('[vaultai-sw] install: calling skipWaiting'); // TEMP diag 2026-07-17
  self.skipWaiting();
});


self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    console.log('[vaultai-sw] activate: start'); // TEMP diag 2026-07-17
    // Take control of every already-open client controlled by
    // the previous SW.
    try {
      await self.clients.claim();
      console.log('[vaultai-sw] activate: clients claimed'); // TEMP diag 2026-07-17
    } catch (_) { /* older browsers: nothing more we can do. */ }

    // Drain stale offline-first caches. Only names starting with
    // 'flutter' — this SW must never touch caches that hold
    // long-lived non-flutter data.
    try {
      var names = await caches.keys();
      var deleted = 0;
      for (var i = 0; i < names.length; i++) {
        if (typeof names[i] === 'string' &&
            names[i].indexOf('flutter') === 0) {
          try { await caches.delete(names[i]); deleted++; } catch (_) {}
        }
      }
      console.log('[vaultai-sw] activate: drained ' + deleted + ' flutter cache(s)'); // TEMP diag 2026-07-17
    } catch (_) { /* Cache Storage unsupported: ignore. */ }

    // 2026-07-17: the previous `clients[j].navigate(clients[j].url)`
    // loop that used to live here caused an infinite reload cycle.
    // Both this SW's navigate() AND the bootstrap's controllerchange
    // listener were triggering reloads for the same activation; on
    // Chrome (and, symmetrically, iPhone Safari) the two paths
    // raced past the sessionStorage dedup and looped forever.
    //
    // The single reload path now lives ONLY in
    // vaultai-sw-bootstrap.js's `controllerchange` handler, which
    // dedupes via `sessionStorage['vaultai_sw_migration_reloaded']`.
    // This SW no longer forces client navigation; it just claims
    // clients + drains flutter caches. Fresh code is picked up by
    // the bootstrap's reload OR the next natural navigation.
    console.log('[vaultai-sw] activate: done (no navigate loop)'); // TEMP diag 2026-07-17
  })());
});


// No fetch handler = pass-through. Every request goes to the
// network, where Nginx's cache policy (see
// deploy/nginx/app.svaultai.com.conf) decides freshness.
