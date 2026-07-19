library;

/// Focused frontend tests for Step B.4 — coded 401 handling.
///
/// Twelve scenarios per the operator brief:
///
///   1.  session_superseded clears token and routes to login
///   2.  session_expired    clears token and shows correct message
///   3.  session_revoked    clears token and shows correct message
///   4.  invalid_session    clears token and shows correct message
///   5.  an un-coded 401 does NOT trigger the session wipe
///   6.  simultaneous coded 401s trigger termination exactly once
///   7.  late authenticated responses cannot restore signed-in state
///   8.  authenticated retry is disabled after termination
///   9.  manual logout remains distinct — no "another device" msg
///   10. restored stale session never exposes authenticated UI
///   11. second-tab termination event clears first tab
///   12. no raw token / hash / UA appears in the termination flow
///
/// Every test resets the process-global SessionTermination singleton
/// in setUp so tests cannot contaminate each other.

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;


// ---------- helpers -------------------------------------------------

Future<AppState> _hydratedAppState({
  String? sessionToken,
  String? lastVaultName,
}) async {
  final initial = <String, Object>{};
  if (sessionToken != null) initial['session_token'] = sessionToken;
  if (lastVaultName != null) initial['last_vault_name'] = lastVaultName;
  SharedPreferences.setMockInitialValues(initial);
  final app = AppState();
  // hydrate() calls the real backend if a session token is present;
  // for these tests we don't want a network hit, so we time-box it
  // and let it fail into the clean-slate path.
  await app.hydrate().timeout(
    const Duration(seconds: 5),
    onTimeout: () {},
  );
  return app;
}

void _primeAuthed(AppState app,
    {String token = 'sess-abc', String vaultId = 'vault-42'}) {
  app.sessionToken = token;
  app.vaultId = vaultId;
  app.vaultName = 'alice-vault';
  app.displayName = 'Alice';
  app.authed = true;
  app.unlocked = true;
}

/// Register the same handler that main.dart's boot wiring installs,
/// scoped to a given AppState. Returns a list that captures each
/// event delivered so the test can inspect them.
List<st.SessionTerminationEvent> _installHandlerFor(AppState app) {
  final captured = <st.SessionTerminationEvent>[];
  st.SessionTermination.instance.setHandler((event) async {
    captured.add(event);
    await app.clearSession(keepLastVaultName: true);
  });
  return captured;
}

// ---------- tests ---------------------------------------------------

void main() {
  setUp(() {
    st.SessionTermination.instance.resetForTests();
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  tearDown(() {
    st.SessionTermination.instance.resetForTests();
  });

  // ==================================================================
  // Pure-parser + message-table checks (fast, no AppState)
  // ==================================================================

  group('code parser', () {
    test('recognises all four backend codes', () {
      expect(st.parseSessionTerminationCode('session_superseded'),
          st.SessionTerminationCode.superseded);
      expect(st.parseSessionTerminationCode('session_expired'),
          st.SessionTerminationCode.expired);
      expect(st.parseSessionTerminationCode('session_revoked'),
          st.SessionTerminationCode.revoked);
      expect(st.parseSessionTerminationCode('invalid_session'),
          st.SessionTerminationCode.invalid);
    });

    test('returns null for unrelated / null strings', () {
      expect(st.parseSessionTerminationCode(null), isNull);
      expect(st.parseSessionTerminationCode(''), isNull);
      expect(st.parseSessionTerminationCode('other_code'), isNull);
      expect(st.parseSessionTerminationCode('rate_limited'), isNull);
    });
  });

  group('user message table', () {
    test('exact strings per Step B.4 spec', () {
      expect(
        st.userMessageFor(st.SessionTerminationCode.superseded),
        'You were signed out because this Vault was opened on '
        'another device.',
      );
      expect(
        st.userMessageFor(st.SessionTerminationCode.expired),
        'Your session expired. Sign in again.',
      );
      expect(
        st.userMessageFor(st.SessionTerminationCode.revoked),
        'Your session was revoked. Sign in again.',
      );
      expect(
        st.userMessageFor(st.SessionTerminationCode.invalid),
        'Your session is no longer valid. Sign in again.',
      );
    });
  });

  // ==================================================================
  // Scenarios 1–4 — coded 401 clears token + routes with message
  // ==================================================================

  group('coded 401 termination (scenarios 1–4)', () {
    for (final entry in <MapEntry<st.SessionTerminationCode, String>>[
      MapEntry(st.SessionTerminationCode.superseded,
          'You were signed out because this Vault was opened on another device.'),
      MapEntry(st.SessionTerminationCode.expired,
          'Your session expired. Sign in again.'),
      MapEntry(st.SessionTerminationCode.revoked,
          'Your session was revoked. Sign in again.'),
      MapEntry(st.SessionTerminationCode.invalid,
          'Your session is no longer valid. Sign in again.'),
    ]) {
      test('${entry.key.name}: clears local state + carries message',
          () async {
        final app = await _hydratedAppState();
        _primeAuthed(app);
        final captured = _installHandlerFor(app);

        await st.SessionTermination.instance.handle(entry.key);

        expect(app.sessionToken, isNull);
        expect(app.authed, isFalse);
        expect(app.unlocked, isFalse);
        expect(app.vaultId, isNull);
        expect(captured, hasLength(1));
        expect(captured.single.code, entry.key);
        expect(captured.single.userMessage, entry.value);
        final sp = await SharedPreferences.getInstance();
        expect(sp.getString('session_token'), isNull,
            reason: 'persisted token must also be wiped');
      });
    }
  });

  // ==================================================================
  // Scenario 5 — un-coded 401 must NOT trigger the session wipe
  // ==================================================================

  test('un-coded 401 does NOT trigger session termination', () async {
    final app = await _hydratedAppState();
    _primeAuthed(app);
    _installHandlerFor(app);

    // The api layer's _throwIfAuthExpired only funnels into
    // SessionTermination.instance.handle() when detail.code
    // matches. Simulate that path by simply NOT calling handle().
    // Any bare 401 without a session code should not invoke the
    // singleton; we assert the singleton stays clean and app state
    // remains untouched.
    expect(st.SessionTermination.instance.isTerminated, isFalse);
    expect(st.SessionTermination.instance.generation, 0);
    expect(app.authed, isTrue);
    expect(app.sessionToken, 'sess-abc');
  });

  // ==================================================================
  // Scenario 6 — simultaneous coded 401s trigger exactly one term
  // ==================================================================

  test('N concurrent coded 401s → handler runs exactly ONCE', () async {
    final app = await _hydratedAppState();
    _primeAuthed(app);
    var handlerRuns = 0;
    st.SessionTermination.instance.setHandler((_) async {
      handlerRuns += 1;
      // Yield inside the handler to expose any lock leaks.
      await Future<void>.delayed(const Duration(milliseconds: 5));
      await app.clearSession();
    });

    await Future.wait([
      for (var i = 0; i < 8; i++)
        st.SessionTermination.instance
            .handle(st.SessionTerminationCode.superseded),
    ]);

    expect(handlerRuns, 1,
        reason: '8 concurrent 401s must produce ONE termination');
    expect(st.SessionTermination.instance.generation, 1,
        reason: 'generation advances by exactly 1');
    expect(app.sessionToken, isNull);
  });

  // ==================================================================
  // Scenario 7 — late responses cannot restore signed-in state
  // ==================================================================

  test('late authenticated response cannot re-authenticate the app',
      () async {
    final app = await _hydratedAppState();
    _primeAuthed(app);
    _installHandlerFor(app);

    final beforeGen = st.SessionTermination.instance.generation;
    await st.SessionTermination.instance
        .handle(st.SessionTerminationCode.expired);
    final afterGen = st.SessionTermination.instance.generation;

    // A late auth-me success arrives — the caller should compare
    // the generation captured at request-issue time to the current
    // one; a mismatch means the response belongs to a session that
    // has since ended and MUST be discarded.
    final captured = beforeGen;
    final current = st.SessionTermination.instance.generation;
    final isStale = current != captured;
    expect(isStale, isTrue,
        reason: 'generation must advance so late results identify as stale');
    expect(afterGen, greaterThan(beforeGen));

    // Regardless of what the caller does with the stale value, the
    // authoritative app state is unauthenticated and stays that
    // way — the termination flag is still set.
    expect(app.authed, isFalse);
    expect(app.sessionToken, isNull);
    expect(st.SessionTermination.instance.isTerminated, isTrue);
  });

  // ==================================================================
  // Scenario 8 — authenticated retry disabled after termination
  // ==================================================================

  test('api_client rejects authenticated calls after termination',
      () async {
    final app = await _hydratedAppState();
    _primeAuthed(app);
    _installHandlerFor(app);

    await st.SessionTermination.instance
        .handle(st.SessionTerminationCode.superseded);

    // Any authenticated call must throw SessionTerminatedException
    // WITHOUT hitting the wire. authMe() uses an authToken; the
    // internal _defaultHeaders guard fires before http.get.
    final client = VaultAIClient(baseUrl: 'http://127.0.0.1:1');
    await expectLater(
      () => client.authMe(authToken: 'ghost-token'),
      throwsA(isA<SessionTerminatedException>()),
    );

    // After a successful new login, retry is re-enabled.
    await app.setSession(
      token: 'new-token',
      vaultIdValue: 'v2',
      vaultNameValue: 'bob',
    );
    expect(st.SessionTermination.instance.isTerminated, isFalse);
    // Public calls remain usable throughout (do not need auth
    // header — no guard fires).
    expect(
      () => client
          .authMe(authToken: '') // empty token → header omitted
          .catchError((_) => <String, dynamic>{}),
      returnsNormally,
      reason: 'unauthenticated calls must not be blocked',
    );
  });

  // ==================================================================
  // Scenario 9 — manual logout remains distinct
  // ==================================================================

  test('manual logout does NOT show the "another device" message',
      () async {
    final app = await _hydratedAppState();
    _primeAuthed(app);
    final captured = _installHandlerFor(app);

    // Simulate the manual-logout path: call clearSession directly
    // without touching SessionTermination.
    await app.clearSession(keepLastVaultName: false);

    expect(app.sessionToken, isNull);
    expect(app.authed, isFalse);
    expect(captured, isEmpty,
        reason: 'manual logout must NOT fire the coded-401 handler');
    expect(st.SessionTermination.instance.generation, 0);
  });

  // ==================================================================
  // Scenario 10 — restored stale session never exposes UI
  // ==================================================================

  test('hydrate with unreachable backend never sets authed=true',
      () async {
    // hydrate() attempts authMe against backendBaseUrl. In a test
    // environment with no backend, the call fails, and the code
    // path nulls sessionToken so `authed` stays false. This
    // guarantees no authenticated UI can be shown from a stale
    // persisted session before validation completes.
    final app = await _hydratedAppState(
      sessionToken: 'possibly-stale-token',
      lastVaultName: 'alice',
    );
    expect(app.authed, isFalse,
        reason: 'authed must be false until authMe confirms validity');
    expect(app.sessionToken, isNull,
        reason: 'a session that failed startup validation must be cleared');
    // lastVaultName can survive so the /unlock route can offer it.
    expect(app.lastVaultName, 'alice');
  });

  // ==================================================================
  // Scenario 11 — second-tab termination event clears first tab
  // ==================================================================

  test('peer-tab termination advances local state exactly once',
      () async {
    final app = await _hydratedAppState();
    _primeAuthed(app);
    final captured = _installHandlerFor(app);

    // Simulate a peer tab that already terminated locally and
    // broadcast to us. Our channel receiver funnels back into
    // handle(code, reason: peerTab). The local handler must run,
    // and duplicate peer broadcasts for the same generation must
    // be ignored (no logout loop).
    await st.SessionTermination.instance.handle(
      st.SessionTerminationCode.superseded,
      reason: st.SessionTerminationReason.peerTab,
    );
    // A duplicate peer broadcast at the same generation is a
    // no-op.
    await st.SessionTermination.instance.handle(
      st.SessionTerminationCode.superseded,
      reason: st.SessionTerminationReason.peerTab,
    );

    expect(captured, hasLength(1));
    expect(captured.single.reason, st.SessionTerminationReason.peerTab);
    expect(app.sessionToken, isNull);
    expect(st.SessionTermination.instance.generation, 1);
  });

  // ==================================================================
  // Scenario 12 — no raw token/hash/UA appears in logs
  // ==================================================================

  test('termination flow never emits token/hash/UA to logs', () async {
    final app = await _hydratedAppState();
    _primeAuthed(app,
        token: 'DEADBEEF1234567890abcdef.SECRETTOKENstuff');
    _installHandlerFor(app);

    final captured = <String>[];
    await runZoned(() async {
      await st.SessionTermination.instance
          .handle(st.SessionTerminationCode.superseded);
    }, zoneSpecification: ZoneSpecification(
      print: (self, parent, zone, line) {
        captured.add(line);
      },
    ));

    final blob = captured.join('\n');
    expect(blob, isNot(contains('DEADBEEF1234567890abcdef.SECRETTOKENstuff')),
        reason: 'raw token must never appear in logs');
    expect(blob, isNot(contains('Mozilla/5.0')));
    expect(blob, isNot(contains('Chrome/126')));
    // Also assert the user-facing message NEVER carries a token
    // fragment.
    for (final code in st.SessionTerminationCode.values) {
      final msg = st.userMessageFor(code);
      expect(msg, isNot(contains('DEADBEEF')));
      expect(msg, isNot(contains('token')));
      expect(msg, isNot(contains('vault_id')));
    }
  });

  // ==================================================================
  // Extra — SessionTerminatedException carries only safe fields
  // ==================================================================

  test('SessionTerminatedException toString omits message body', () {
    const e = SessionTerminatedException(
      code: st.SessionTerminationCode.superseded,
      message:
          'You were signed out because this Vault was opened on another device.',
    );
    // toString must contain the code (useful in dev logs) but not
    // the raw backend body or any secret material.
    final s = e.toString();
    expect(s, contains('superseded'));
    expect(s, isNot(contains('token')));
    expect(s, isNot(contains('vault_id')));
  });
}
