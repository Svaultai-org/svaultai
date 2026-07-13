/// Web implementation of the AppReleaseController side-effects
/// (service-worker unregister, cache clear, reload, sessionStorage).
///
/// This file is only compiled on `dart.library.html` targets. All
/// entry points wrap DOM/JS access in try/catch — a broken browser
/// API must never cause a fatal reload loop.

// ignore_for_file: deprecated_member_use
// dart:html is scheduled for eventual removal but is the stable
// path for Flutter 3.38 web. package:web + dart:js_interop is the
// eventual successor. Migrate when the frontend adds package:web.

import 'dart:html' as html;


/// Aggressively unregister every Flutter service worker owning
/// scripts under this origin. Works even if the SW was installed
/// with an older Flutter build that used `--pwa-strategy=offline-
/// first`.
Future<void> unregisterFlutterServiceWorker() async {
  try {
    final container = html.window.navigator.serviceWorker;
    if (container == null) return;
    final regs = await container.getRegistrations();
    for (final reg in regs) {
      try {
        await reg.unregister();
      } catch (_) {
        // Continue with next registration.
      }
    }
  } catch (_) {
    // No SW support / older browser.
  }
}


/// Clear only Cache Storage entries a Flutter web bundle would have
/// populated (anything whose name starts with `flutter`). DO NOT
/// touch `localStorage`, `sessionStorage`, `IndexedDB`, or cookies
/// — those hold the auth session, wallet ciphertext, and user
/// prefs.
Future<void> clearAppCodeCacheEntries() async {
  try {
    final caches = html.window.caches;
    if (caches == null) return;
    final names = await caches.keys();
    for (final name in names) {
      if (name.startsWith('flutter')) {
        try {
          await caches.delete(name);
        } catch (_) {
          // Continue with next cache.
        }
      }
    }
  } catch (_) {
    // Cache Storage unavailable — the `no-store` Nginx headers on
    // the shell files will still deliver a fresh bundle on reload.
  }
}


void reloadPage() {
  try {
    html.window.location.reload();
  } catch (_) {
    // Nothing more we can do.
  }
}


const String _kSessionKey = 'vaultai_release_reload_target';


String? readLastAttemptedTargetRelease() {
  try {
    final raw = html.window.sessionStorage[_kSessionKey];
    if (raw == null || raw.isEmpty) return null;
    return raw;
  } catch (_) {
    return null;
  }
}


void writeLastAttemptedTargetRelease(String target) {
  try {
    html.window.sessionStorage[_kSessionKey] = target;
  } catch (_) {
    // sessionStorage disabled — loop protection degrades to the
    // controller's own `_updateInProgress` flag.
  }
}
