// Regression tests for the 2026-07-22 production incident that
// followed the f8210d6 deployment. Backend logs proved:
//
//   verify_pin_ok          ← server accepted the PIN
//   decrypt_failed 400     ← ciphertext did NOT decrypt under the
//                            correctly-derived server key
//
// Root cause: the client stored the vault key and its (salt, iter)
// origin in TWO separate maps (`_VaultCrypto._keyCache` and
// `_VaultCrypto._keyOrigin`) written by different code paths at
// different times. The three ZK login/signup paths at main.dart
// lines 3853, 4290, 4639 wrote MVK into `_keyCache` without ever
// touching `_keyOrigin`. On `/chat`, `_send()` read the origin
// first (returning null for the ZK slot), then read the key
// (returning MVK). The request went out with MVK-encrypted body +
// no KDF metadata. Server fell into the legacy pass-through,
// derived the CORRECT PBKDF2 K from the current DB row, tried to
// decrypt MVK-ciphertext with PBKDF2 K → 400 "Invalid PIN or
// corrupted data" → client mis-classified as
// `AuthExpiredException` → user signed out and later saw
// "Incorrect PIN". The key and its metadata were never an atomic
// unit.
//
// Fix contract locked here:
//
//   * Test 1 (atomic snapshot): `_send()` reads its key + salt +
//     iter from ONE `VaultCryptoContext` snapshot captured ONCE.
//     No separate lookups.
//
//   * Test 2 (stale async): a later `deriveAndInstallCryptoContext`
//     call cannot be overwritten by an earlier one that finishes
//     later. Enforced by the operation-id + generation guards on
//     `VaultCryptoRegistry.install`.
//
//   * Test 3 (serializer): a modern build with X-App-Release set
//     serializes `kdf_salt_used` and `kdf_iterations_used` into the
//     chat request body when a context is installed.
//
//   * Test 7 (decrypt UI): a 400 "Invalid PIN or corrupted data"
//     response throws `CryptoContextMismatchException`, NOT
//     `InvalidVaultUnlockException` / `AuthExpiredException`.
//     Auth state survives; user is not signed out and does not
//     see "Incorrect PIN".
//
// Source-scan and behavioral tests. No live network — the
// `VaultCryptoRegistry` and the exception classification are
// unit-testable in isolation.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart'
    show
        VaultCryptoContext,
        VaultCryptoRegistry,
        cryptoFingerprintForKey,
        cryptoFingerprintForSaltBase64,
        deriveAndInstallCryptoContext,
        encryptWithContext;


String _mainDart() => File('lib/main.dart').readAsStringSync();
String _apiClient() => File('lib/api_client.dart').readAsStringSync();


VaultCryptoContext _makeCtx({
  required String vaultId,
  required String vaultName,
  required SecretKey key,
  required String saltBase64,
  required int iterations,
  required int generation,
  required String source,
  String pin = '000000',
}) {
  return VaultCryptoContext(
    vaultId: vaultId,
    vaultName: vaultName,
    key: key,
    pin: pin,
    saltBase64: saltBase64,
    iterations: iterations,
    generation: generation,
    source: source,
  );
}


void main() {
  setUp(() {
    VaultCryptoRegistry.clear(reason: 'test.setUp');
  });

  tearDown(() {
    VaultCryptoRegistry.clear(reason: 'test.tearDown');
  });

  // -------------------------------------------------------------
  // Test 1 (spec) — atomic context snapshot
  // -------------------------------------------------------------
  group('Test 1 — atomic context snapshot', () {
    testWidgets(
      'encryptWithContext uses EXACTLY the passed context\'s key '
      'and never a registry lookup',
      (tester) async {
        final keyA = SecretKey(Uint8List(32));
        final keyBBytes = Uint8List(32)..[0] = 0x01;
        final keyB = SecretKey(keyBBytes);
        final saltA = base64.encode(Uint8List(16));
        final saltB = base64.encode(Uint8List(16)..[0] = 0x02);
        final ctxA = _makeCtx(
          vaultId: 'v-1', vaultName: 'Yola',
          key: keyA, saltBase64: saltA,
          iterations: 1000, generation: 1, source: 'test.A',
        );
        final ctxB = _makeCtx(
          vaultId: 'v-1', vaultName: 'Yola',
          key: keyB, saltBase64: saltB,
          iterations: 1000, generation: 2, source: 'test.B',
        );

        // Install B, then encrypt using A. The encrypt MUST use A's
        // key (the SNAPSHOT the caller holds), not B's (the registry
        // current). This is the atomicity guarantee that prevents
        // "encrypted with keyA + declared saltB" ciphertexts.
        VaultCryptoRegistry.install(
          operationId: VaultCryptoRegistry.nextOperationId(),
          context: ctxB,
        );
        final ctA = await encryptWithContext(
          plaintext: 'hello', context: ctxA,
        );
        final ctB = await encryptWithContext(
          plaintext: 'hello', context: ctxB,
        );
        // Two different keys must produce different ciphertexts.
        expect(ctA, isNot(equals(ctB)),
            reason: 'encryptWithContext must use the passed context\'s '
                    'key exclusively — not do a registry lookup');

        // Decrypt each ciphertext with its OWN key; both must
        // succeed and yield the original plaintext.
        Future<String> decryptWith(String encoded, SecretKey key) async {
          final combined = base64.decode(encoded);
          final nonce = combined.sublist(0, 12);
          final ct = combined.sublist(12, combined.length - 16);
          final mac = combined.sublist(combined.length - 16);
          final aead = AesGcm.with256bits();
          final box = SecretBox(ct, nonce: nonce, mac: Mac(mac));
          final pt = await aead.decrypt(box, secretKey: key);
          return utf8.decode(pt);
        }
        expect(await decryptWith(ctA, keyA), 'hello');
        expect(await decryptWith(ctB, keyB), 'hello');
      },
    );

    test(
      '_send() snapshots VaultCryptoRegistry.current ONCE, then '
      'uses the SAME snapshot for encrypt AND declared metadata',
      () {
        // Structural guarantee: the /chat send path must (a) name
        // its snapshot variable, (b) pass ctxSnapshot.key path via
        // encryptWithContext, and (c) send ctxSnapshot.saltBase64
        // and ctxSnapshot.iterations verbatim. This test scans the
        // source to make sure the atomicity contract cannot be
        // silently broken by a later refactor.
        final src = _mainDart();
        final sendIdx = src.indexOf('Future<void> _send()');
        expect(sendIdx, greaterThan(-1));
        final windowEnd = (sendIdx + 20000).clamp(0, src.length);
        final fn = src.substring(sendIdx, windowEnd);

        final snapIdx = fn.indexOf('final ctxSnapshot = VaultCryptoRegistry');
        expect(snapIdx, greaterThan(-1),
            reason: '_send() must snapshot VaultCryptoRegistry.current '
                    'into a named local variable ONCE');

        final encIdx = fn.indexOf('encryptWithContext(');
        expect(encIdx, greaterThan(-1),
            reason: '_send() must encrypt via encryptWithContext '
                    '(which pins the key from the passed context)');
        expect(encIdx, greaterThan(snapIdx),
            reason: 'the snapshot must be captured BEFORE the '
                    'encrypt call');

        // Every kdf field on the outgoing chatStream call MUST
        // read from ctxSnapshot.* — not from any other source.
        final streamCallIdx = fn.indexOf('client.chatStream(');
        final windowStream =
            fn.substring(streamCallIdx, (streamCallIdx + 3000)
                .clamp(0, fn.length));
        expect(
          windowStream.contains('kdfSaltUsed: ctxSnapshot.saltBase64'),
          isTrue,
          reason: 'chatStream must be passed ctxSnapshot.saltBase64 '
                  '(NOT a separate origin lookup)',
        );
        expect(
          windowStream.contains('kdfIterationsUsed: ctxSnapshot.iterations'),
          isTrue,
          reason: 'chatStream must be passed ctxSnapshot.iterations',
        );
      },
    );
  });

  // -------------------------------------------------------------
  // Test 2 (spec) — stale async completion cannot overwrite
  // -------------------------------------------------------------
  group('Test 2 — stale async cannot clobber newer context', () {
    test(
      'earlier operationId cannot overwrite a later install',
      () {
        final kA = SecretKey(Uint8List(32));
        final kB = SecretKey(Uint8List(32)..[0] = 0xAB);
        final salt = base64.encode(Uint8List(16));

        // Reserve op 1 first, op 2 second — B "started later".
        final op1 = VaultCryptoRegistry.nextOperationId();
        final op2 = VaultCryptoRegistry.nextOperationId();
        expect(op2, greaterThan(op1));

        // B completes first, installs at generation 1.
        final ctxB = _makeCtx(
          vaultId: 'v', vaultName: 'Yola',
          key: kB, saltBase64: salt,
          iterations: 1000, generation: VaultCryptoRegistry.nextGeneration(),
          source: 'B',
        );
        final okB = VaultCryptoRegistry.install(
          operationId: op2, context: ctxB,
        );
        expect(okB, isTrue,
            reason: 'B (op 2) must install cleanly — it holds the '
                    'operation-peak reservation');
        expect(VaultCryptoRegistry.current?.source, 'B');

        // A completes LATER but its op id is 1 (superseded). Also
        // note its generation would come from nextGeneration() so
        // it's numerically greater — but the operation-id guard
        // still refuses it because op2 is the peak.
        final ctxA = _makeCtx(
          vaultId: 'v', vaultName: 'Yola',
          key: kA, saltBase64: salt,
          iterations: 1000, generation: VaultCryptoRegistry.nextGeneration(),
          source: 'A',
        );
        final okA = VaultCryptoRegistry.install(
          operationId: op1, context: ctxA,
        );
        expect(okA, isFalse,
            reason: 'A (op 1) MUST be refused — a later reservation '
                    'has superseded it');
        expect(VaultCryptoRegistry.current?.source, 'B',
            reason: 'stale install must NOT overwrite the current '
                    'context');
      },
    );

    test(
      'generation guard refuses install with lower or equal '
      'generation even when operationId is fresh',
      () {
        final k1 = SecretKey(Uint8List(32));
        final k2 = SecretKey(Uint8List(32)..[0] = 0x02);
        final salt = base64.encode(Uint8List(16));

        // Install context at generation 5 (skip 1..4 for realism).
        for (var i = 0; i < 5; i++) {
          VaultCryptoRegistry.nextGeneration();
        }
        VaultCryptoRegistry.install(
          operationId: VaultCryptoRegistry.nextOperationId(),
          context: _makeCtx(
            vaultId: 'v', vaultName: 'Yola',
            key: k1, saltBase64: salt,
            iterations: 1000, generation: 5, source: 'seed',
          ),
        );
        expect(VaultCryptoRegistry.current?.generation, 5);

        // Now try to install at generation 5 (equal). Must refuse.
        final ok = VaultCryptoRegistry.install(
          operationId: VaultCryptoRegistry.nextOperationId(),
          context: _makeCtx(
            vaultId: 'v', vaultName: 'Yola',
            key: k2, saltBase64: salt,
            iterations: 1000, generation: 5, source: 'lower',
          ),
        );
        expect(ok, isFalse,
            reason: 'generation must strictly increase');
        expect(VaultCryptoRegistry.current?.source, 'seed');
      },
    );
  });

  // -------------------------------------------------------------
  // Test 3 (spec) — production serializer includes KDF fields
  // -------------------------------------------------------------
  group('Test 3 — production serializer includes KDF fields', () {
    test('chatStream body serializer includes kdf_salt_used + '
         'kdf_iterations_used when both are provided', () {
      final src = _apiClient();
      final fnIdx = src.indexOf('Stream<String> chatStream');
      expect(fnIdx, greaterThan(-1));
      final bodyIdx = src.indexOf('request.body = jsonEncode', fnIdx);
      final bodyEnd = src.indexOf('});', bodyIdx);
      final body = src.substring(bodyIdx, bodyEnd);
      expect(body.contains("'kdf_salt_used'"), isTrue);
      expect(body.contains("'kdf_iterations_used'"), isTrue);
      expect(body.contains('kdfSaltUsed'), isTrue);
      expect(body.contains('kdfIterationsUsed'), isTrue);
    });

    test('every request sends X-App-Release when APP_RELEASE is '
         'not "dev"', () {
      final src = _apiClient();
      final defIdx = src.indexOf('Map<String, String> _defaultHeaders(');
      expect(defIdx, greaterThan(-1));
      final endIdx = src.indexOf('return headers;', defIdx);
      final fn = src.substring(defIdx, endIdx);
      expect(fn.contains("'X-App-Release'"), isTrue,
          reason: '_defaultHeaders must send X-App-Release so the '
                  'server can identify modern clients');
      expect(fn.contains("String.fromEnvironment('APP_RELEASE'"), isTrue,
          reason: 'the header value must come from the build-time '
                  'APP_RELEASE constant');
      expect(fn.contains("_appRelease != 'dev'"), isTrue,
          reason: 'dev-only local builds must NOT identify as modern '
                  '— they would fail the missing-fields check');
    });
  });

  // -------------------------------------------------------------
  // Test 7 (spec) — 400 decrypt failure UI: no logout, no
  // "Incorrect PIN"
  // -------------------------------------------------------------
  group('Test 7 — 400 decrypt failure classification', () {
    test('api_client._throwIfInvalidVaultUnlock throws '
         'CryptoContextMismatchException, NOT InvalidVaultUnlockException',
         () {
      final src = _apiClient();
      final fnIdx = src.indexOf('void _throwIfInvalidVaultUnlock');
      expect(fnIdx, greaterThan(-1));
      final endIdx = src.indexOf('}\n', fnIdx);
      final fn = src.substring(fnIdx, endIdx);
      expect(fn.contains('CryptoContextMismatchException()'), isTrue,
          reason: '400 decrypt failure must throw the typed '
                  'CryptoContextMismatchException so the session '
                  'is preserved');
      expect(fn.contains('InvalidVaultUnlockException()'), isFalse,
          reason: 'the 400 decrypt path must NOT use the sign-out '
                  'InvalidVaultUnlockException type any more');
    });

    test('AppState.handleApiException(CryptoContextMismatchException) '
         'does NOT call clearSession and does NOT navigate away', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('bool handleApiException(Object error)');
      expect(fnIdx, greaterThan(-1));
      final windowEnd = (fnIdx + 4000).clamp(0, src.length);
      final fn = src.substring(fnIdx, windowEnd);
      final branchIdx = fn.indexOf('error is CryptoContextMismatchException');
      expect(branchIdx, greaterThan(-1),
          reason: 'handleApiException must have an explicit branch '
                  'for the crypto-mismatch type');
      // Slice the branch body.
      final branchEnd = fn.indexOf('return true;', branchIdx);
      final branch = fn.substring(branchIdx, branchEnd);
      expect(branch.contains('clearSession'), isFalse,
          reason: 'CryptoContextMismatch must NOT clear the session');
      expect(branch.contains('pushNamedAndRemoveUntil'), isFalse,
          reason: 'CryptoContextMismatch must NOT navigate away — '
                  'the caller controls where the user goes');
      expect(branch.contains("authed = false"), isFalse,
          reason: 'CryptoContextMismatch must NOT tear down auth');
      expect(branch.contains("unlocked = false"), isFalse,
          reason: 'CryptoContextMismatch must NOT drop the unlock');
    });

    test('_send() 400 handler preserves input, drops the failed '
         'user bubble, and does NOT navigate', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      final windowEnd = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, windowEnd);
      // Slice the branch body via brace-depth so nested
      // `if (!mounted) return;` bail-outs don't cut it short.
      final ifIdx = fn.indexOf('if (err is CryptoContextMismatchException)');
      expect(ifIdx, greaterThan(-1),
          reason: '_send() must catch the typed 400');
      final openBrace = fn.indexOf('{', ifIdx);
      var depth = 0;
      var i = openBrace;
      var closeIdx = -1;
      while (i < fn.length) {
        final ch = fn[i];
        if (ch == '{') depth++;
        if (ch == '}') {
          depth--;
          if (depth == 0) { closeIdx = i; break; }
        }
        i++;
      }
      expect(closeIdx, greaterThan(-1),
          reason: 'unbalanced braces in the 400 branch');
      final branch = fn.substring(ifIdx, closeIdx + 1);
      expect(branch.contains('input.text = text'), isTrue,
          reason: 'must restore the input so the user can retry');
      expect(branch.contains("'/pin'"), isFalse,
          reason: 'must NOT navigate to /pin');
      expect(branch.contains("'/login'"), isFalse,
          reason: 'must NOT navigate to /login');
      expect(branch.contains('clearSession'), isFalse,
          reason: 'must NOT clear the session');
      // Look for a recursive _send( call — the `_send(` string is
      // fine to appear inside comments, so check for the actual
      // await pattern.
      expect(branch.contains('await _send('), isFalse,
          reason: 'must NOT auto-retry');
    });

    test('PinInvalidException is defined and does NOT extend '
         'AuthExpiredException', () {
      final src = _apiClient();
      expect(src.contains('class PinInvalidException'), isTrue);
      expect(src.contains('class CryptoContextMismatchException'), isTrue);
      // These typed exceptions are peers, not siblings of a shared
      // base that could accidentally group them.
      final pinIdx = src.indexOf('class PinInvalidException');
      final windowEnd = (pinIdx + 500).clamp(0, src.length);
      expect(
        src.substring(pinIdx, windowEnd)
          .contains('extends AuthExpiredException'),
        isFalse,
        reason: 'PinInvalidException must NOT extend the sign-out '
                'exception type',
      );
    });
  });

  // -------------------------------------------------------------
  // Test 8 (spec) partial — legitimate session terminations
  // still terminate. See backend test file for the code-list guard.
  // -------------------------------------------------------------
  group('Test 8 — real session codes still sign out', () {
    test('handleApiException(SessionTerminatedException) is '
         'documented as clearing session', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('bool handleApiException(Object error)');
      final windowEnd = (fnIdx + 4000).clamp(0, src.length);
      final fn = src.substring(fnIdx, windowEnd);
      expect(fn.contains('SessionTerminatedException'), isTrue,
          reason: 'the session-termination branch must still exist');
      // AuthExpiredException branch still exists — for legitimate
      // uncoded 401s NOT reclassified to invalid_pin.
      expect(fn.contains('AuthExpiredException'), isTrue,
          reason: 'the AuthExpired branch must still exist as the '
                  'fallback for genuinely un-typed 401s');
    });
  });

  // -------------------------------------------------------------
  // Fingerprint helpers safety
  // -------------------------------------------------------------
  group('Fingerprint helpers', () {
    testWidgets('key fingerprint is 12 hex chars', (tester) async {
      final key = SecretKey(Uint8List(32));
      final fp = await cryptoFingerprintForKey(key);
      expect(fp.length, 12);
      expect(RegExp(r'^[0-9a-f]{12}$').hasMatch(fp), isTrue,
          reason: 'must be lowercase hex');
    });

    test('salt fingerprint is 12 hex chars', () {
      final salt = base64.encode(Uint8List(16));
      final fp = cryptoFingerprintForSaltBase64(salt);
      expect(fp.length, 12);
      expect(RegExp(r'^[0-9a-f]{12}$').hasMatch(fp), isTrue);
    });

    test('malformed salt does not throw — returns marker', () {
      final fp = cryptoFingerprintForSaltBase64('!!! not base64 !!!');
      expect(fp, 'unavailable');
    });
  });
}
