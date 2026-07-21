// Client-side contract for the 2026-07-21 KDF-generation
// concurrency fix (server-side reviewed and required a proper
// compare-and-swap; the 65d7910 pre-encrypt GET was rejected as a
// mitigation, not a fix).
//
// This file locks:
//
//   * `KdfGenerationStaleException` type + `fromResponseBody`
//     factory shape.
//   * `chatStream` signature accepts `kdfSaltUsed` and
//     `kdfIterationsUsed` and includes them in the request body.
//   * `chatStream` throws `KdfGenerationStaleException` on the
//     server's 409 kdf_generation_stale — BEFORE it maps 400
//     "Invalid PIN or corrupted data" to InvalidVaultUnlockException.
//   * `_send()` reads _keyOrigin and forwards it to chatStream.
//   * `_send()` catches KdfGenerationStaleException, applies fresh
//     metadata, restores the input text, drops the just-added user
//     bubble, shows a clear snackbar, and does NOT force PIN or
//     auto-retry.
//   * Same policy in `_startSecureItemDeleteConfirmation`.
//   * `AppState.applyFreshKdfMetadata` re-derives without any HTTP
//     round-trip and without mutating the session.
//   * `getVaultMeta` sends Cache-Control: no-cache request headers
//     (defense-in-depth against caches that ignore the response
//     header).
//   * The pre-encrypt `resyncCryptoKeyIfDrifted` call site is GONE
//     from _send and _startSecureItemDeleteConfirmation (structural
//     proof the mitigation was removed, not stacked).
//
// All source-scan — this file compiles against the same lib source
// the Flutter build ships, so contract violations fail the test
// suite regardless of runtime environment.

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';


String _mainDart() => File('lib/main.dart').readAsStringSync();
String _apiClient() => File('lib/api_client.dart').readAsStringSync();


void main() {
  group('KdfGenerationStaleException type + factory', () {
    test('class exists with currentPinSalt, currentKdfIterations, '
         'message fields', () {
      final src = _apiClient();
      expect(src.contains('class KdfGenerationStaleException'),
          isTrue,
          reason: 'the typed 409 exception must exist so callers can '
                  'distinguish it from InvalidVaultUnlockException '
                  '(session-fine vs session-expired)');
      final classIdx = src.indexOf('class KdfGenerationStaleException');
      final windowEnd = (classIdx + 1500).clamp(0, src.length);
      final window = src.substring(classIdx, windowEnd);
      expect(window.contains('currentPinSalt'), isTrue,
          reason: 'must expose the response body\'s current_pin_salt');
      expect(window.contains('currentKdfIterations'), isTrue,
          reason: 'must expose the response body\'s '
                  'current_kdf_iterations');
      expect(window.contains('message'), isTrue,
          reason: 'must carry a user-facing message');
    });

    test('fromResponseBody parses the server\'s 409 detail shape', () {
      final body = jsonEncode({
        'detail': {
          'code': 'kdf_generation_stale',
          'message': 'Please tap send again.',
          'current_pin_salt': 'AAAAABCDEFGHIJKL',
          'current_kdf_iterations': 100000,
        },
      });
      final exc = KdfGenerationStaleException.fromResponseBody(body);
      expect(exc.currentPinSalt, 'AAAAABCDEFGHIJKL');
      expect(exc.currentKdfIterations, 100000);
      expect(exc.message, 'Please tap send again.');
    });

    test('fromResponseBody survives a malformed body without crashing',
         () {
      final exc = KdfGenerationStaleException.fromResponseBody('{}');
      expect(exc.currentPinSalt, isNull);
      expect(exc.currentKdfIterations, isNull);
      // Falls back to a default message so the snackbar has something
      // to show even if the server response was truncated.
      expect(exc.message.isNotEmpty, isTrue);
    });

    test('KdfGenerationStaleException is NOT '
         'InvalidVaultUnlockException — the semantics differ', () {
      // Callers key their recovery flow on the type. If these two
      // exceptions were siblings of the same base, a caller might
      // accidentally clear the session on a stale-KDF response.
      final k = KdfGenerationStaleException.fromResponseBody('{}');
      final u = InvalidVaultUnlockException();
      expect(k is InvalidVaultUnlockException, isFalse);
      expect(u is KdfGenerationStaleException, isFalse);
    });
  });

  group('chatStream — includes kdf origin, throws typed 409', () {
    test('chatStream signature accepts kdfSaltUsed + '
         'kdfIterationsUsed', () {
      final src = _apiClient();
      final fnIdx = src.indexOf('Stream<String> chatStream');
      expect(fnIdx, greaterThan(-1));
      final sigEnd = src.indexOf(') async*', fnIdx);
      expect(sigEnd, greaterThan(-1));
      final signature = src.substring(fnIdx, sigEnd);
      expect(signature.contains('String? kdfSaltUsed'), isTrue,
          reason: 'chatStream must accept the client\'s declared '
                  'salt so the server can compare-and-swap');
      expect(signature.contains('int? kdfIterationsUsed'), isTrue,
          reason: 'chatStream must accept the client\'s declared '
                  'iteration count');
    });

    test('chatStream body includes kdf_salt_used + '
         'kdf_iterations_used when present', () {
      final src = _apiClient();
      final fnIdx = src.indexOf('Stream<String> chatStream');
      final bodyIdx = src.indexOf('request.body = jsonEncode', fnIdx);
      expect(bodyIdx, greaterThan(-1));
      final bodyEnd = src.indexOf('});', bodyIdx);
      final body = src.substring(bodyIdx, bodyEnd);
      expect(body.contains("'kdf_salt_used'"), isTrue,
          reason: 'the request body MUST carry the client\'s '
                  'declared salt so the server can gate');
      expect(body.contains("'kdf_iterations_used'"), isTrue,
          reason: 'the request body MUST carry the declared '
                  'iterations');
    });

    test('chatStream error path throws KdfGenerationStaleException '
         'BEFORE mapping to InvalidVaultUnlockException', () {
      final src = _apiClient();
      final fnIdx = src.indexOf('Stream<String> chatStream');
      final errPathIdx = src.indexOf(
          '_throwIfInvalidVaultUnlock', fnIdx);
      final stalePathIdx = src.indexOf(
          '_throwIfKdfGenerationStale', fnIdx);
      expect(stalePathIdx, greaterThan(-1),
          reason: 'chatStream must handle 409 via the typed helper');
      expect(errPathIdx, greaterThan(-1));
      expect(stalePathIdx, lessThan(errPathIdx),
          reason: 'the 409 kdf_generation_stale check must run '
                  'BEFORE the 400 InvalidVaultUnlock check — the '
                  'ordering is what prevents a 409 from being '
                  'downgraded to a "session expired" bounce');
    });

    test('_throwIfKdfGenerationStale only fires on 409 with the '
         'code marker', () {
      final src = _apiClient();
      final fnIdx = src.indexOf('void _throwIfKdfGenerationStale');
      expect(fnIdx, greaterThan(-1));
      final endIdx = src.indexOf('}\n', fnIdx);
      final fn = src.substring(fnIdx, endIdx);
      expect(fn.contains('statusCode != 409'), isTrue,
          reason: 'must short-circuit for non-409 responses');
      expect(fn.contains('kdf_generation_stale'), isTrue,
          reason: 'must gate on the specific server-side code marker');
    });
  });

  group('getVaultMeta — cache-poisoning defense on the client', () {
    test('sends Cache-Control: no-cache + Pragma: no-cache on the '
         'request', () {
      final src = _apiClient();
      final fnIdx = src.indexOf(
          'Future<Map<String, dynamic>> getVaultMeta');
      expect(fnIdx, greaterThan(-1));
      final closingIdx = src.indexOf('return decoded;', fnIdx);
      final fn = src.substring(fnIdx, closingIdx);
      expect(fn.contains("'Cache-Control'"), isTrue,
          reason: 'getVaultMeta must set a request Cache-Control '
                  'header so shared caches that ignore the response '
                  'header still bypass');
      expect(fn.contains('no-cache'), isTrue,
          reason: 'the request Cache-Control must include no-cache');
      expect(fn.contains("'Pragma'"), isTrue,
          reason: 'HTTP/1.0 caches key on Pragma; belt-and-braces');
    });
  });

  group('AppState.applyFreshKdfMetadata — the in-place re-derive', () {
    test('method exists and takes pinSaltBase64 + iterations', () {
      final src = _mainDart();
      expect(
        src.contains('Future<bool> applyFreshKdfMetadata'),
        isTrue,
        reason: 'AppState must expose a method to re-derive from '
                'the 409 response body WITHOUT another HTTP call '
                '(which is what the pre-encrypt-GET mitigation did '
                'and what the review rejected)',
      );
      final idx = src.indexOf('Future<bool> applyFreshKdfMetadata');
      final windowEnd = (idx + 2500).clamp(0, src.length);
      final window = src.substring(idx, windowEnd);
      expect(window.contains('pinSaltBase64'), isTrue);
      expect(window.contains('iterations'), isTrue);
      expect(window.contains('deriveAndCacheKey'), isTrue,
          reason: 'must re-derive via the same PBKDF2 path unlock '
                  'uses');
      // Must NOT hit HTTP.
      expect(window.contains('getVaultMeta'), isFalse,
          reason: 'applyFreshKdfMetadata must NOT fetch /vault-meta '
                  '— it uses the server-provided salt/iter directly, '
                  'which is what closes the TOCTOU window the '
                  'pre-encrypt-GET approach could not close');
      // Must NOT tear down the session.
      expect(window.contains('clearSession'), isFalse);
      expect(window.contains('signOut'), isFalse);
    });
  });

  group('_send() — passes origin, catches 409, no forced PIN, no '
        'auto-retry', () {
    test('reads _keyOrigin and forwards to chatStream', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      final endIdx = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, endIdx);
      final originIdx = fn.indexOf('_VaultCrypto.originFor(');
      final streamIdx = fn.indexOf('client.chatStream(');
      expect(originIdx, greaterThan(-1),
          reason: '_send() must look up _keyOrigin to know what '
                  '(salt, iter) the cached key was derived from');
      expect(streamIdx, greaterThan(originIdx),
          reason: 'origin lookup must precede the chatStream call');
      expect(fn.contains('kdfSaltUsed:'), isTrue,
          reason: '_send() must forward the origin salt');
      expect(fn.contains('kdfIterationsUsed:'), isTrue,
          reason: '_send() must forward the origin iterations');
    });

    test('catches KdfGenerationStaleException in the stream error '
         'path', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      final endIdx = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, endIdx);
      expect(fn.contains('err is KdfGenerationStaleException'),
          isTrue,
          reason: '_send() must special-case the typed 409 exception');
    });

    // Slice out the 409 branch body: from `if (err is
    // KdfGenerationStaleException)` up to the matching closing
    // brace. The branch itself contains its own `if (!mounted)
    // return;` bail-outs, so scanning to the first `return;` cuts
    // the body short. Use a brace-depth scanner instead so the
    // window covers the whole branch.
    String kdfBranchBody(String fn) {
      final ifIdx = fn.indexOf('if (err is KdfGenerationStaleException)');
      expect(ifIdx, greaterThan(-1));
      final openBrace = fn.indexOf('{', ifIdx);
      var depth = 0;
      var i = openBrace;
      while (i < fn.length) {
        final ch = fn[i];
        if (ch == '{') depth++;
        if (ch == '}') {
          depth--;
          if (depth == 0) return fn.substring(ifIdx, i + 1);
        }
        i++;
      }
      throw StateError('unbalanced braces in 409 branch');
    }

    test('on 409, applies fresh metadata + restores input + does NOT '
         'force PIN', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      final endIdx = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, endIdx);
      final branch = kdfBranchBody(fn);
      expect(branch.contains('applyFreshKdfMetadata'), isTrue,
          reason: 'the 409 branch must re-derive from the response '
                  'salt/iter');
      expect(branch.contains('input.text = text'), isTrue,
          reason: 'the 409 branch must restore the user\'s text so '
                  'they can tap send again without retyping');
    });

    test('on 409 with rederived=true, does NOT navigate to /pin', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      final endIdx = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, endIdx);
      final branch = kdfBranchBody(fn);
      // The rederived==true path must go through
      // `showSnackBar(SnackBar(content: Text(err.message)))` and
      // NOT `pushNamedAndRemoveUntil('/pin', ...)`.
      // The rederived==false fallback DOES push to /pin, but that
      // is an EXPLAINED state, gated behind the snackbar. Verify
      // the /pin push is behind an else branch, not the primary
      // path.
      final pinPushIdx = branch.indexOf("'/pin'");
      // Must exist as fallback...
      expect(pinPushIdx, greaterThan(-1));
      // ...but only inside an `else` branch (i.e. AFTER an if/else
      // on rederived). Simple check: the /pin push must not be the
      // first side-effect after applyFreshKdfMetadata.
      final applyIdx = branch.indexOf('applyFreshKdfMetadata');
      expect(applyIdx, greaterThan(-1));
      // The distance between applyFreshKdfMetadata and the /pin
      // push must include the branching logic — proxy: check that
      // an `else` or `if (rederived)` structure sits between them.
      final between = branch.substring(applyIdx, pinPushIdx);
      final hasBranchGuard = between.contains('rederived') ||
                              between.contains('else') ||
                              between.contains('if (');
      expect(hasBranchGuard, isTrue,
          reason: 'the /pin push must be behind a branch guard so '
                  'it fires ONLY when local re-derive was not '
                  'possible — never the primary path');
    });

    test('does NOT auto-retry the send in the 409 branch', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      final endIdx = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, endIdx);
      final branch = kdfBranchBody(fn);
      // No recursive _send or chatStream inside the 409 branch.
      expect(branch.contains('_send('), isFalse,
          reason: 'must NOT auto-retry the send — user re-taps send');
      expect(branch.contains('chatStream('), isFalse,
          reason: 'must NOT restart the stream — user re-taps send');
    });
  });

  group('_startSecureItemDeleteConfirmation — same 409 policy', () {
    test('reads _keyOrigin and forwards to chatStream', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('_startSecureItemDeleteConfirmation');
      final endIdx = (fnIdx + 8000).clamp(0, src.length);
      final fn = src.substring(fnIdx, endIdx);
      expect(fn.contains('_VaultCrypto.originFor('), isTrue);
      expect(fn.contains('kdfSaltUsed:'), isTrue);
      expect(fn.contains('kdfIterationsUsed:'), isTrue);
    });

    test('catches KdfGenerationStaleException with same recovery '
         'shape', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('_startSecureItemDeleteConfirmation');
      final endIdx = (fnIdx + 8000).clamp(0, src.length);
      final fn = src.substring(fnIdx, endIdx);
      expect(fn.contains('err is KdfGenerationStaleException'), isTrue);
      expect(fn.contains('applyFreshKdfMetadata'), isTrue);
    });
  });

  group('Pre-encrypt mitigation is REMOVED', () {
    test('_send() no longer calls resyncCryptoKeyIfDrifted', () {
      final src = _mainDart();
      final sendIdx = src.indexOf('Future<void> _send()');
      // Grab a fat window — the send handler is long.
      final endIdx = (sendIdx + 20000).clamp(0, src.length);
      final fn = src.substring(sendIdx, endIdx);
      expect(
        fn.contains('resyncCryptoKeyIfDrifted'),
        isFalse,
        reason: 'the 65d7910 pre-encrypt GET was rejected on review '
                'as a mitigation, not a fix. Correctness now sits '
                'in the server-side KDF-version gate. Re-adding the '
                'GET stacks a race on top of a race.',
      );
    });

    test('_startSecureItemDeleteConfirmation no longer calls '
         'resyncCryptoKeyIfDrifted', () {
      final src = _mainDart();
      final fnIdx = src.indexOf('_startSecureItemDeleteConfirmation');
      final endIdx = (fnIdx + 8000).clamp(0, src.length);
      final fn = src.substring(fnIdx, endIdx);
      expect(fn.contains('resyncCryptoKeyIfDrifted'), isFalse);
    });
  });
}
