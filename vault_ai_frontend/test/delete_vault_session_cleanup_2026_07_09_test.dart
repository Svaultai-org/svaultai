/// Regression tests for the "user stays inside the app after Delete
/// Vault succeeds" bug.
///
/// Bug shape (pre-fix):
///   * user completes Delete Vault (phrase + PIN + trusted device)
///   * backend returns 204 and deletes the vault
///   * frontend clears only `sessionToken` (a plain field write) —
///     does NOT clear vaultId/vaultName/caches/SharedPreferences
///   * user stays visually inside Settings; a second Delete-Vault
///     tap surfaces "Please sign in again to delete your vault."
///
/// Fix under test:
///   * `AppState.handleVaultDeleted()` performs a full session +
///     cache + persistent-storage wipe, notifies listeners, then
///     navigates via `rootNavigatorKey` to `/auth` with
///     `pushNamedAndRemoveUntil`.
///   * The Settings-tile handler calls that method instead of the
///     old `sessionToken = null` shortcut.
///   * The `api_client.confirmDeleteVault` treats 204 (and 200) as
///     success — nothing else.
///
/// These tests never touch real auth logic, real PIN handling, or
/// real trusted-device gates. They exercise only the *state
/// cleanup* + *response-code handling* portions of the flow, which
/// is what the bug lives in.

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/perf/frontend_cache.dart' as perf_cache;
import 'package:vault_ai_frontend/services/crypto_chat_live_cache.dart';


Future<AppState> _hydratedAppState({
  String? sessionToken,
  String? lastVaultName,
}) async {
  final initial = <String, Object>{};
  if (sessionToken != null) initial['session_token'] = sessionToken;
  if (lastVaultName != null) initial['last_vault_name'] = lastVaultName;
  SharedPreferences.setMockInitialValues(initial);
  final app = AppState();


  await app.hydrate().timeout(
    const Duration(seconds: 5),
    onTimeout: () {},
  );
  return app;
}


void _primeAuthedVault(AppState app, {
  String token = 'sess-abc',
  String vaultId = 'vault-42',
  String vaultName = 'alice-vault',
  String display = 'Alice',
}) {

  app.sessionToken = token;
  app.vaultId = vaultId;
  app.vaultName = vaultName;
  app.displayName = display;
  app.authed = true;
  app.unlocked = true;
  app.availableVaults = [
    {'vault_name': vaultName, 'vault_id': vaultId},
  ];
  app.notifications = [
    {'title': 'Welcome', 'body': 'Hi', 'unread': true},
  ];
  app.unreadNotificationCount = 1;
  app.billingBlockCount = 2;
  app.billingPurchasedBytes = 100;
  app.storageUsedBytes = 42;
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });



  group('AppState.handleVaultDeleted', () {
    test('clears sessionToken from memory and SharedPreferences',
        () async {
      final app = await _hydratedAppState(
        sessionToken: 'sess-abc',
        lastVaultName: 'alice-vault',
      );
      _primeAuthedVault(app);
      expect(app.sessionToken, 'sess-abc');

      await app.handleVaultDeleted();

      expect(app.sessionToken, isNull,
          reason: 'in-memory sessionToken must be null after delete');
      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('session_token'), isNull,
          reason: 'persisted session_token must be removed');
    });

    test('clears vaultId, vaultName, displayName, authed, unlocked',
        () async {
      final app = await _hydratedAppState(sessionToken: 'sess-abc');
      _primeAuthedVault(app);

      await app.handleVaultDeleted();

      expect(app.vaultId, isNull);
      expect(app.vaultName, isNull);
      expect(app.displayName, isNull);
      expect(app.authed, isFalse);
      expect(app.unlocked, isFalse);
    });

    test('removes last_vault_name from SharedPreferences so the '
        'deleted vault does not resurface after a refresh', () async {
      final app = await _hydratedAppState(
        sessionToken: 'sess-abc',
        lastVaultName: 'alice-vault',
      );
      _primeAuthedVault(app);

      await app.handleVaultDeleted();

      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('last_vault_name'), isNull,
          reason: 'a refresh must NOT re-hydrate the deleted vault '
              'name back into AppState');
      expect(app.lastVaultName, isNull);
    });

    test('clears availableVaults, notifications, unreadCount, billing '
        'and storage state', () async {
      final app = await _hydratedAppState(sessionToken: 'sess-abc');
      _primeAuthedVault(app);

      await app.handleVaultDeleted();

      expect(app.availableVaults, isEmpty);
      expect(app.notifications, isEmpty);
      expect(app.unreadNotificationCount, 0);
      expect(app.billingBlockCount, 0);
      expect(app.billingPurchasedBytes, 0);
      expect(app.billingIncludedBytes, 0);
      expect(app.billingEffectiveLimitBytes, 0);
      expect(app.storageUsedBytes, 0);
      expect(app.storagePendingBytes, 0);
      expect(app.recoveryInfo, isNull);
    });

    test('clears CryptoChatLiveCache and FrontendCache', () async {
      final app = await _hydratedAppState(sessionToken: 'sess-abc');
      _primeAuthedVault(app);


      await CryptoChatLiveCache.instance.fetch(
        type: 'balance', asset: 'BTC', address: 'addr-x',
        run: () async => {'balance': 1.0},
      );
      expect(
        CryptoChatLiveCache.instance.hasFresh(
          type: 'balance', asset: 'BTC', address: 'addr-x',
        ),
        isTrue,
      );


      perf_cache.FrontendCache.instance.put('probe-key', 'probe-value');
      expect(perf_cache.FrontendCache.instance.has('probe-key'), isTrue);

      await app.handleVaultDeleted();

      expect(
        CryptoChatLiveCache.instance.hasFresh(
          type: 'balance', asset: 'BTC', address: 'addr-x',
        ),
        isFalse,
        reason: 'crypto chat cache must be wiped after vault delete',
      );
      expect(
        perf_cache.FrontendCache.instance.has('probe-key'), isFalse,
        reason: 'FrontendCache must be wiped after vault delete',
      );
    });

    test('notifies listeners so widgets rebuild without the stale '
        'vault header', () async {
      final app = await _hydratedAppState(sessionToken: 'sess-abc');
      _primeAuthedVault(app);

      int notifyCount = 0;
      app.addListener(() => notifyCount++);

      await app.handleVaultDeleted();

      expect(notifyCount, greaterThanOrEqualTo(1),
          reason: 'listeners must be notified so the sidebar / header '
              'rebuild with no vault name');
    });

    test('is idempotent — running twice does not throw', () async {
      final app = await _hydratedAppState(sessionToken: 'sess-abc');
      _primeAuthedVault(app);
      await app.handleVaultDeleted();

      await app.handleVaultDeleted();
      expect(app.sessionToken, isNull);
      expect(app.vaultId, isNull);
    });

    test('handles the "already logged out" edge case (no vault, no '
        'token) without crashing', () async {
      final app = await _hydratedAppState();
      expect(app.sessionToken, isNull);

      await app.handleVaultDeleted();
      expect(app.authed, isFalse);
    });
  });



  group('AppState.handleVaultDeleted vs AppState.signOut / '
      'clearSession — separation of concerns', () {
    test('signOut without delete still leaves lastVaultName so the '
        'user can unlock again', () async {
      final app = await _hydratedAppState(
        sessionToken: 'sess-abc',
        lastVaultName: 'alice-vault',
      );
      _primeAuthedVault(app);


      await app.clearSession(keepLastVaultName: true);

      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('last_vault_name'), 'alice-vault',
          reason: 'plain sign-out must NOT forget the vault name — '
              'that is what /unlock uses to re-authenticate the same '
              'user without asking for the vault name again');
      expect(app.sessionToken, isNull,
          reason: 'plain sign-out still clears the session token');
    });

    test('handleVaultDeleted DOES forget lastVaultName, unlike '
        'signOut', () async {
      final app = await _hydratedAppState(
        sessionToken: 'sess-abc',
        lastVaultName: 'alice-vault',
      );
      _primeAuthedVault(app);

      await app.handleVaultDeleted();

      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('last_vault_name'), isNull,
          reason: 'delete must wipe the vault name so the app cannot '
              'suggest re-unlocking a vault that no longer exists');
      expect(app.lastVaultName, isNull);
    });
  });



  group('api_client.confirmDeleteVault success-code handling '
      '(source-level guards)', () {




    late final String apiClientSrc;
    setUpAll(() {
      apiClientSrc = File('lib/api_client.dart').readAsStringSync();
    });

    String _confirmDeleteBody() {
      final start = apiClientSrc.indexOf('Future<void> confirmDeleteVault');
      expect(start, greaterThan(-1),
          reason: 'confirmDeleteVault must exist');
      final endMarker = 'Future<Map<String, dynamic>> registerDevice';
      final end = apiClientSrc.indexOf(endMarker, start);
      return apiClientSrc.substring(start, end == -1 ? start + 4000 : end);
    }

    test('treats 204 (no body) as success (no throw path)', () {
      final body = _confirmDeleteBody();
      expect(
        body,
        contains('statusCode == 204'),
        reason: 'confirmDeleteVault must treat 204 as success — the '
            'backend returns 204 by design (see '
            'routes/vault_delete_routes.py: HTTP_204_NO_CONTENT)',
      );
    });

    test('also treats 200 as success (compat with future backend '
        'refactors)', () {
      final body = _confirmDeleteBody();
      expect(body, contains('statusCode == 200'));
    });

    test('routes 401 through AuthExpiredException before the 204/200 '
        'success check', () {
      final body = _confirmDeleteBody();

      final expiredIdx  = body.indexOf('_throwIfAuthExpired');
      final successIdx  = body.indexOf('statusCode == 204');
      expect(expiredIdx, greaterThan(-1));
      expect(successIdx, greaterThan(-1));
      expect(expiredIdx, lessThan(successIdx),
          reason: '401/403 must be classified BEFORE we return "success" '
              'so a failed delete cannot be silently promoted to a '
              'session-wipe on the client');
    });

    test('routes 403 device_not_trusted through DeviceNotTrustedException',
        () {
      final body = _confirmDeleteBody();
      expect(body, contains('_throwIfDeviceNotTrusted'));
    });

    test('any non-2xx that is not 401/403 throws — does NOT claim '
        'success', () {
      final body = _confirmDeleteBody();
      expect(body, contains("throw Exception("));
      expect(
        body,
        contains("'Delete confirmation failed'"),
        reason: 'the failure path must carry a distinct, honest '
            'message — never a "success" fall-through',
      );
    });
  });



  group('ARB copy for the success snackbar', () {
    test('English "Your vault has been deleted." is defined', () async {
      final l = await AppLocalizations.delegate.load(
        const Locale('en'),
      );
      expect(l.deleteVaultSuccess, 'Your vault has been deleted.');
    });

    test('Korean and Arabic have their own translations '
        '(no English fallback bleed-through)', () async {
      final en = await AppLocalizations.delegate.load(const Locale('en'));
      for (final code in const <String>['ko', 'ar', 'fr', 'es', 'ja', 'zh']) {
        final l =
            await AppLocalizations.delegate.load(Locale(code));
        expect(l.deleteVaultSuccess.trim(), isNotEmpty,
            reason: '$code deleteVaultSuccess must be non-empty');
        expect(l.deleteVaultSuccess, isNot(equals(en.deleteVaultSuccess)),
            reason: '$code deleteVaultSuccess must not be the English '
                'string (would signal a missing translation)');
      }
    });

    test('the success message never contains the pre-fix "Please sign '
        'in again to delete your vault" phrase', () async {

      for (final code in const <String>['en', 'ko', 'ar', 'fr', 'es',
          'ja', 'zh']) {
        final l = await AppLocalizations.delegate.load(Locale(code));
        expect(
          l.deleteVaultSuccess.toLowerCase(),
          isNot(contains('sign in again')),
          reason: '$code deleteVaultSuccess must not tell the user to '
              'sign in — the vault is deleted, they cannot sign in',
        );
      }
    });
  });



  group('Settings-tile behaviour after delete success', () {
    testWidgets('when handleVaultDeleted runs from inside a Settings-'
        'shaped scaffold, the tile is unmounted (navigator pop)',
        (tester) async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        'session_token': 'sess-abc',
        'last_vault_name': 'alice-vault',
      });
      final app = AppState();
      await app.hydrate().timeout(
        const Duration(seconds: 5), onTimeout: () {},
      );
      _primeAuthedVault(app);

      await tester.pumpWidget(
        ChangeNotifierProvider<AppState>.value(
          value: app,
          child: MaterialApp(
            navigatorKey: rootNavigatorKey,
            scaffoldMessengerKey: rootScaffoldMessengerKey,
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            supportedLocales: AppLocalizations.supportedLocales,
            routes: {
              '/auth': (_) => const Scaffold(
                key: Key('auth_landing'),
                body: Center(child: Text('Sign in')),
              ),
            },
            home: Scaffold(
              key: const Key('settings_scaffold'),
              body: Text(
                'Active vault: ${app.vaultName ?? 'none'}',
                key: const Key('probe_vault_name'),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        tester.widget<Text>(find.byKey(const Key('probe_vault_name')))
            .data,
        'Active vault: alice-vault',
      );

      await app.handleVaultDeleted();
      await tester.pumpAndSettle();


      expect(find.byKey(const Key('auth_landing')), findsOneWidget,
          reason: 'delete success must land the user on /auth');
      expect(find.byKey(const Key('settings_scaffold')), findsNothing,
          reason: 'the settings scaffold must not remain in the tree '
              '— pushNamedAndRemoveUntil((_) => false) removes it');



      final messenger = rootScaffoldMessengerKey.currentState;
      expect(messenger, isNotNull);
      expect(find.byKey(const Key('delete_vault_success_snackbar')),
          findsOneWidget,
          reason: 'the user must see "Your vault has been deleted." '
              'confirmation, not "Please sign in again to delete your '
              'vault."');


      expect(
        find.text('Please sign in again to delete your vault.'),
        findsNothing,
        reason: 'the pre-fix stale-copy must not surface after a '
            'successful delete',
      );
    });

    testWidgets('handleVaultDeleted works even if the presenting '
        'context is unmounted before it runs', (tester) async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        'session_token': 'sess-abc',
      });
      final app = AppState();
      await app.hydrate().timeout(
        const Duration(seconds: 5), onTimeout: () {},
      );
      _primeAuthedVault(app);

      await tester.pumpWidget(
        ChangeNotifierProvider<AppState>.value(
          value: app,
          child: MaterialApp(
            navigatorKey: rootNavigatorKey,
            scaffoldMessengerKey: rootScaffoldMessengerKey,
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            supportedLocales: AppLocalizations.supportedLocales,
            routes: {
              '/auth': (_) => const Scaffold(
                key: Key('auth_landing_2'),
                body: Center(child: Text('Sign in')),
              ),
            },
            home: const Scaffold(body: SizedBox()),
          ),
        ),
      );
      await tester.pumpAndSettle();


      await app.handleVaultDeleted();
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('auth_landing_2')), findsOneWidget);
    });
  });
}
