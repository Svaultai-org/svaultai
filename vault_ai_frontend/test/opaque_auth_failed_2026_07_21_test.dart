// Regression tests for the a084794 production diagnostic.
//
// Diagnostic tag from production:
//     [zk-login-diag]
//     last_step=post_login_init
//     type=minified:0s
//     head=Null check operator used on a null value
//     top_frame: TypeError: Cannot read properties of undefined
//                (reading 'finishLoginRequest')
//
// Root cause: @serenity-kit/opaque's ``client.finishLogin(...)``
// returns ``undefined`` when the OPAQUE handshake cannot complete
// (wrong PIN, in practice — RFC 9807 forbids the client from
// telling the server that authentication failed, so the library
// silently returns nothing). The Dart wrapper wrapped that
// undefined into a non-nullable extension type; the next getter
// access threw the raw JS TypeError.
//
// Fix:
//   * OpaqueClient.*  null-check the JS return and throw a typed
//     ``OpaqueAuthenticationFailed`` (finishLogin) or
//     ``OpaqueUnavailable`` (start*, finishRegistration).
//   * LoginPage + UnlockPage catch OpaqueAuthenticationFailed and
//     surface "Wrong username or PIN." — NEVER the raw JS
//     TypeError, NEVER a legacy /auth/login retry.
//
// This suite locks the contract with source-scan invariants; the
// JS-side null return can't be reproduced from a pure Dart test
// without stubbing the WASM module.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

// NOTE: opaque_client.dart uses ``dart:js_interop`` and cannot be
// imported into a Dart VM test. Every assertion below is a source-
// scan invariant. The Web build's own compiler is the runtime
// checker: if any of the invariants regresses, ``flutter analyze``
// on ``lib/services/opaque_client.dart`` will surface it and
// ``flutter build web`` will fail.

String _readLib(String path) => File('lib/$path').readAsStringSync();

String _readSvc(String path) => File('lib/services/$path').readAsStringSync();

void main() {
  group('OpaqueAuthenticationFailed is defined and distinct', () {
    test('the class exists in opaque_client.dart', () {
      final src = _readSvc('opaque_client.dart');
      expect(
        src.contains('class OpaqueAuthenticationFailed implements Exception'),
        isTrue,
        reason: 'OpaqueAuthenticationFailed is the typed signal for '
            'a wrong-PIN OPAQUE failure — LoginPage cannot '
            'distinguish it from OpaqueUnavailable without it',
      );
    });

    test('the exception carries a stage tag', () {
      final src = _readSvc('opaque_client.dart');
      final idx = src.indexOf('class OpaqueAuthenticationFailed');
      final window = src.substring(idx, (idx + 800).clamp(0, src.length));
      expect(window.contains('final String stage;'), isTrue);
      // The user-visible message must mention "wrong PIN" so a
      // support engineer reading the log knows the operational
      // meaning without reading RFC 9807.
      expect(
        window.toLowerCase().contains('wrong pin'),
        isTrue,
        reason: 'toString() must mention "wrong PIN" so an operator '
            'reading the diagnostic knows what the OPAQUE '
            'protocol failure means in practice',
      );
    });
  });

  group('OpaqueClient wrappers null-check every JS return', () {
    File _svc() => File('lib/services/opaque_client.dart');

    test('the four external methods are declared nullable', () {
      final src = _svc().readAsStringSync();
      // The JS-interop declarations MUST return ``JSObject?`` so
      // Dart's null-check catches an undefined return before the
      // downstream getter accesses fire a raw TypeError.
      for (final name in const [
        'startRegistration',
        'finishRegistration',
        'startLogin',
        'finishLogin',
      ]) {
        expect(
          src.contains('external JSObject? $name(JSObject params);'),
          isTrue,
          reason: 'external declaration for $name must return '
              'JSObject? — @serenity-kit/opaque returns '
              'undefined on OPAQUE-protocol failure',
        );
      }
    });

    test('every wrapper throws on null return', () {
      final src = _svc().readAsStringSync();
      // Each of the four static wrappers must have an explicit
      // ``if (result == null)`` guard right after the JS call.
      // Counting occurrences is enough — the guards are unique
      // per wrapper.
      final nullGuards = 'if (result == null)'.allMatches(src).length;
      expect(nullGuards, greaterThanOrEqualTo(4),
          reason: 'every JS-interop wrapper must null-check the '
              'return before wrapping it in the extension type');
    });

    test(
        'finishLogin maps a null return to OpaqueAuthenticationFailed, '
        'not OpaqueUnavailable', () {
      final src = _svc().readAsStringSync();
      final idx = src.indexOf('static ClientLoginFinish finishLogin(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 3000).clamp(0, src.length));
      final guardIdx = window.indexOf('if (result == null)');
      expect(guardIdx, greaterThan(-1));
      // Within the guard body, the throw must be
      // OpaqueAuthenticationFailed — a wrong PIN is NOT the same
      // as "the WASM module is missing", and if we conflate them
      // the LoginPage will surface the wrong error copy.
      // Widen the throw window to 1500 — the block contains a
      // multi-line comment explaining the RFC 9807 rationale
      // before the throw itself.
      final throwWindow =
          window.substring(guardIdx, (guardIdx + 1500).clamp(0, window.length));
      expect(
        throwWindow.contains('throw OpaqueAuthenticationFailed'),
        isTrue,
        reason: 'finishLogin must throw OpaqueAuthenticationFailed '
            'when the OPAQUE handshake cannot complete',
      );
    });

    test('startLogin / start* / finishRegistration use OpaqueUnavailable', () {
      // These calls should NEVER return undefined for well-formed
      // inputs — if they do, the WASM bundle is broken and the
      // correct signal is "module unavailable", not "wrong PIN".
      final src = _svc().readAsStringSync();
      for (final wrapper in const [
        'static ClientRegistrationStart startRegistration(',
        'static ClientRegistrationFinish finishRegistration(',
        'static ClientLoginStart startLogin(',
      ]) {
        final idx = src.indexOf(wrapper);
        expect(idx, greaterThan(-1), reason: 'missing wrapper: $wrapper');
        final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
        final guardIdx = window.indexOf('if (result == null)');
        expect(guardIdx, greaterThan(-1), reason: '$wrapper has no null guard');
        final throwWindow = window.substring(
            guardIdx, (guardIdx + 400).clamp(0, window.length));
        expect(
          throwWindow.contains('throw OpaqueUnavailable'),
          isTrue,
          reason: '$wrapper must throw OpaqueUnavailable on null '
              '— it cannot legitimately fail authentication',
        );
      }
    });
  });

  group('LoginPage + UnlockPage catch the typed auth failure', () {
    test(
        'LoginPage catches OpaqueAuthenticationFailed and surfaces '
        '"Wrong username or PIN."', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _LoginPageState');
      final window = src.substring(idx, (idx + 25000).clamp(0, src.length));
      expect(
        window.contains('on OpaqueAuthenticationFailed catch'),
        isTrue,
        reason: 'LoginPage must have a typed catch for the wrong-'
            'PIN signal — otherwise it falls into the generic '
            'catch and the user sees a diagnostic tag instead '
            'of the friendly "Wrong username or PIN." copy',
      );
      // Within THAT catch block, verify the visible copy.
      final catchIdx = window.indexOf('on OpaqueAuthenticationFailed catch');
      final catchBody =
          window.substring(catchIdx, (catchIdx + 1500).clamp(0, window.length));
      expect(
        catchBody.contains("'Wrong username or PIN.'"),
        isTrue,
        reason: 'the OpaqueAuthenticationFailed catch must set the '
            'friendly error copy',
      );
    });

    test(
        'the OpaqueAuthenticationFailed catch does NOT fall through to '
        'legacy /auth/login', () {
      // OPAQUE authentication failure is a definitive wrong-PIN
      // signal. Retrying via the legacy plaintext-verifier path
      // would only expose the same PIN to a timing oracle. The
      // catch must ``return`` immediately.
      final src = _readLib('main.dart');
      final loginPageIdx = src.indexOf('class _LoginPageState');
      final idx = src.indexOf(
        'on OpaqueAuthenticationFailed catch',
        loginPageIdx,
      );
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 1000).clamp(0, src.length));
      // Look for the return statement inside the block.
      final returnIdx = window.indexOf('return;');
      final legacyIdx = window.indexOf('client.authLogin(');
      expect(returnIdx, greaterThan(-1),
          reason: 'the catch must return immediately');
      // legacyIdx being -1 in the 1000-char window means the
      // catch doesn't fall into the legacy fallback below.
      // If legacyIdx were positive AND less than returnIdx, the
      // catch would be broken.
      if (legacyIdx > -1) {
        expect(returnIdx, lessThan(legacyIdx),
            reason: 'the catch must return BEFORE reaching the '
                'legacy /auth/login fallback');
      }
    });

    test('UnlockPage catches OpaqueAuthenticationFailed too', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _UnlockPageState');
      final window = src.substring(idx, (idx + 15000).clamp(0, src.length));
      expect(
        window.contains('on OpaqueAuthenticationFailed catch'),
        isTrue,
        reason: 'UnlockPage must have the same typed catch as '
            'LoginPage — the unlock flow reaches the same '
            'OPAQUE finishLogin call and can fail the same way',
      );
      final catchIdx = window.indexOf('on OpaqueAuthenticationFailed catch');
      final catchBody =
          window.substring(catchIdx, (catchIdx + 1500).clamp(0, window.length));
      expect(catchBody.contains("'Wrong username or PIN.'"), isTrue);
    });
  });
}
