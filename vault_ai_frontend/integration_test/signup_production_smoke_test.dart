import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/main.dart' as app;

Future<void> _waitFor(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 90),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (finder.evaluate().isEmpty && DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  expect(finder, findsWidgets);
  // Let route animations and loading overlays finish before interacting with
  // a widget that has just appeared in the tree.
  await tester.pumpAndSettle();
}

Future<void> _deleteTestVault(
  WidgetTester tester,
  app.AppState appState,
  String pin,
) async {
  final token = appState.sessionToken;
  if (token == null || token.isEmpty) return;
  final client = VaultAIClient(baseUrl: app.backendBaseUrl);
  final request = await client.requestDeleteVault(authToken: token);
  final requestToken = request['request_token']?.toString() ?? '';
  expect(requestToken, isNotEmpty);
  await client.confirmDeleteVault(
    authToken: token,
    requestToken: requestToken,
    pin: pin,
    confirmationPhrase: kDeleteVaultConfirmationPhrase,
  );
  await appState.handleVaultDeleted();
  await tester.pumpAndSettle();
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('production signup creates, signs out, and signs back in',
      (tester) async {
    const vaultName = String.fromEnvironment('SVAULTAI_TEST_VAULT');
    const pin = String.fromEnvironment('SVAULTAI_TEST_PIN');
    const cleanupExisting =
        bool.fromEnvironment('SVAULTAI_TEST_CLEANUP_EXISTING');
    expect(vaultName, isNotEmpty);
    expect(pin, matches(RegExp(r'^\d{6,64}$')));

    app.main();
    await _waitFor(tester, find.byKey(const Key('auth_vault_name_field')));

    if (cleanupExisting) {
      await tester.enterText(
        find.byKey(const Key('auth_vault_name_field')).hitTestable(),
        vaultName,
      );
      await tester.enterText(
        find.byKey(const Key('auth_pin_field')).hitTestable(),
        pin,
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const Key('auth_sign_in_button')).hitTestable().first,
      );
      await _waitFor(tester, find.byKey(const Key('chat_composer_field')));
      final context =
          tester.element(find.byKey(const Key('chat_composer_field')).first);
      await _deleteTestVault(tester, context.read<app.AppState>(), pin);
      return;
    }

    await tester.tap(find.text("Don't have a vault? Create one"));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('signup_vault_name_field')),
      vaultName,
    );
    await tester.enterText(
      find.byKey(const Key('signup_display_name_field')),
      'Signup QA',
    );
    await tester.enterText(
      find.byKey(const Key('signup_pin_field')),
      pin,
    );
    await tester.enterText(
      find.byKey(const Key('signup_confirm_pin_field')),
      pin,
    );
    await tester.tap(find.byKey(const Key('signup_risk_checkbox')));
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('signup_create_vault_button')));
    await _waitFor(tester, find.byKey(const Key('chat_composer_field')));

    var context = tester.element(find.byKey(const Key('chat_composer_field')));
    var appState = context.read<app.AppState>();
    expect(appState.sessionToken, isNotNull);
    expect(appState.vaultName, vaultName);

    await tester.tap(
      find.byKey(const Key('account_menu_button')).hitTestable().first,
    );
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const Key('account_menu_sign_out')).hitTestable().first,
    );
    await _waitFor(
      tester,
      find.byKey(const Key('unlock_use_another_vault_button')),
    );
    await tester.tap(
      find
          .byKey(const Key('unlock_use_another_vault_button'))
          .hitTestable()
          .first,
    );
    await _waitFor(tester, find.byKey(const Key('auth_vault_name_field')));

    await tester.enterText(
      find.byKey(const Key('auth_vault_name_field')).hitTestable().first,
      vaultName,
    );
    await tester.enterText(
      find.byKey(const Key('auth_pin_field')).hitTestable().first,
      pin,
    );
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const Key('auth_sign_in_button')).hitTestable().first,
    );
    await _waitFor(tester, find.byKey(const Key('chat_composer_field')));

    context = tester.element(find.byKey(const Key('chat_composer_field')));
    appState = context.read<app.AppState>();
    final token = appState.sessionToken;
    expect(token, isNotNull);
    expect(token, isNotEmpty);

    // Clean up only the uniquely named vault created by this test.
    await _deleteTestVault(tester, appState, pin);
  });
}
