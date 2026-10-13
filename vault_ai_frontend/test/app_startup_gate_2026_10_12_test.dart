import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/ui/app_startup_gate.dart';

const _readyApp = MaterialApp(home: Text('Initialized app'));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    st.SessionTermination.instance.reset();
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    st.SessionTermination.instance.reset();
  });

  testWidgets('pending initialization paints the original logo without copy',
      (tester) async {
    final pending = Completer<Widget>();
    var calls = 0;
    await tester.pumpWidget(AppStartupGate(initialize: () {
      calls++;
      return pending.future;
    }));
    await tester.pump(const Duration(seconds: 60));
    final logo = tester.widget<Image>(find.byType(Image));
    expect((logo.image as AssetImage).assetName,
        'assets/branding/vaultai-icon-1024.png');
    expect(logo.semanticLabel, 'SVaultAI logo');
    expect(find.text('Opening SVaultAI…'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('Try again'), findsNothing);
    expect(find.byType(Navigator), findsNothing);
    expect(find.text('Initialized app'), findsNothing);
    expect(calls, 1);

    pending.complete(_readyApp);
    await tester.pumpAndSettle();
    expect(find.text('Initialized app'), findsOneWidget);
    expect(find.text('Opening SVaultAI…'), findsNothing);
    expect(find.byType(Image), findsNothing);
    expect(tester.takeException(), isNull);
  });

  test('startup reuses the existing canonical updated branding master', () {
    expect(
      sha256
          .convert(
              File('assets/branding/vaultai-icon-1024.png').readAsBytesSync())
          .toString(),
      '171f3be8c7d1c0d081ed23496dd8bd8b34267cfe07693c72527a9865c47bfcd1',
    );
  });

  testWidgets('pending logo is unchanged on iOS and Android', (tester) async {
    final pending = Completer<Widget>();
    await tester.pumpWidget(AppStartupGate(initialize: () => pending.future));
    await tester.pump();
    expect(find.byType(Image), findsOneWidget);
    expect(find.text('Opening SVaultAI…'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.byType(Navigator), findsNothing);
    expect(tester.takeException(), isNull);
    pending.complete(_readyApp);
    await tester.pumpAndSettle();
  },
      variant:
          TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}));

  testWidgets('manual error retry returns to the same logo-only pending state',
      (tester) async {
    final pending = Completer<Widget>();
    var calls = 0;
    await tester.pumpWidget(AppStartupGate(initialize: () {
      if (++calls == 1) throw StateError('synthetic-do-not-display');
      return pending.future;
    }));
    await tester.pumpAndSettle();
    expect(find.text('SVaultAI could not start. Please try again.'),
        findsOneWidget);
    await tester.tap(find.text('Try again'));
    await tester.pump();
    expect(find.byType(Image), findsOneWidget);
    expect(
        find.text('SVaultAI could not start. Please try again.'), findsNothing);
    expect(find.text('Opening SVaultAI…'), findsNothing);
    expect(find.text('Try again'), findsNothing);
    expect(calls, 2);
    pending.complete(_readyApp);
    await tester.pumpAndSettle();
    expect(find.byType(Image), findsNothing);
    expect(find.text('Initialized app'), findsOneWidget);
    expect(calls, 2);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed initialization offers one retry without exposing secrets',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(AppStartupGate(initialize: () async {
      if (++calls == 1) throw StateError('synthetic-token-do-not-display');
      return _readyApp;
    }));
    await tester.pumpAndSettle();
    expect(find.text('SVaultAI could not start. Please try again.'),
        findsOneWidget);
    expect(find.textContaining('synthetic-token'), findsNothing);
    expect(find.text('Initialized app'), findsNothing);
    expect(find.widgetWithText(FilledButton, 'Try again'), findsOneWidget);

    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('Initialized app'), findsOneWidget);
    expect(find.text('Try again'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('synchronous initialization failures are also visible and safe',
      (tester) async {
    await tester.pumpWidget(AppStartupGate(initialize: () {
      throw StateError('synthetic-local-storage-secret');
    }));
    await tester.pumpAndSettle();
    expect(find.text('SVaultAI could not start. Please try again.'),
        findsOneWidget);
    expect(find.textContaining('synthetic-local-storage-secret'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  test('auth/me times out, retains request headers and ignores a late success',
      () async {
    final pending = Completer<http.Response>();
    var requests = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      authMeTimeout: const Duration(milliseconds: 20),
    );
    await http.runWithClient(() async {
      await expectLater(
        client.authMe(authToken: 'synthetic-session'),
        throwsA(isA<TimeoutException>()),
      );
      pending.complete(http.Response('{"vault_id":"late-vault"}', 200));
      await Future<void>.delayed(Duration.zero);
      expect(requests, 1);
    },
        () => MockClient((request) {
              requests++;
              expect(request.method, 'GET');
              expect(request.url.path, '/auth/me');
              expect(
                  request.headers['Authorization'], 'Bearer synthetic-session');
              return pending.future;
            }));
  });

  test('auth/me still decodes successful responses', () async {
    await http.runWithClient(() async {
      final me = await const VaultAIClient(baseUrl: 'https://synthetic.invalid')
          .authMe(authToken: 'synthetic-session');
      expect(me['vault_id'], 'synthetic-vault');
    },
        () => MockClient((_) async => http.Response(
              jsonEncode({'vault_id': 'synthetic-vault'}),
              200,
            )));
  });

  test('auth/me retains rejected-session and server-error behavior', () async {
    for (final status in [401, 503]) {
      await http.runWithClient(() async {
        await expectLater(
          const VaultAIClient(baseUrl: 'https://synthetic.invalid')
              .authMe(authToken: 'synthetic-session'),
          throwsA(
              status == 401 ? isA<AuthExpiredException>() : isA<Exception>()),
        );
      },
          () => MockClient(
              (_) async => http.Response('{"detail":"test"}', status)));
    }
  });

  testWidgets('startup timeout fails closed and preserves the remembered name',
      (tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{
      'session_token': 'synthetic-session',
      'last_vault_name': 'Synthetic Private Name',
      'last_display_name': 'Synthetic Display',
      'last_vault_handle': 'synthetic-handle',
    });
    final app = AppState();
    final pending = Completer<http.Response>();
    var requests = 0;
    String? requestedPath;
    await http.runWithClient(() async {
      final hydration = app.hydrate();
      await tester.pump();
      expect(requests, 1);
      expect(requestedPath, '/auth/me');
      expect(app.sessionToken, 'synthetic-session');
      await tester.pump(const Duration(seconds: 13));
      await hydration;
      expect(app.authed, isFalse);
      expect(app.sessionToken, isNull);
      expect(app.vaultId, isNull);
      expect(app.unlocked, isFalse);
      expect(app.lastVaultName, 'Synthetic Private Name');
      expect(await NativeSecureStore.readString('last_vault_name'),
          'Synthetic Private Name');
      expect(await NativeSecureStore.readString('session_token'), isNull);
      // A late response must not revive a session after the timeout.
      pending.complete(http.Response('{"vault_id":"late-vault"}', 200));
      await tester.pump();
      expect(app.authed, isFalse);
      expect(app.vaultId, isNull);
    },
        () => MockClient((request) {
              requests++;
              requestedPath = request.url.path;
              return pending.future;
            }));
    app.dispose();
  });

  for (final status in [200, 401, 503]) {
    test('hydrate preserves the existing $status session decision', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        'session_token': 'synthetic-session',
        'last_vault_name': 'Synthetic Private Name',
        'last_vault_handle': 'synthetic-handle',
      });
      final app = AppState();
      await http.runWithClient(
          () => app.hydrate(),
          () => MockClient(
                (_) async => http.Response(
                  status == 200
                      ? '{"vault_id":"synthetic-vault"}'
                      : '{"detail":"synthetic failure"}',
                  status,
                ),
              ));
      expect(app.authed, status == 200);
      expect(app.sessionToken, status == 200 ? 'synthetic-session' : null);
      expect(app.vaultId, status == 200 ? 'synthetic-vault' : null);
      expect(app.unlocked, isFalse);
      expect(app.lastVaultName, 'Synthetic Private Name');
      app.dispose();
    });
  }

  test(
      'main mounts the startup gate rather than awaiting hydrate before runApp',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('Future<void> main() async');
    final end = source.indexOf('const String _kAppLocaleStorageKeyV1', start);
    final mainSource = source.substring(start, end);
    expect(mainSource,
        contains('runApp(AppStartupGate(initialize: initializeApp))'));
    expect(mainSource, contains('await appState.hydrate();'));
    expect(
        mainSource, isNot(contains('runApp(\n        ChangeNotifierProvider')));
    expect(mainSource, contains('purgeIosKeychainAfterReinstallIfNeeded'));
    expect(mainSource, contains('st.SessionTermination.instance.setHandler'));
  });
}
