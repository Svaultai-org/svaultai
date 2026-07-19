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
    test('dashboard "Welcome to …" reads displayUsername, not vaultName',
        () {
      final src = _readLib('main.dart');
      // The old code was:
      //   'Welcome to ${app.vaultName ?? 'your vault'}'
      // The fixed code MUST bind to displayUsername.
      expect(
        src.contains("'Welcome to \${app.displayUsername ?? 'your vault'}'"),
        isTrue,
        reason: 'dashboard greeting must show the friendly username',
      );
      expect(
        src.contains("'Welcome to \${app.vaultName"),
        isFalse,
        reason: 'dashboard greeting must not read vaultName — that '
                'value is the VLT handle for ZK accounts',
      );
    });

    test('drawer header primary label is displayUsername', () {
      final src = _readLib('main.dart');
      // Find the drawer header block by anchoring on the tile list
      // that follows it, then verify the header does not read
      // ``app.vaultName``.
      final drawerIdx = src.indexOf("'vault_drawer_menu_list'");
      expect(drawerIdx, greaterThan(-1));
      // Look back ~1500 chars — the header text is within a few
      // Column children right above the tile list.
      final windowStart = (drawerIdx - 1500).clamp(0, src.length);
      final window = src.substring(windowStart, drawerIdx);
      expect(
        window.contains('app.vaultName ?? '),
        isFalse,
        reason: 'drawer header must not paint the VLT vault handle',
      );
      expect(
        window.contains('app.displayUsername ??'),
        isTrue,
        reason: 'drawer header must surface the friendly username',
      );
    });
  });

  group('AppState identity contract', () {
    test('vaultHandle is a distinct field from vaultName', () {
      final src = _readLib('main.dart');
      // The AppState class declares vaultHandle as its own field —
      // it is NOT an alias for vaultName. Overloading vaultName with
      // both meanings is the root cause of the UI leak.
      expect(src.contains('String? vaultHandle;'), isTrue,
          reason: 'AppState must expose vaultHandle separately from '
                  'vaultName so UI/lookup/cache-key concerns can be '
                  'reasoned about independently');
    });

    test('setSession accepts vaultHandleValue and displayUsernameValue',
        () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> setSession(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
      expect(window.contains('String? vaultHandleValue'), isTrue,
          reason: 'setSession must accept the deterministic handle '
                  'so it can be recovered without another OPAQUE '
                  'round-trip');
      expect(window.contains('String? displayUsernameValue'), isTrue);
      expect(
        window.contains("sp.setString('last_display_username'"),
        isTrue,
        reason: 'the friendly name must persist so hydrate() can '
                'paint it before /auth/me returns',
      );
    });

    test('hydrate reads last_display_username BEFORE calling /auth/me',
        () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> hydrate(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2500).clamp(0, src.length));
      final restoreIdx = window.indexOf("sp.getString('last_display_username')");
      final authMeIdx = window.indexOf('client.authMe(');
      expect(restoreIdx, greaterThan(-1),
          reason: 'hydrate must restore the persisted friendly name '
                  'from SharedPreferences on launch');
      expect(authMeIdx, greaterThan(-1));
      expect(restoreIdx, lessThan(authMeIdx),
          reason: 'the friendly name must be painted BEFORE /auth/me '
                  '— otherwise the first frame flashes the fallback '
                  'label until the network round-trip completes');
    });

    test('hydrate never clobbers displayUsername with vault_name', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> hydrate(');
      final window = src.substring(idx, (idx + 2500).clamp(0, src.length));
      // The old bug: hydrate assigned vault_name to vaultName AND
      // treated display_username as optional; a null response would
      // leave the UI painting vault_name (the VLT handle for ZK).
      // The fix must NOT contain
      //   displayUsername = name.trim();
      // or any pattern that binds the display username to the
      // vault_name response value.
      expect(
        window.contains('displayUsername = name.trim();'),
        isFalse,
        reason: 'hydrate must not overload vault_name into '
                'displayUsername — those are distinct concepts',
      );
    });

    test('clearSession(keepLastVaultName: false) wipes friendly-name hints',
        () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('Future<void> clearSession(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
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
        window.contains("sp.remove('last_vault_handle')"),
        isTrue,
      );
    });
  });

  group('LoginPage preflight validates before touching the network', () {
    test('_submit runs a derivation preflight with typed InvalidUsername '
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
      // copy. If a future refactor puts the raw message back in,
      // this test flips.
      expect(
        window.contains(r"err = 'Login failed. ${msg.replaceFirst"),
        isFalse,
        reason: 'never stringify a raw exception into the user-'
                'visible error message; use a controlled copy so a '
                'bang null does not leak to the user',
      );
      // And the controlled copy MUST be present.
      expect(
        window.contains("'Login failed. Please try again.'"),
        isTrue,
        reason: 'controlled login-failed copy is missing',
      );
    });

    test('failure classification only routes HTTP 401 to legacy fallback',
        () {
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
        window.contains("'Wrong username or PIN.'"),
        isTrue,
        reason: 'controlled unlock-failed copy is missing',
      );
    });
  });

  group('LoginPage prefills the friendly username, not the handle', () {
    test('_autofillCachedHandle reads last_display_username first', () {
      final src = _readLib('main.dart');
      final idx = src.indexOf('_autofillCachedHandle');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2000).clamp(0, src.length));
      final usernameIdx = window.indexOf("'last_display_username'");
      final handleIdx = window.indexOf('readCachedVaultHandle()');
      expect(usernameIdx, greaterThan(-1),
          reason: 'autofill must prefer the persisted friendly '
                  'username so returning users do not see a VLT '
                  'handle in their login form');
      expect(usernameIdx, lessThan(handleIdx),
          reason: 'username must be checked BEFORE the legacy '
                  'cached handle');
    });
  });
}
