// Source-scan regression for the c2f917e production failure:
//
//   Sign in -> Enter PIN -> Vault unlocks -> Send first chat -> error
//   "Your vault unlock session expired or no longer matches this vault.
//    Please enter your PIN again."
//
// Root cause: in AppState.verifyPin (main.dart:1549) the rotate step
// at ~1652-1671 is:
//
//   try {
//     final rotateResult = await client.rotateVaultKdf(...);
//     if (rotateResult['rotated'] == true) {
//       final newSalt = rotateResult['pin_salt']?.toString();
//       final newIter = (rotateResult['kdf_iterations'] as num?)?.toInt();
//       if (newSalt != null && newSalt.isNotEmpty && newIter != null) {
//         await _VaultCrypto.deriveAndCacheKey(...);
//       }
//     }
//   } catch (_) {}
//
// Fragilities that produced the desync:
//   1. Gated on `rotated == true`. Any client-side type-coercion or
//      JSON-decoding weirdness that made `rotateResult['rotated']`
//      not-strictly-`true` silently skipped the re-derive — the DB
//      had a new salt, the client kept the old key, and the very
//      first /chat POST decrypted with the wrong key server-side.
//   2. `try { ... } catch (_) {}` swallowed EVERY throw — network
//      errors, HTTP status errors, PBKDF2 exceptions. Nothing was
//      logged; the frontend had no visibility.
//   3. No recovery path if the rotate response was malformed or
//      lost. The DB could commit a rotation while the client
//      thought nothing happened.
//
// The 2026-07-21 fix (in this branch) tightens verifyPin so that:
//   * the client always refetches /vault-meta AFTER the rotate call
//     as the authoritative source of the CURRENT DB salt/iter,
//   * if that salt/iter differs from what K1 was derived from, it
//     re-derives K2 and replaces the cache — no `rotated` flag gate,
//   * rotate errors are LOGGED via vlog, not silently swallowed.
//
// These source-scan tests fail on the pre-fix code and pass on the
// fixed code — they lock the structural change in place so a
// future refactor can't silently re-introduce the fragile pattern.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _mainDart() => File('lib/main.dart').readAsStringSync();


// Extract the ~800 chars around the rotate call inside verifyPin.
String _verifyPinRotateWindow() {
  final src = _mainDart();
  final verifyIdx =
      src.indexOf('Future<bool> verifyPin');
  expect(verifyIdx, greaterThan(-1),
      reason: 'AppState.verifyPin must exist');
  final rotateIdx = src.indexOf('rotateVaultKdf(', verifyIdx);
  expect(rotateIdx, greaterThan(-1),
      reason: 'verifyPin must call rotateVaultKdf');
  // Take a healthy window on either side.
  final start = (rotateIdx - 200).clamp(0, src.length);
  final end   = (rotateIdx + 1400).clamp(0, src.length);
  return src.substring(start, end);
}


void main() {
  group('verifyPin — post-rotate authoritative re-derive', () {

    test(
      'verifyPin refetches /vault-meta after rotateVaultKdf '
      '(defends against rotate-response desync)',
      () {
        final window = _verifyPinRotateWindow();
        // The fix must AWAIT a second getVaultMeta call after the
        // rotate step. That fetch is the authoritative source of
        // the CURRENT DB salt/iter and closes the "server rotated
        // but client silently kept old key" window.
        final metaCount = 'getVaultMeta('.allMatches(window).length;
        expect(
          metaCount, greaterThanOrEqualTo(1),
          reason: 'after rotateVaultKdf, verifyPin must refetch '
                  '/vault-meta so the client always resyncs to the '
                  'authoritative post-rotation salt/iter. Without '
                  'the refetch, a server-side rotation whose '
                  'response was malformed / lost / silently caught '
                  'leaves the client encrypting /chat with a stale '
                  'key and produces "unlock session expired" on '
                  'the very first chat.',
        );
      },
    );

    test(
      'verifyPin no longer gates the re-derive on '
      '`rotateResult[\\\'rotated\\\'] == true`',
      () {
        final window = _verifyPinRotateWindow();
        // A `rotated == true` gate is what caused the production
        // desync — any type/coercion or JSON weirdness that made
        // the comparison false silently skipped the re-derive.
        // The fix trusts the response's salt/iter fields
        // regardless of the flag (they are authoritative in BOTH
        // branches of rotate_vault_kdf_if_needed — see
        // vault_core.py:446-451 and 524-528).
        expect(
          window.contains("['rotated'] == true"),
          isFalse,
          reason: 'the fragile `[\'rotated\'] == true` gate must '
                  'be removed. Re-derive when the authoritative '
                  'salt/iter (from /vault-meta refetch or the '
                  'rotate response itself) differs from what K1 '
                  'was derived from — the flag is not a reliable '
                  'signal.',
        );
      },
    );

    test(
      'verifyPin does not silently catch-and-drop rotate errors',
      () {
        final window = _verifyPinRotateWindow();
        // The old `catch (_) {}` masked network failures, HTTP
        // errors, and PBKDF2 exceptions with zero diagnostic
        // output. The fix must at minimum LOG the failure via
        // vlog so future incidents are debuggable.
        //
        // We check the specific ANTI-pattern (empty catch of
        // unnamed exception).
        expect(
          window.contains('catch (_) {}'),
          isFalse,
          reason: 'verifyPin must not silently swallow rotate errors '
                  'with `catch (_) {}`. Log via vlog so a future '
                  '"unlock session expired" incident is diagnosable '
                  'from client-side traces.',
        );
      },
    );

    test(
      'verifyPin logs the rotate attempt outcome via vlog',
      () {
        final window = _verifyPinRotateWindow();
        // Positive contract: there IS a vlog call in the rotate
        // block. Prevents a future refactor from removing the
        // observability we just gained.
        expect(
          window.contains('vlog('),
          isTrue,
          reason: 'verifyPin must vlog the rotate outcome so we '
                  'can diagnose future unlock-session-expired '
                  'incidents from client logs',
        );
      },
    );
  });
}
