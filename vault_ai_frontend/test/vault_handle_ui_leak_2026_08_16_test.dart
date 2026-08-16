import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/vault_handle.dart' as vh;

const _handle = 'VLT-1111-2222-3333-4444-5555-6666';

const _localizationsDelegates = <LocalizationsDelegate<Object?>>[
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

Future<AppState> _hydrate([Map<String, Object> values = const {}]) async {
  SharedPreferences.setMockInitialValues(values);
  final app = AppState();
  await app.hydrate().timeout(const Duration(seconds: 5));
  return app;
}

Future<void> _pumpLogin(WidgetTester tester, AppState app) async {
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        localizationsDelegates: _localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        routes: {
          '/signup': (_) => const Scaffold(body: Text('SIGNUP')),
          '/unlock': (_) => const Scaffold(body: Text('UNLOCK')),
        },
        home: const LoginPage(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _pumpUnlock(WidgetTester tester, AppState app) async {
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        localizationsDelegates: _localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        routes: {
          '/login': (_) => const Scaffold(body: Text('LOGIN')),
        },
        home: const UnlockPage(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

String _loginFieldText(WidgetTester tester) {
  final field = tester.widget<TextField>(
    find.byKey(const Key('auth_vault_name_field')),
  );
  return field.controller?.text ?? '';
}

void main() {
  setUp(() {
    NativeSecureStore.useSharedPreferencesForTesting = true;
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
  });

  group('display vault name and internal handle separation', () {
    test('suppresses prefixed, malformed, grouped, and compact handles', () {
      expect(vh.userFacingVaultNameOrNull(_handle), isNull);
      expect(vh.userFacingVaultNameOrNull('vlt-not-a-valid-handle'), isNull);
      expect(
        vh.userFacingVaultNameOrNull('1111-2222-3333-4444-5555-6666'),
        isNull,
      );
      expect(
        vh.userFacingVaultNameOrNull('111122223333444455556666'),
        isNull,
      );
      expect(vh.userFacingVaultNameOrNull('  Vault A  '), 'Vault A');
    });

    test('AppState display setters reject handles', () {
      final app = AppState();
      app.vaultName = _handle;
      app.lastVaultName = _handle;
      app.vaultHandle = _handle;

      expect(app.vaultName, isNull);
      expect(app.lastVaultName, isNull);
      expect(app.vaultHandle, _handle);
      expect(app.hasRememberedVaultLogin, isTrue);
    });
  });

  testWidgets('A: fresh install shows an empty vault-name field',
      (tester) async {
    final app = await _hydrate();
    await _pumpLogin(tester, app);

    expect(find.byKey(const Key('auth_vault_name_field')), findsOneWidget);
    expect(_loginFieldText(tester), isEmpty);
    expect(find.textContaining('VLT-'), findsNothing);
  });

  testWidgets('B: an intentionally remembered human name may be prefilled',
      (tester) async {
    final app = await _hydrate();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('last_vault_name', 'Vault A');

    await _pumpLogin(tester, app);

    expect(_loginFieldText(tester), 'Vault A');
    expect(_loginFieldText(tester), isNot(startsWith('VLT-')));
  });

  test('B/D: logout retains display name and private auth handle', () async {
    final app = await _hydrate();
    await app.setSession(
      token: 'synthetic-session',
      vaultIdValue: 'synthetic-vault-id',
      vaultNameValue: 'Vault A',
      vaultHandleValue: _handle,
    );

    await app.clearSession(keepLastVaultName: true);

    expect(app.lastVaultName, 'Vault A');
    expect(app.vaultHandle, _handle);
    expect(app.hasRememberedVaultLogin, isTrue);
    final selected = selectInheritanceRevealLoginIdentifier(
      vaultName: app.vaultName,
      lastVaultName: app.lastVaultName,
      vaultHandle: app.vaultHandle,
    );
    expect(selected.vaultHandle, _handle);
    expect(selected.source, 'stored_vault_handle');
  });

  testWidgets('C: Use another vault clears stale display and handle state',
      (tester) async {
    final app = await _hydrate();
    await app.setSession(
      token: 'synthetic-session',
      vaultIdValue: 'synthetic-vault-id',
      vaultNameValue: 'Vault A',
      vaultHandleValue: _handle,
    );
    await app.clearSession(keepLastVaultName: false);

    expect(app.lastVaultName, isNull);
    expect(app.vaultHandle, isNull);
    expect(app.hasRememberedVaultLogin, isFalse);
    await _pumpLogin(tester, app);
    expect(_loginFieldText(tester), isEmpty);
    expect(find.textContaining('VLT-'), findsNothing);
  });

  testWidgets('E: PIN validation error never renders the private handle',
      (tester) async {
    final app = await _hydrate({'last_vault_handle': _handle});
    await _pumpUnlock(tester, app);

    expect(find.byKey(const Key('auth_vault_name_field')), findsNothing);
    expect(find.textContaining(_handle), findsNothing);
    await tester.tap(find.byKey(const Key('auth_unlock_button')));
    await tester.pump();
    expect(find.text('PIN can only contain digits.'), findsOneWidget);
    expect(find.textContaining(_handle), findsNothing);
  });

  test('F: hard restart migrates a leaked name-slot handle privately',
      () async {
    final app = await _hydrate({'last_vault_name': _handle});

    expect(app.vaultName, isNull);
    expect(app.lastVaultName, isNull);
    expect(app.vaultHandle, _handle);
    expect(app.hasRememberedVaultLogin, isTrue);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('last_vault_name'), isNull);
    expect(prefs.getString('last_vault_handle'), _handle);
  });

  testWidgets(
      'G/H/I: shared web Android and iOS login autofill suppresses VLT values',
      (tester) async {
    final app = await _hydrate();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('last_vault_name', _handle);
    await prefs.setString('last_vault_handle', _handle);

    await _pumpLogin(tester, app);

    expect(_loginFieldText(tester), isEmpty);
    expect(find.textContaining('VLT-'), findsNothing);
    expect(prefs.getString('last_vault_handle'), _handle,
        reason: 'UI suppression must not destroy the private auth handle');
  });
}
