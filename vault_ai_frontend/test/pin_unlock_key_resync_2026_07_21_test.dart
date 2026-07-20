// Regression tests for the 2026-07-21 "first chat still forces PIN"
// incident (deployment e797516 was live but the desync was not
// closed — the earlier "refetch after /rotate-vault-kdf" patch only
// fixed the rotate-response race, not the general drift window
// between the cached client key and the server's current DB state
// on every chat send).
//
// Definitive fix pinned by this file:
//
//   * `_VaultCrypto` records the (salt, iterations) that each cached
//     key was derived from — the "key origin".
//   * Before every chat encrypt (`_send()` and the delete-item
//     sentinel path `_startSecureItemDeleteConfirmation`), the client
//     calls `AppState.resyncCryptoKeyIfDrifted` which fetches
//     /vault-meta, compares to the recorded origin, and re-derives
//     ONLY when the server's current state differs.
//
// The pre-fix production symptom was:
//
//   PIN unlock → try to chat → 400 "Invalid PIN or corrupted data"
//   from `decrypt_message` at vault_core.py:225 →
//   `InvalidVaultUnlockException` on the client → snackbar reads
//   "Your vault unlock session expired or no longer matches this
//   vault. Please enter your PIN again." → user bounced to /pin.
//   Second PIN entry succeeded because by then the client re-derived
//   from the post-rotation salt.
//
// Source-scan tests only — no Flutter runtime — so the invariants
// hold as PR-level structural guarantees.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _mainDart() => File('lib/main.dart').readAsStringSync();


void main() {
  group('_VaultCrypto — key origin is tracked per cache slot', () {
    test('_KeyOrigin class exists with saltBase64 + iterations', () {
      final src = _mainDart();
      expect(src.contains('class _KeyOrigin'), isTrue,
          reason: 'a _KeyOrigin type must exist to record the salt+iter '
                  'the cached key was derived from');
      final classIdx = src.indexOf('class _KeyOrigin');
      final windowEnd = (classIdx + 600).clamp(0, src.length);
      final window = src.substring(classIdx, windowEnd);
      expect(window.contains('saltBase64'), isTrue,
          reason: '_KeyOrigin must record the salt as base64');
      expect(window.contains('iterations'), isTrue,
          reason: '_KeyOrigin must record the iteration count');
    });

    test('_VaultCrypto declares a _keyOrigin map', () {
      final src = _mainDart();
      final classIdx = src.indexOf('class _VaultCrypto');
      expect(classIdx, greaterThan(-1));
      // Look inside the first ~800 chars of the class body for the
      // field declaration.
      final windowEnd = (classIdx + 1500).clamp(0, src.length);
      final window = src.substring(classIdx, windowEnd);
      expect(
        window.contains('_keyOrigin'),
        isTrue,
        reason: '_VaultCrypto must declare _keyOrigin to track '
                'per-slot derivation origin',
      );
    });

    test('deriveAndCacheKey writes to _keyOrigin', () {
      final src = _mainDart();
      // Anchor on the DECLARATION, not any caller.
      final fnIdx = src.indexOf('static Future<void> deriveAndCacheKey');
      expect(fnIdx, greaterThan(-1),
          reason: 'the deriveAndCacheKey static method declaration '
                  'must exist on _VaultCrypto');
      final windowEnd = (fnIdx + 2500).clamp(0, src.length);
      final window = src.substring(fnIdx, windowEnd);
      expect(
        window.contains('_keyOrigin['),
        isTrue,
        reason: 'deriveAndCacheKey must record the (salt, iterations) '
                'origin at the same cache slot as the key itself',
      );
    });

    test('clearCache and clearSession remove _keyOrigin entries', () {
      final src = _mainDart();
      final clearIdx = src.indexOf('static void clearCache');
      expect(clearIdx, greaterThan(-1));
      final clearWindowEnd = (clearIdx + 800).clamp(0, src.length);
      final clearWindow = src.substring(clearIdx, clearWindowEnd);
      expect(clearWindow.contains('_keyOrigin.removeWhere'), isTrue,
          reason: 'clearCache must drop the origin entries alongside '
                  'the key and pin caches');

      final sessIdx = src.indexOf('Future<void> clearSession');
      expect(sessIdx, greaterThan(-1));
      final sessWindowEnd = (sessIdx + 1400).clamp(0, src.length);
      final sessWindow = src.substring(sessIdx, sessWindowEnd);
      expect(sessWindow.contains('_keyOrigin.remove('), isTrue,
          reason: 'clearSession must drop the origin entry for the '
                  'leaving vault alongside the key and pin caches');
    });
  });

  group('AppState.resyncCryptoKeyIfDrifted — the sync gate', () {
    test('AppState declares resyncCryptoKeyIfDrifted', () {
      final src = _mainDart();
      expect(
        src.contains('Future<void> resyncCryptoKeyIfDrifted'),
        isTrue,
        reason: 'AppState must expose an authoritative "resync from '
                'server /vault-meta" method that other paths (chat '
                'send, delete sentinel) call before encrypting',
      );
    });

    test('resyncCryptoKeyIfDrifted fetches /vault-meta and compares '
         'to the recorded origin', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('Future<void> resyncCryptoKeyIfDrifted');
      expect(fnIdx, greaterThan(-1));
      // Scan a generous window for the two required behaviors:
      // authoritative vault-meta GET + salt/iter drift comparison.
      final windowEnd = (fnIdx + 3500).clamp(0, src.length);
      final window = src.substring(fnIdx, windowEnd);
      expect(window.contains('getVaultMeta'), isTrue,
          reason: 'resyncCryptoKeyIfDrifted must issue a fresh '
                  '/vault-meta GET as the authoritative source of '
                  'current pin_salt + kdf_iterations');
      expect(window.contains('originFor('), isTrue,
          reason: 'resyncCryptoKeyIfDrifted must consult the recorded '
                  'origin for the current cache slot');
      expect(window.contains('saltChanged') || window.contains('salt_changed'),
          isTrue,
          reason: 'resyncCryptoKeyIfDrifted must compare fresh salt '
                  'to the recorded origin salt');
      expect(window.contains('iterChanged') || window.contains('iter_changed'),
          isTrue,
          reason: 'resyncCryptoKeyIfDrifted must compare fresh iter '
                  'to the recorded origin iter');
      expect(window.contains('deriveAndCacheKey'), isTrue,
          reason: 'resyncCryptoKeyIfDrifted must re-derive with the '
                  'fresh salt/iter when drift is detected');
    });

    test('resyncCryptoKeyIfDrifted short-circuits when no origin exists '
         '(ZK-adopted vault safety)', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('Future<void> resyncCryptoKeyIfDrifted');
      final windowEnd = (fnIdx + 3500).clamp(0, src.length);
      final window = src.substring(fnIdx, windowEnd);
      // Absence of a recorded origin means the cache slot was
      // populated directly (ZK adoption path stores the MVK without
      // a PBKDF2 derivation). We must NOT try to re-derive from a PIN
      // in that case.
      expect(
        window.contains('origin == null'),
        isTrue,
        reason: 'resyncCryptoKeyIfDrifted must safely no-op when no '
                'PBKDF2 origin is recorded — ZK-adopted vaults store '
                'the MVK directly in _keyCache and there is nothing '
                'to re-derive from a PIN',
      );
    });

    test('resyncCryptoKeyIfDrifted swallows /vault-meta errors — no '
         'forced re-PIN on a transient network drop', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('Future<void> resyncCryptoKeyIfDrifted');
      final windowEnd = (fnIdx + 3500).clamp(0, src.length);
      final window = src.substring(fnIdx, windowEnd);
      // A catch around the vault-meta fetch is the requirement — a
      // transient failure must NOT tear down the unlock session; it
      // just leaves the current (possibly-stale) key in place. If it
      // WAS actually stale, the /chat that follows still surfaces
      // InvalidVaultUnlockException as before — but a genuine
      // network hiccup no longer forces a needless re-PIN.
      expect(window.contains('catch'), isTrue,
          reason: 'resyncCryptoKeyIfDrifted must catch fetch failures '
                  'so a transient network drop does not compound into '
                  'a forced re-PIN');
    });
  });

  group('Chat send paths — resync happens BEFORE encrypt', () {
    test('_send() awaits resyncCryptoKeyIfDrifted before encrypt', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      expect(sendIdx, greaterThan(-1));
      // Grab the whole function body (heuristic bound; the file is
      // large so we scan a fat window).
      final windowEnd = (sendIdx + 20000).clamp(0, src.length);
      final window = src.substring(sendIdx, windowEnd);
      final resyncIdx = window.indexOf('resyncCryptoKeyIfDrifted');
      final encryptIdx = window.indexOf('_VaultCrypto.encrypt(text)');
      expect(resyncIdx, greaterThan(-1),
          reason: '_send() must invoke resyncCryptoKeyIfDrifted before '
                  'encrypting the chat message');
      expect(encryptIdx, greaterThan(-1),
          reason: '_send() must call _VaultCrypto.encrypt(text)');
      expect(resyncIdx, lessThan(encryptIdx),
          reason: 'resyncCryptoKeyIfDrifted must run BEFORE the '
                  '_VaultCrypto.encrypt(text) call — running after it '
                  'is a bug because the stale key would already be '
                  'used for the ciphertext the server tries to decrypt');
    });

    test('_startSecureItemDeleteConfirmation awaits resync before '
         'encrypt', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('_startSecureItemDeleteConfirmation');
      expect(fnIdx, greaterThan(-1));
      final windowEnd = (fnIdx + 8000).clamp(0, src.length);
      final window = src.substring(fnIdx, windowEnd);
      final resyncIdx = window.indexOf('resyncCryptoKeyIfDrifted');
      final encryptIdx = window.indexOf('_VaultCrypto.encrypt(sentinel)');
      expect(resyncIdx, greaterThan(-1),
          reason: 'the delete-item sentinel path must also resync — '
                  'otherwise deleting an item first-thing after PIN '
                  'unlock repros the same 400 as the plain chat path');
      expect(encryptIdx, greaterThan(-1));
      expect(resyncIdx, lessThan(encryptIdx),
          reason: 'resync must run before the sentinel encrypt');
    });
  });
}
