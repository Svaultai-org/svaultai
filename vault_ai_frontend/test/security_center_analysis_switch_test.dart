import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/security_center_page.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    ZkActiveMvk.clear();
  });
  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    ZkActiveMvk.clear();
  });

  testWidgets('losing the private key while warning is open never asks for PIN',
      (tester) async {
    final app = AppState();
    await app.setSession(
      token: 'synthetic-legacy-session',
      vaultIdValue: 'synthetic-vault',
      vaultNameValue: 'Synthetic vault',
    );
    app.markUnlocked();
    app.vaultHandle = 'synthetic-opaque-handle';
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 17)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-opaque-handle',
    );
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        if (request.url.path == '/security-center/summary') {
          return http.Response('{}', 200);
        }
        // The local inventory is deliberately unavailable. The UI must show
        // an incomplete check rather than retrying the old PIN route.
        return http.Response('{}', 503);
      }),
    );
    await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: AppLocalizations.supportedLocales,
        home: SecurityCenterPage(client: client),
      ),
    ));
    await tester.pumpAndSettle();
    final button = find.text('Analyze all passwords');
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.textContaining('Passwords and the check results stay on this device'),
        findsOneWidget);

    ZkActiveMvk.clear();
    final continueButton = find.descendant(
      of: find.byType(AlertDialog),
      matching: find.byType(FilledButton),
    );
    await tester.tap(continueButton);
    await tester.pumpAndSettle();

    expect(find.textContaining('Enter vault PIN'), findsNothing);
    expect(sent.any((r) => r.url.path ==
        '/security-center/analyze-passwords'), isFalse);
    expect(sent.every((r) => !r.body.contains('"pin"')), isTrue);
    await tester.pumpWidget(const SizedBox.shrink());
    app.dispose();
  });

  test('active private key fences password analysis at outbound boundary', () {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 19)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'synthetic-opaque-handle',
    );
    expect(
      () => assertOutboundPinFreeRequest(
        Uri.parse('https://synthetic.example/security-center/analyze-passwords'),
        const <String, String>{},
        body: jsonEncode({'pin': '123456', 'cursor': 0}),
      ),
      throwsStateError,
    );
  });
}
