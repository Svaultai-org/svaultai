// Corrective-release regression tests (2026-07-20).
//
// Two production symptoms in the 492a6e0 build:
//
//   1. Dashboard and drawer painted the internal VLT-* vault handle
//      as the user's account name.
//   2. Logging back in with username + PIN surfaced a raw Dart
//      exception ("Login failed. Null check operator used on a null
//      value") because a bang somewhere in the ZK login pipeline
//      blew up and the outer catch stringified it verbatim.
//
// The fix separates the state contract — displayUsername (UI),
// vaultHandle (backend lookup), vaultName (legacy compat) — and
// wraps every login/unlock exit path in controlled error copy plus
// diagnostic vlogs.
//
// This suite locks the pieces the widget tree can reason about
// without a live backend: source-scan invariants for the UI
// bindings, the preflight validation shape, the persisted hint
// keys, and the controlled-error copy that must survive future
// refactors.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readLib(String path) => File('lib/$path').readAsStringSync();

void main() {
  group('UI never surfaces the internal VLT vault handle', () {
    test(
        'dashboard welcome greets with displayName (not vault_name, '
        'never the VLT handle) — updated 2026-07-21 (c2f917e)', () {
      final src = _readLib('main.dart');
      // 2026-07-21 UPDATE: production feedback said greeting users
      // with their vault_name ("Welcome to Yola") looks like the
      // app is greeting the vault, not the person. The welcome
      // heading now uses displayName as the visible name and falls
      // back to a neutral "Welcome to your vault" when there is no
      // displayName. vault_name remains the LOGIN + AI identity —
      // just never the visible greeting.
      expect(src.contains('app.vaultName'), isTrue,
          reason: 'vaultName remains referenced elsewhere for '
              'login/AI identity — sanity check');
      // The welcome heading itself no longer reads vault_name.
      expect(
        src.contains(
          "'Welcome to \${app.vaultName ?? app.displayName ?? 'your vault'}'",
        ),
        isFalse,
        reason: 'the OLD "Welcome to \${vaultName …}" interpolation '
            'must be gone — greet by displayName instead',
      );
      // New shape: neutral "Welcome to your vault" fallback string
      // appears in the source AND the greeting reads displayName.
      expect(
        src.contains("'Welcome to your vault'"),
        isTrue,
        reason: 'neutral fallback string must exist for the null-'
            'displayName case',
      );
      expect(
        src.contains("'Welcome, \$name'"),
        isTrue,
        reason: 'the primary greeting must be "Welcome, <displayName>"',
      );
    });

    test(
        'drawer header reads displayName only, never vault_name '
        '(updated 2026-07-21 c2f917e follow-up)', () {
      final src = _readLib('main.dart');
      final drawerIdx = src.indexOf("'vault_drawer_menu_list'");
      expect(drawerIdx, greaterThan(-1));
      final windowStart = (drawerIdx - 1500).clamp(0, src.length);
      final window = src.substring(windowStart, drawerIdx);
      // 2026-07-21 UPDATE (from earlier "vaultName ?? displayName"
      // contract): production users reported seeing the internal
      // vault_name ("Yola") in the drawer. The user policy is now
      // that vault_name is INTERNAL only — the drawer header (and
      // every other normal-UI surface) must use display_name with a
      // neutral 'Vault' fallback.
      expect(
        window.contains('app.vaultName ?? app.displayName ??'),
        isFalse,
        reason: 'the OLD vaultName-first shape must be gone — the '
            'drawer header must read displayName with a neutral '
            'fallback, never surface vault_name',
      );
      expect(window.contains('app.displayName'), isTrue,
          reason: 'drawer header must interpolate app.displayName');
      // Retired identifier — must not resurface.
      expect(window.contains('app.canonicalUsername'), isFalse);
    });
  });

  group('AppState identity contract', () {
    test('vaultHandle is a distinct field from vaultName', () {
      final src = _readLib('main.dart');
      expect(src.contains('String? vaultHandle;'), isTrue);
    });

    test('setSession accepts vaultHandleValue and displayNameValue', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> setSession(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
      expect(window.contains('String? vaultHandleValue'), isTrue);
      expect(window.contains('String? displayNameValue'), isTrue);
      expect(
        window.contains("NativeSecureStore.writeString") &&
            window.contains("'last_display_name'"),
        isTrue,
        reason: 'displayName must persist so hydrate() can paint '
            'the profile menu before /auth/me returns',
      );
    });

    test(
        'hydrate consults the new persisted keys AND the '
        'legacy fallbacks so existing users\' names survive', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> hydrate(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 3500).clamp(0, src.length));
      final restoreIdx =
          window.indexOf("NativeSecureStore.readString('last_display_name')");
      final legacyIdx = window.indexOf("sp.getString('last_display_username')");
      final authMeIdx = window.indexOf('client.authMe(');
      expect(restoreIdx, greaterThan(-1),
          reason: 'hydrate must restore the new displayName key');
      expect(legacyIdx, greaterThan(-1),
          reason: 'legacy last_display_username key must be readable '
              'as a fallback for one-time migration');
      expect(authMeIdx, greaterThan(-1));
      expect(restoreIdx, lessThan(authMeIdx),
          reason: 'friendly-name paint must precede the /auth/me '
              'round-trip');
    });

    test('hydrate never clobbers displayName with vault_name', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> hydrate(');
      final window = src.substring(idx, (idx + 3500).clamp(0, src.length));
      // The retired vault_name-clobbers-display pattern must be
      // gone; displayName is only assigned from display_username
      // (legacy) or the persisted key.
      expect(window.contains('displayName = name.trim();'), isFalse);
    });

    test('clearSession(keepLastVaultName: false) wipes friendly-name hints',
        () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> clearSession(');
      expect(idx, greaterThan(-1));
      // Window widened 2026-07-20: clearSession now also clears the
      // canonical username slot, so more lines live between the
      // function head and the last relevant remove(). 4000 chars is
      // comfortably above the current function size.
      final window = src.substring(idx, (idx + 4000).clamp(0, src.length));
      // "Use another vault" MUST drop last_display_username so the
      // fresh /login page starts blank instead of pre-filling the
      // previous user.
      expect(
        window.contains("sp.remove('last_display_username')"),
        isTrue,
        reason: 'use-another-vault must clear the persisted friendly '
            'name — a leftover would prefill the wrong user',
      );
      expect(
        window.contains("NativeSecureStore.deleteString('last_vault_handle')"),
        isTrue,
      );
      expect(
        window.contains("sp.remove('last_canonical_username')"),
        isTrue,
        reason: 'use-another-vault must also clear the canonical '
            'username so the previous badge does not carry over',
      );
    });
  });

  group('LoginPage preflight validates before touching the network', () {
    test(
        '_submit runs a derivation preflight with typed InvalidUsername '
        'catches before any HTTP call', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _LoginPageState');
      final window = src.substring(idx, (idx + 25000).clamp(0, src.length));
      // The preflight block must appear BEFORE the ZK attempt.
      final preflightIdx = window.indexOf("login.preflight.ok");
      final zkAttemptIdx = window.indexOf('zk.loginVault(');
      expect(preflightIdx, greaterThan(-1),
          reason: 'preflight vlog must exist and be emitted before '
              'any HTTP call, so production logs can pinpoint '
              'a derivation failure without a wire trace');
      expect(preflightIdx, lessThan(zkAttemptIdx),
          reason: 'preflight must run BEFORE the ZK login attempt');
      // The preflight must catch the two typed exceptions the
      // derivation can raise, plus a defensive catch-all — none of
      // those must reach the outer error path where a raw
      // NullCheckError could be stringified for the user.
      expect(window.contains('on vh.InvalidUsername'), isTrue,
          reason: 'derivation must catch InvalidUsername');
      expect(window.contains('on vh.InvalidVaultHandle'), isTrue,
          reason: 'derivation must catch InvalidVaultHandle');
    });

    test('the ZK catch never displays the raw Dart exception', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _LoginPageState');
      final window = src.substring(idx, (idx + 25000).clamp(0, src.length));
      // The literal error copy the pre-2026-07-20 build produced
      // ("Null check operator…") came from stringifying `msg` into
      // the user-visible error. The fixed code uses a controlled
      // copy PLUS a diagnostic step + exception-class tag. If a
      // future refactor puts the raw ``.toString()`` back in, this
      // test flips.
      expect(
        window.contains(r"err = 'Login failed. ${msg.replaceFirst"),
        isFalse,
        reason: 'never stringify a raw exception into the user-'
            'visible error message; use a controlled copy so a '
            'bang null does not leak to the user',
      );
      // The controlled copy carries the diagnostic tag so operators
      // can see WHICH step threw.
      expect(
        window.contains('kAuthDeviceSafeError'),
        isTrue,
        reason: 'controlled login-failed copy is missing',
      );
      expect(
        window.contains(r'[diagnostic: step=$loginLastStep, type=$typeName]'),
        isFalse,
        reason: 'diagnostic details must not be exposed in UI copy',
      );
    });

    test('LoginPage passes onStep into zk.loginVault and records last step',
        () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _LoginPageState');
      final window = src.substring(idx, (idx + 25000).clamp(0, src.length));
      // The step tracker is a plain local that mutates as each
      // pipeline step completes. If a future refactor drops the
      // onStep hook, we lose the ability to pinpoint pre-HTTP
      // failures from production logs.
      expect(
        window.contains('String loginLastStep ='),
        isTrue,
        reason: 'LoginPage must track the last completed login step',
      );
      expect(
        window.contains('onStep: (s) => loginLastStep = s'),
        isTrue,
        reason: 'LoginPage must pass onStep into zk.loginVault so '
            'the step tracker gets updated as the ZK pipeline '
            'progresses',
      );
    });

    test(
        'LoginPage emits an unconditional console diagnostic on ZK '
        'failure (fires in release builds)', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _LoginPageState');
      final window = src.substring(idx, (idx + 25000).clamp(0, src.length));
      // ``print`` fires in release builds too (unlike ``vlog``
      // which is stripped by kReleaseMode). The tag is greppable
      // in DevTools without a debug build.
      expect(
        window.contains('[zk-login-diag]'),
        isTrue,
        reason: 'LoginPage must print a diagnostic line to the '
            'browser console on ZK failure so production '
            'operators can pinpoint the throwing step',
      );
    });

    test('failure classification only routes HTTP 401 to legacy fallback', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('class _LoginPageState');
      final window = src.substring(idx, (idx + 25000).clamp(0, src.length));
      // The classifier must NOT treat every exception as a "not-found"
      // — that would silently retry legacy authLogin for a bang null
      // and hide the real problem. Look for the explicit boolean.
      expect(
        window.contains("looksLikeAuth401"),
        isTrue,
        reason: 'the ZK-vs-legacy classifier must be an explicit '
            'boolean, not an ad-hoc string match — this makes '
            'the intent obvious to reviewers',
      );
    });
  });

  group('UnlockPage never surfaces raw Dart exceptions either', () {
    test('UnlockPage catch-all uses controlled copy', () {
      final src = _readLib('main.dart');
      final startIdx = src.indexOf('class _UnlockPageState');
      expect(startIdx, greaterThan(-1));
      // Stop the search at the "Use another vault" helper — that's
      // the last thing inside _submit; the sign-up page's own error
      // stringifier lives BEFORE _UnlockPageState in the file and
      // must not be picked up here.
      final endIdx = src.indexOf('_useAnotherVault', startIdx);
      expect(endIdx, greaterThan(startIdx));
      final window = src.substring(startIdx, endIdx);
      // Same regression guard as the LoginPage version.
      expect(
        window.contains(r"err = e.toString().replaceFirst('Exception: ', '')"),
        isFalse,
        reason: 'UnlockPage must not stringify a raw exception into '
            'the user-visible error message',
      );
      expect(
        window.contains('kUnlockDeviceSafeError'),
        isTrue,
        reason: 'controlled unlock-failed copy is missing',
      );
      // Same diagnostic contract as LoginPage — the UnlockPage error
      // string must expose the step + exception class so a wrong-
      // PIN attempt and a bang-null crash look different in a
      // screenshot.
      expect(
        window.contains(r'[diagnostic: step=$unlockLastStep, type=$typeName]'),
        isFalse,
        reason: 'UnlockPage diagnostic details must stay out of UI copy',
      );
      expect(
        window.contains('[zk-unlock-diag]'),
        isTrue,
        reason: 'UnlockPage must print a diagnostic line to the '
            'browser console on ZK failure',
      );
    });
  });

  group('zk_auth_service loginVault emits step-tag beacons', () {
    File _svc() => File('lib/services/zk_auth_service.dart');

    test('loginVault accepts an onStep callback', () {
      final src = _svc().readAsStringSync();
      expect(
        src.contains('void Function(String stepDone)? onStep'),
        isTrue,
        reason: 'loginVault must accept an onStep callback so a '
            'LoginPage-side tracker can pinpoint the failing '
            'step from production logs',
      );
    });

    test('loginVault emits static step beacons for safe diagnostics', () {
      final src = _svc().readAsStringSync();
      // The [zk-login-step] tag is what an operator greps for in
      // the browser DevTools console when a login fails without
      // an HTTP request reaching the backend.
      expect(
        src.contains('[zk-login-step]'),
        isTrue,
        reason: 'loginVault must emit console-visible step beacons '
            'in release builds too — vlog() is silenced by '
            'kReleaseMode and cannot be used here',
      );
      // Sanity-check the exact steps we depend on in the test
      // above about page-side tracking. If a step name is renamed
      // without updating the operator runbook, this test flips.
      for (final s in const [
        'opaque_ready',
        'derive_handle',
        'opaque_start_login',
        'post_login_init',
        'opaque_finish_login',
        'post_login_finalize',
      ]) {
        expect(
          src.contains("'$s'"),
          isTrue,
          reason: 'the pipeline step "$s" is missing from '
              'loginVault — production diagnostics depend on '
              'this exact name',
        );
      }
    });

    test('loginVault never logs the pin, password, or ciphertext', () {
      final src = _svc().readAsStringSync();
      // Grep the print() lines specifically. If a future refactor
      // adds `print('... pin=$pin ...')` this test flips.
      final printLines =
          src.split('\n').where((ln) => ln.contains('print(')).toList();
      expect(printLines, isNotEmpty,
          reason: 'expected at least one print() call for the '
              'step beacons');
      for (final ln in printLines) {
        expect(ln.contains(r'$pin'), isFalse, reason: 'never log the PIN: $ln');
        expect(ln.contains(r'$password'), isFalse,
            reason: 'never log the password: $ln');
        expect(ln.contains(r'$wrappedMvk'), isFalse,
            reason: 'never log wrapped MVK bytes: $ln');
        expect(ln.contains(r'$ke1'), isFalse,
            reason: 'never log OPAQUE ke1 bytes: $ln');
      }
    });
  });

  group('LoginPage prefills the friendly username, not the handle', () {
    test('_autofillCachedHandle never assigns the cached handle', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('_autofillCachedHandle');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
      expect(window, contains('userFacingVaultNameOrNull'));
      expect(window, isNot(contains('readCachedVaultHandle()')),
          reason: 'an internal handle may support private auth '
              'rehydration but must never initialize the visible field');
      expect(window, isNot(contains('vaultNameCtrl.text = cached')));
    });
  });
}
