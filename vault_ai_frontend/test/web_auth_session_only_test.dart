import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';

class _ReadyApp extends AppState {
  @override
  bool get hydrated => true;
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test(
    'web removes old stored auth identity and keeps new sessions in memory',
    () async {
      if (!kIsWeb) return;
      SharedPreferences.setMockInitialValues(<String, Object>{
        'session_token': 'synthetic-old-session',
        'last_vault_name': 'Old Web Name',
        'last_vault_handle': 'VLT-SYNTHETIC',
        'last_display_name': 'Old Display Name',
        'last_canonical_username': 'Old Canonical Name',
        'last_display_username': 'Old Legacy Display',
        'last_vault_ai_name': 'Old AI Name',
        'vaultai.zk.vault_handle': 'VLT-LEGACY',
        'unrelated_preference': 'keep me',
      });

      final app = AppState();
      await app.hydrate();
      final prefs = await SharedPreferences.getInstance();
      expect(app.sessionToken, isNull);
      expect(app.vaultName, isNull);
      expect(app.lastVaultName, isNull);
      expect(app.vaultHandle, isNull);
      expect(app.displayName, isNull);
      for (final key in <String>[
        'session_token',
        'last_vault_name',
        'last_vault_handle',
        'last_display_name',
        'last_canonical_username',
        'last_display_username',
        'last_vault_ai_name',
        'vaultai.zk.vault_handle',
      ]) {
        expect(
          prefs.getString(key),
          isNull,
          reason: '$key survived web cleanup',
        );
      }
      expect(prefs.getString('unrelated_preference'), 'keep me');

      await app.setSession(
        token: 'synthetic-new-session',
        vaultIdValue: 'synthetic-vault-id',
        vaultNameValue: 'New Web Name',
        vaultHandleValue: 'VLT-NEW',
        displayNameValue: 'New Display Name',
      );
      expect(app.sessionToken, 'synthetic-new-session');
      expect(app.vaultName, 'New Web Name');
      expect(prefs.getString('session_token'), isNull);
      expect(prefs.getString('last_vault_name'), isNull);
      expect(prefs.getString('last_vault_handle'), isNull);
      expect(prefs.getString('last_display_name'), isNull);
      await NativeSecureStore.writeString('vaultai.zk.vault_handle', 'VLT-NEW');
      expect(prefs.getString('vaultai.zk.vault_handle'), isNull);

      final refreshed = AppState();
      await refreshed.hydrate();
      expect(refreshed.sessionToken, isNull);
      expect(refreshed.lastVaultName, isNull);
      expect(refreshed.vaultName, isNull);
      app.dispose();
      refreshed.dispose();
    },
  );

  test('web sign-out forgets the in-memory vault name', () async {
    if (!kIsWeb) return;
    final app = AppState();
    await app.setSession(
      token: 'synthetic-session',
      vaultIdValue: 'synthetic-vault-id',
      vaultNameValue: 'Session Only Name',
    );
    await app.clearSession(keepLastVaultName: true);
    expect(app.sessionToken, isNull);
    expect(app.lastVaultName, isNull);
    app.dispose();
  });

  testWidgets(
    'web sign-in fields do not register browser autofill credentials',
    (tester) async {
      if (!kIsWeb) return;
      final app = _ReadyApp();
      await tester.pumpWidget(
        ChangeNotifierProvider<AppState>.value(
          value: app,
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: const LoginPage(),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 50));
      final name = find.byKey(const Key('auth_vault_name_field'));
      final pin = find.byKey(const Key('auth_pin_field'));
      expect(name, findsOneWidget);
      expect(pin, findsOneWidget);
      expect(tester.widget<TextField>(name).autofillHints, isNull);
      expect(tester.widget<TextField>(pin).autofillHints, isNull);
      expect(find.byType(AutofillGroup), findsNothing);
      await tester.enterText(name, 'Synthetic Name');
      await tester.enterText(pin, '00a123');
      await tester.tap(find.byKey(const Key('auth_sign_in_button')));
      await tester.pump();
      expect(tester.widget<TextField>(pin).controller!.text, isEmpty);
      expect(find.text('PIN can only contain digits.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      app.dispose();
    },
  );

  testWidgets('web signup PIN and confirmation do not request save/autofill', (
    tester,
  ) async {
    if (!kIsWeb) return;
    final app = _ReadyApp();
    await tester.pumpWidget(
      ChangeNotifierProvider<AppState>.value(
        value: app,
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const SignupPage(),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 50));
    for (final key in <Key>[
      const Key('signup_vault_name_field'),
      const Key('signup_pin_field'),
      const Key('signup_confirm_pin_field'),
    ]) {
      expect(tester.widget<TextField>(find.byKey(key)).autofillHints, isNull);
    }
    expect(find.byType(AutofillGroup), findsNothing);
    await tester.pumpWidget(const SizedBox());
    app.dispose();
  });
}
