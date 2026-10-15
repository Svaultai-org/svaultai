import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart'
    show debugDefaultTargetPlatformOverride;
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_platform_interface.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart' as mvk_store;

const tokenA = 'synthetic-session-A';
const tokenB = 'synthetic-session-B';
const vaultA = 'synthetic-vault-A';
const vaultB = 'synthetic-vault-B';
final service = st.SessionTermination.instance;

AppState appWith(Future<Map<String, dynamic>> Function(String) validate) {
  final app = AppState(sessionValidator: validate)
    ..installSessionTerminationHandler();
  addTearDown(app.dispose);
  return app;
}

Future<void> signIn(AppState app,
        {String token = tokenA, String vault = vaultA}) =>
    app.setSession(
        token: token, vaultIdValue: vault, vaultNameValue: 'Test vault');

VaultAIClient clientWith(
        Future<http.Response> Function(http.Request) respond) =>
    VaultAIClient(
        baseUrl: 'https://example.invalid', httpClient: MockClient(respond));

Future<VaultCryptoContext?> installContext(int saltByte, String source,
    {String vault = vaultA}) async {
  final previous = debugDefaultTargetPlatformOverride;
  debugDefaultTargetPlatformOverride = TargetPlatform.macOS;
  try {
    return await deriveAndInstallCryptoContext(
        vaultId: vault,
        vaultName: 'Test vault',
        pin: '000000',
        pinSaltBase64: base64Encode(List<int>.filled(16, saltByte)),
        iterations: 1,
        source: source);
  } finally {
    debugDefaultTargetPlatformOverride = previous;
  }
}

Widget gate(AppState app, {bool public = false}) =>
    ChangeNotifierProvider<AppState>.value(
        value: app,
        child: MaterialApp(
          home: SessionStatusGate(
              publicMarketingVisible: public,
              onSignIn: () {},
              child: const Scaffold(body: Text('Private content'))),
        ));

class DelayedRemovalStore extends InMemorySharedPreferencesStore {
  DelayedRemovalStore() : super.empty();
  final started = Completer<void>();
  final release = Completer<void>();
  @override
  Future<bool> remove(String key) async {
    if (key == 'flutter.session_token' && !started.isCompleted) {
      started.complete();
      await release.future;
    }
    return super.remove(key);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    service.resetForTests();
    NativeSecureStore.useSharedPreferencesForTesting = true;
    SharedPreferences.setMockInitialValues({});
  });
  tearDown(() {
    service.resetForTests();
    NativeSecureStore.useSharedPreferencesForTesting = false;
    VaultCryptoRegistry.clear(reason: 'session monitor test teardown');
    mvk_store.ZkActiveMvk.clear();
  });

  testWidgets('idle foreground detects second-device login within 15 seconds',
      (tester) async {
    var requests = 0;
    final observedRequests = <http.Request>[];
    var superseded = false;
    final client = clientWith((request) async {
      requests++;
      observedRequests.add(request);
      return superseded
          ? http.Response('{"detail":{"code":"session_superseded"}}', 401)
          : http.Response('{"vault_id":"$vaultA"}', 200);
    });
    final app = appWith((token) => client.authMe(authToken: token));
    await signIn(app);
    app.startSessionMonitoring();
    superseded = true;
    await tester.pump(const Duration(seconds: 14));
    expect(requests, 0);
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(requests, 1);
    expect(observedRequests.single.method, 'GET');
    expect(observedRequests.single.url.path, '/auth/me');
    expect(app.sessionToken, isNull);
    expect(app.authed, isFalse);
    expect(app.signedOutCode, st.SessionTerminationCode.superseded);
    final sp = await SharedPreferences.getInstance();
    expect(sp.getString('session_token'), isNull);
    expect(sp.getString('session_signed_out_code'), 'session_superseded');
    await tester.pumpWidget(gate(app));
    expect(find.text('Private content'), findsNothing);
    expect(find.text('Signed out'), findsOneWidget);
    expect(find.text(st.userMessageFor(st.SessionTerminationCode.superseded)),
        findsOneWidget);
    app.stopSessionMonitoring();
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'background stops polling and resume covers private dialog until checked',
      (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    var requests = 0;
    final app = appWith((_) {
      requests++;
      return pending.future;
    });
    await signIn(app);
    final context = await tester
        .runAsync(() => installContext(1, 'session monitor fixture'));
    app.unlocked = true;
    expect(app.unlocked, isTrue);
    app.startSessionMonitoring();
    await tester.pumpWidget(gate(app));
    app.sessionLifecycleChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 30));
    expect(requests, 0);
    expect(app.unlocked, isTrue,
        reason: 'Ordinary resume does not require another PIN.');
    expect(identical(VaultCryptoRegistry.current, context), isTrue);
    app.sessionLifecycleChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(requests, 1);
    expect(find.text('Private content'), findsNothing);
    expect(find.text('Checking your session'), findsOneWidget);
    pending.complete({'vault_id': vaultA});
    await tester.pump();
    expect(app.sessionVerificationBlocked, isFalse);
    expect(app.unlocked, isTrue);
    expect(identical(VaultCryptoRegistry.current, context), isTrue);
    app.unlocked = false;
    expect(find.text('Private content'), findsOneWidget);
    app.stopSessionMonitoring();
    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final response in [
    http.Response('{"detail":"Unauthorized"}', 401),
    http.Response('{"detail":{"code":"invalid_pin"}}', 401),
    http.Response('{"detail":"Forbidden"}', 403),
    http.Response('{}', 503),
  ]) {
    testWidgets(
        'unclassified ${response.statusCode}/${response.body} keeps resumed session and retry',
        (tester) async {
      var valid = false;
      final client = clientWith((_) async =>
          valid ? http.Response('{"vault_id":"$vaultA"}', 200) : response);
      final app = appWith((token) => client.authMe(authToken: token));
      await signIn(app);
      app.sessionLifecycleChanged(AppLifecycleState.paused);
      app.sessionLifecycleChanged(AppLifecycleState.resumed);
      await tester.pump();
      await tester.pumpWidget(gate(app));
      expect(app.sessionToken, tokenA);
      expect(app.authed, isTrue);
      expect(app.sessionVerificationUnavailable, isTrue);
      expect(find.text('Private content'), findsNothing);
      expect(find.text('Retry'), findsOneWidget);
      expect((await SharedPreferences.getInstance()).getString('session_token'),
          tokenA);
      valid = true;
      await tester.tap(find.text('Retry'));
      await tester.pump();
      expect(find.text('Private content'), findsOneWidget);
      expect(app.sessionVerificationBlocked, isFalse);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('offline startup retains token, hides private UI, and can retry',
      (tester) async {
    SharedPreferences.setMockInitialValues(
        {'session_token': tokenA, 'last_vault_name': 'Test vault'});
    var offline = true;
    final app = appWith((_) async {
      if (offline) throw http.ClientException('Offline');
      return {'vault_id': vaultA};
    });
    await app.hydrate();
    expect(app.hydrated, isTrue);
    expect(app.authed, isFalse);
    expect(app.sessionToken, tokenA);
    expect(app.sessionVerificationUnavailable, isTrue);
    await tester.pumpWidget(gate(app));
    expect(find.text('Private content'), findsNothing);
    expect(find.text('Retry'), findsOneWidget);
    offline = false;
    await tester.tap(find.text('Retry'));
    await tester.pump();
    expect(app.authed, isTrue);
    expect(find.text('Private content'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'public marketing remains visible while session check is unavailable',
      (tester) async {
    final app = appWith((_) async => throw http.ClientException('Offline'));
    await signIn(app);
    app.sessionLifecycleChanged(AppLifecycleState.paused);
    app.sessionLifecycleChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pumpWidget(gate(app, public: true));
    expect(find.text('Private content'), findsOneWidget);
    expect(find.text('Retry'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final status in [200, 401, 403]) {
    testWidgets(
        'old validation $status cannot clear or restore over a replacement login',
        (tester) async {
      final pending = Completer<http.Response>();
      final client = clientWith((_) => pending.future);
      final app = appWith((token) => client.authMe(authToken: token));
      await signIn(app);
      final check = app.validateCurrentSession();
      await tester.pump();
      await signIn(app, token: tokenB, vault: vaultB);
      pending.complete(http.Response(
          status == 200
              ? '{"vault_id":"$vaultA"}'
              : status == 401
                  ? '{"detail":{"code":"session_superseded"}}'
                  : '{"detail":{"code":"device_revoked"}}',
          status));
      await check;
      expect(app.sessionToken, tokenB);
      expect(app.vaultId, vaultB);
      expect(app.authed, isTrue);
      expect(app.signedOutCode, isNull);
      expect((await SharedPreferences.getInstance()).getString('session_token'),
          tokenB);
    });
  }

  testWidgets(
      'pre-background validation cannot uncover resume without a fresh check',
      (tester) async {
    final old = Completer<Map<String, dynamic>>();
    final fresh = Completer<Map<String, dynamic>>();
    var requests = 0;
    final app = appWith((_) => ++requests == 1 ? old.future : fresh.future);
    await signIn(app);
    final first = app.validateCurrentSession();
    app.sessionLifecycleChanged(AppLifecycleState.paused);
    app.sessionLifecycleChanged(AppLifecycleState.resumed);
    old.complete({'vault_id': vaultA});
    await first;
    await tester.pump();
    expect(requests, 2);
    expect(app.sessionVerificationBlocked, isTrue);
    fresh.complete({'vault_id': vaultA});
    await tester.pump();
    expect(app.sessionVerificationBlocked, isFalse);
  });

  testWidgets(
      'picker background/resume preserves unlock and defers validation until completion',
      (tester) async {
    var requests = 0;
    final picked = Completer<String>();
    final app = appWith((_) async {
      requests++;
      return {'vault_id': vaultA};
    });
    await signIn(app);
    final context = await tester
        .runAsync(() => installContext(2, 'picker session fixture'));
    app.unlocked = true;
    final result = app.runWithNativePickerKeepAlive(() => picked.future);
    app.sessionLifecycleChanged(AppLifecycleState.paused);
    app.sessionLifecycleChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(requests, 0);
    expect(app.unlocked, isTrue);
    expect(identical(VaultCryptoRegistry.current, context), isTrue);
    picked.complete('selected-file');
    expect(await result, 'selected-file');
    await tester.pump();
    expect(requests, 1);
    expect(app.sessionVerificationBlocked, isFalse);
    expect(app.unlocked, isTrue);
    app.unlocked = false;
  });

  test(
      'old queued cleanup cannot delete new persisted login or signed-out state',
      () async {
    final app = appWith((_) async => {'vault_id': vaultA});
    await signIn(app);
    final oldCleanup =
        app.clearSession(signedOutCode: st.SessionTerminationCode.superseded);
    final replacement = signIn(app, token: tokenB, vault: vaultB);
    await Future.wait([oldCleanup, replacement]);
    final sp = await SharedPreferences.getInstance();
    expect(app.sessionToken, tokenB);
    expect(sp.getString('session_token'), tokenB);
    expect(sp.getString('session_signed_out_code'), isNull);
  });

  for (final status in [200, 401]) {
    test('late logout$status cannot clear a replacement login, keys or billing', () async {
      final response = Completer<http.Response>();
      final started = Completer<void>();
      final app = appWith((_) async => {'vault_id': vaultA});
      await http.runWithClient(() async {
        await signIn(app);
        final logout = app.signOutEverywhere();
        await started.future;
        await signIn(app, token: tokenB, vault: vaultB);
        final currentContext = await installContext(4, 'replacement logout fixture', vault: vaultB);
        app.unlocked = true;
        app.applyBillingPayload({'block_count': 3, 'effective_limit_bytes': 9000});
        response.complete(http.Response(status == 401
          ? '{"detail":{"code":"session_superseded"}}' : '{}', status));
        await logout;
        expect(app.sessionToken, tokenB);
        expect(app.vaultId, vaultB);
        expect(app.authed, isTrue);
        expect(app.unlocked, isTrue);
        expect(VaultCryptoRegistry.current, same(currentContext));
        expect(app.billingBlockCount, 3);
        expect(app.billingEffectiveLimitBytes, 9000);
        expect((await SharedPreferences.getInstance()).getString('session_token'), tokenB);
      }, () => MockClient((request) {
        expect(request.url.path, '/auth/logout');
        started.complete();
        return response.future;
      }));
    });
  }

  test('validated replacement token clears a stale saved sign-out notice', () async {
    SharedPreferences.setMockInitialValues({
      'session_token': tokenB,
      'session_signed_out_code': 'session_superseded',
      'last_vault_name': 'Test vault',
    });
    final app = appWith((_) async => {'vault_id': vaultB});
    await app.hydrate();
    expect(app.sessionToken, tokenB);
    expect(app.authed, isTrue);
    expect(app.signedOutCode, isNull);
    expect((await SharedPreferences.getInstance()).getString('session_signed_out_code'), isNull);
  });

  test('already-running old disk cleanup finishes before replacement token writes', () async {
    final store = DelayedRemovalStore();
    SharedPreferencesStorePlatform.instance = store;
    final app = appWith((_) async => {'vault_id': vaultA});
    await signIn(app);
    final cleanup = app.clearSession(signedOutCode: st.SessionTerminationCode.superseded);
    await store.started.future;
    final replacement = signIn(app, token: tokenB, vault: vaultB);
    expect(app.sessionToken, tokenB);
    store.release.complete();
    await Future.wait([cleanup, replacement]);
    final sp = await SharedPreferences.getInstance();
    expect(sp.getString('session_token'), tokenB);
    expect(sp.getString('session_signed_out_code'), isNull);
    expect(app.signedOutCode, isNull);
  });

  test('departing tab cannot delete another tab winning token or identity', () async {
    final app = appWith((_) async => {'vault_id': vaultA});
    await signIn(app);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('session_token', tokenB);
    await prefs.setString('last_vault_name', 'New tab vault');
    final cleanup = app.clearSession(keepLastVaultName: false,
      signedOutCode: st.SessionTerminationCode.superseded);
    await cleanup;
    expect(app.sessionToken, isNull);
    expect(prefs.getString('session_token'), tokenB);
    expect(prefs.getString('last_vault_name'), 'New tab vault');
    expect(prefs.getString('session_signed_out_code'), isNull);
  });

  for (final wire in ['session_superseded', 'session_expired', 'session_revoked', 'invalid_session']) {
    test('current authMe $wire confirms termination and wipes saved session', () async {
      final client = clientWith((_) async => http.Response(
        jsonEncode({'detail': {'code': wire}}), 401));
      final app = appWith((token) => client.authMe(authToken: token));
      await signIn(app);
      await app.validateCurrentSession();
      await Future<void>.delayed(Duration.zero);
      expect(app.sessionToken, isNull);
      expect(app.signedOutCode, st.parseSessionTerminationCode(wire));
      expect((await SharedPreferences.getInstance()).getString('session_token'), isNull);
    });
  }

  test('current device-revoked authMe403 confirms termination', () async {
    final client = clientWith((_) async => http.Response(
      '{"detail":{"code":"device_revoked","status":"revoked"}}', 403));
    final app = appWith((token) => client.authMe(authToken: token));
    await signIn(app);
    await app.validateCurrentSession();
    expect(app.sessionToken, isNull);
    expect(app.signedOutCode, st.SessionTerminationCode.revoked);
  });

  test(
      'confirmed takeover clears crypto and persistent notice survives restart',
      () async {
    final app = appWith((_) async => {'vault_id': vaultA});
    await signIn(app);
    await installContext(3, 'takeover fixture');
    await service.handle(st.SessionTerminationCode.superseded,
        request: service.captureRequest(tokenA));
    expect(app.sessionToken, isNull);
    expect(VaultCryptoRegistry.current, isNull);
    expect(app.signedOutCode, st.SessionTerminationCode.superseded);
    final restored =
        appWith((_) async => throw StateError('No token to validate'));
    await restored.hydrate();
    expect(restored.hydrated, isTrue);
    expect(restored.signedOutCode, st.SessionTerminationCode.superseded);
    restored.requestSignInAfterTermination();
    await signIn(restored, token: tokenB, vault: vaultB);
    expect(restored.signedOutCode, isNull);
    expect(service.isTerminated, isFalse);
  });
}
