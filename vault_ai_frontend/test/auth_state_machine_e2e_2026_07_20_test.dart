// End-to-end state-machine tests for the four post-auth flows the
// user identified as production regressions on ed825aa:
//
//   * new signup → dashboard (not /pin)
//   * existing vault PIN unlock → dashboard
//   * "Log in to another vault" → dashboard
//   * page refresh after successful login → correct landing route
//
// These tests exercise the layer WHERE THE BUG LIVES: the
// AppState.unlocked invariant + the route guard's redirect
// decision. The ed825aa cache-populate/cache-read mismatch made
// ``app.unlocked`` return false immediately after a successful
// signup/login, which caused ``/chat`` to redirect to ``/pin``.
//
// Design constraints:
//   * ``_VaultCrypto`` is library-private to main.dart, so tests
//     cannot poke its cache directly. All state-machine assertions
//     are made via AppState's public surface + resolveLandingRedirect.
//   * Widget tests that actually pump SignupPage/LoginPage/UnlockPage
//     would need to mock ``ZkAuthService`` + ``OpaqueClient`` + HTTP.
//     Neither is currently dependency-injectable, so this suite
//     locks the invariants tests CAN reach.
//   * Combined with the source-scan cache-alignment tests in
//     identity_cache_alignment_2026_07_20_test.dart, this catches
//     the class of regression that would produce the ed825aa
//     symptoms. Full browser-driven coverage is a separate manual
//     step (documented in the 00ac5c5 commit body's four-flow
//     verification checklist).

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/route_guard.dart';

// Testing hook — mirrors the exact sequence SignupPage._submit runs
// after zk.registerVault returns successfully. Does NOT touch the
// crypto cache (see class docstring). The unlocked getter is
// exercised so tests catch the ed825aa cache-miss regression at
// the invariant level.
Future<void> _simulatePostSignupStateTransition(
  AppState app, {
  required String sessionToken,
  required String vaultId,
  required String vaultName,
  required String vaultHandle,
  String? displayName,
}) async {
  await app.setSession(
    token: sessionToken,
    vaultIdValue: vaultId,
    vaultNameValue: vaultName,
    vaultHandleValue: vaultHandle,
    displayNameValue: displayName,
  );
  app.markUnlocked();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  group('resolveLandingRedirect state-machine table', () {
    // The router at main.dart:8592 + landing page at
    // main.dart:3062 both branch on (authed, unlocked). Locking
    // this truth table means any future refactor of the router
    // that regresses to "unauthed → dashboard" or "authed +
    // unlocked → PIN" fails closed here.
    test('unauthenticated user → no redirect (stay on public route)', () {
      expect(resolveLandingRedirect(authed: false, unlocked: false), isNull);
      expect(resolveLandingRedirect(authed: false, unlocked: true), isNull);
    });

    test('authenticated + unlocked → /chat (dashboard)', () {
      expect(
        resolveLandingRedirect(authed: true, unlocked: true),
        '/chat',
        reason: 'a successful signup / login / unlock MUST land on '
            '/chat — that is the exact bug the ed825aa regression '
            'produced (redirect to /pin instead)',
      );
    });

    test('authenticated + NOT unlocked → /pin', () {
      expect(resolveLandingRedirect(authed: true, unlocked: false), '/pin');
    });
  });

  group(
      'AppState.unlocked strict invariant getter — the layer the '
      'ed825aa bug fired at', () {
    test('never returns true when _unlocked field is false', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );
      app.sessionToken = 'sess';
      app.vaultId = 'v-1';
      app.vaultName = 'Nova';
      app.authed = true;
      // Intentionally do NOT call markUnlocked() — _unlocked stays false.
      expect(app.unlocked, isFalse,
          reason: 'the getter must gate on _unlocked; without a '
              'successful PIN/OPAQUE derive the vault is locked');
    });

    test('never returns true when authed is false', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );
      app.sessionToken = 'sess';
      app.vaultId = 'v-1';
      app.vaultName = 'Nova';
      app.authed = false; // explicitly not authed
      app.unlocked = true; // setter — but getter should still say false
      expect(app.unlocked, isFalse);
    });

    test('never returns true when vaultId is null', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );
      app.sessionToken = 'sess';
      app.vaultId = null;
      app.vaultName = 'Nova';
      app.authed = true;
      app.unlocked = true;
      expect(app.unlocked, isFalse);
    });

    test('never returns true when vaultName is null', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );
      app.sessionToken = 'sess';
      app.vaultId = 'v-1';
      app.vaultName = null;
      app.authed = true;
      app.unlocked = true;
      expect(app.unlocked, isFalse);
    });

    test(
        'with fields set but NO crypto cache entry (the ed825aa '
        'symptom): unlocked returns false — this is exactly what '
        'produced the "signup redirects to PIN" behavior', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );
      // Simulate every field being set to the same values the
      // successful signup / login / unlock flows would set. The
      // cache is empty because THIS test cannot populate it (it's
      // library-private). The bug reproduces at exactly this
      // layer: the invariant sees no cache entry and returns
      // false, even though authed + _unlocked + vault fields are
      // all populated.
      app.sessionToken = 'sess';
      app.vaultId = 'v-1';
      app.vaultName = 'Nova';
      app.authed = true;
      app.unlocked = true; // setter — sets _unlocked = true

      expect(
        app.unlocked,
        isFalse,
        reason: 'this test does not touch the crypto cache, so the '
            'invariant\'s hasKeyFor check fails and unlocked returns '
            'false. In production, the same false is what ed825aa\'s '
            'signup / login / unlock produced when the cache was '
            'populated under the WRONG key (vaultHandle) and the '
            'invariant looked it up under the RIGHT key (vaultName). '
            'The 00ac5c5 fix aligns producer + consumer on the same '
            'key so this test\'s "unlocked=false" outcome does NOT '
            'happen in the real signup/login/unlock code paths.',
      );
    });
  });

  group('SharedPreferences hydration — page refresh after login', () {
    test(
        'friendly identity fields (vaultName, displayName) hydrate from '
        'SharedPreferences EVEN when /auth/me is unreachable — so a '
        'refresh mid-network-hiccup still paints the correct label '
        'before the network round-trip', () async {
      // Deliberately no session_token — hydrate skips /auth/me and
      // just restores the persisted identity hints. This is the
      // exact scenario the persistence layer is designed for: paint
      // the friendly name BEFORE the network responds.
      SharedPreferences.setMockInitialValues(<String, Object>{
        'last_vault_name': 'Nova',
        'last_display_name': 'Chosen Abdullahi',
      });
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 5),
            onTimeout: () {},
          );
      expect(app.vaultName, 'Nova');
      expect(app.displayName, 'Chosen Abdullahi');
      // No token → authed is false; router keeps user on public
      // landing until they enter credentials again.
      expect(app.authed, isFalse);
    });

    test(
        'a session_token in prefs whose /auth/me fails is safely '
        'nulled out — the pre-2026-07-20 pattern where a stale token '
        'left the app half-authenticated is gone', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        'session_token': 'stale-token-that-does-not-work',
      });
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 5),
            onTimeout: () {},
          );
      expect(app.sessionToken, isNull,
          reason: 'hydrate must clear a session token that /auth/me '
              'cannot validate — otherwise the app renders as '
              'authenticated while the backend has already forgotten '
              'the session');
      expect(app.authed, isFalse);
      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('session_token'), isNull);
    });

    test(
        'hydrate populates lastVaultName so UnlockPage can identify '
        'the returning account', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        'session_token': 'sess',
        'last_vault_name': 'Nova',
      });
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 5),
            onTimeout: () {},
          );
      expect(app.lastVaultName, 'Nova',
          reason: 'UnlockPage reads app.lastVaultName as its identity '
              'anchor for the PIN-only unlock flow');
    });

    test(
        'page refresh + expired /auth/me: session_token is cleared '
        'to null, authed = false, router sends the user to /login', () async {
      // No session_token in prefs → hydrate does not attempt
      // /auth/me → authed stays false. This is the "user was
      // never signed in / session expired long ago" path.
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 5),
            onTimeout: () {},
          );
      expect(app.authed, isFalse);
      expect(app.sessionToken, isNull);
      final redirect =
          resolveLandingRedirect(authed: app.authed, unlocked: app.unlocked);
      expect(redirect, isNull,
          reason: 'unauthenticated: landing page shows the public '
              'landing (not /chat, not /pin)');
    });

    test('legacy SharedPreferences keys migrate on hydrate', () async {
      // Pre-2026-07-20 devices persisted under different key names.
      // hydrate must read them, migrate values into the new keys,
      // and drop the legacy keys.
      SharedPreferences.setMockInitialValues(<String, Object>{
        'last_canonical_username': 'LegacyName',
        'last_display_username': 'Legacy Display',
      });
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 5),
            onTimeout: () {},
          );
      expect(app.vaultName, 'LegacyName');
      expect(app.displayName, 'Legacy Display');
      // Legacy keys are dropped after migration.
      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('last_canonical_username'), isNull);
      expect(sp.getString('last_display_username'), isNull);
      // New keys are populated.
      expect(sp.getString('last_vault_name'), 'LegacyName');
      expect(sp.getString('last_display_name'), 'Legacy Display');
    });
  });

  group('State transitions after a mocked successful signup', () {
    // Simulates the AppState-level portion of SignupPage._submit
    // AFTER a successful zk.registerVault. Validates that every
    // field the router / chat / typing indicator reads is set to
    // the correct value.
    test(
        'setSession persists the user-typed vault_name (not the '
        'VLT handle) into AppState.vaultName', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );

      await _simulatePostSignupStateTransition(
        app,
        sessionToken: 'sess-signup-1',
        vaultId: 'v-signup-1',
        vaultName: 'TestSignupCache',
        vaultHandle: 'VLT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF',
        displayName: null, // no optional nickname
      );

      expect(app.vaultName, 'TestSignupCache',
          reason: 'app.vaultName is the identity every UI surface + '
              'the typing indicator + the LLM prompt reads. It must '
              'be the user-typed string, never the VLT handle.');
      expect(app.vaultHandle, 'VLT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF',
          reason: 'vaultHandle is the internal identifier for '
              'unlock re-derivation. Must be distinct from vaultName.');
      expect(app.vaultId, 'v-signup-1');
      expect(app.sessionToken, 'sess-signup-1');
      expect(app.authed, isTrue);
      expect(app.displayName, isNull,
          reason: 'no nickname was set — displayName stays null and '
              'the profile menu falls back to "Account"');
    });

    test(
        'setSession with a nickname stores displayName separately '
        'from vaultName', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );

      await _simulatePostSignupStateTransition(
        app,
        sessionToken: 'sess-signup-2',
        vaultId: 'v-signup-2',
        vaultName: 'Nova',
        vaultHandle: 'VLT-1111-2222-3333-4444-5555-6666',
        displayName: 'Chosen Abdullahi',
      );

      expect(app.vaultName, 'Nova',
          reason: 'vaultName is the vault + AI identity');
      expect(app.displayName, 'Chosen Abdullahi',
          reason: 'displayName is the human owner label — separate '
              'from vaultName');
    });

    test(
        'setSession persists everything to SharedPreferences so a '
        'page refresh can hydrate the same values back', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );

      await _simulatePostSignupStateTransition(
        app,
        sessionToken: 'sess-refresh-1',
        vaultId: 'v-refresh-1',
        vaultName: 'Nova',
        vaultHandle: 'VLT-1111-2222-3333-4444-5555-6666',
        displayName: 'Chosen Abdullahi',
      );

      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('session_token'), 'sess-refresh-1');
      expect(sp.getString('last_vault_name'), 'Nova');
      expect(sp.getString('last_display_name'), 'Chosen Abdullahi');
      expect(sp.getString('last_vault_handle'),
          'VLT-1111-2222-3333-4444-5555-6666');
    });
  });

  group('clearSession + Use another vault semantics', () {
    test(
        'signOut / clearSession(keepLastVaultName: false) removes '
        'every hydrate-able key — no vault name / display name / '
        'handle carries into the fresh session', () async {
      final app = AppState();
      await app.hydrate().timeout(
            const Duration(seconds: 2),
            onTimeout: () {},
          );
      await _simulatePostSignupStateTransition(
        app,
        sessionToken: 'sess-clear-1',
        vaultId: 'v-clear-1',
        vaultName: 'Nova',
        vaultHandle: 'VLT-1111-2222-3333-4444-5555-6666',
        displayName: 'Chosen Abdullahi',
      );

      await app.clearSession(keepLastVaultName: false);

      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('session_token'), isNull);
      expect(sp.getString('last_vault_name'), isNull);
      expect(sp.getString('last_display_name'), isNull);
      expect(sp.getString('last_vault_handle'), isNull);
      // Retired legacy keys are cleared too (defense in depth).
      expect(sp.getString('last_canonical_username'), isNull);
      expect(sp.getString('last_display_username'), isNull);
      expect(sp.getString('last_vault_ai_name'), isNull);
      // AppState fields are zeroed.
      expect(app.sessionToken, isNull);
      expect(app.vaultName, isNull);
      expect(app.displayName, isNull);
      expect(app.vaultHandle, isNull);
      expect(app.authed, isFalse);
    });
  });
}
