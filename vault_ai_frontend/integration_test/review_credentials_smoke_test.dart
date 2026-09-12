import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
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
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('production review credentials open a usable vault',
      (tester) async {
    const vaultName = String.fromEnvironment('SVAULTAI_REVIEW_VAULT');
    const pin = String.fromEnvironment('SVAULTAI_REVIEW_PIN');
    expect(vaultName, isNotEmpty);
    expect(pin, isNotEmpty);

    app.main();
    await _waitFor(
      tester,
      find.byKey(const Key('auth_vault_name_field')),
    );
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
    final signInButton =
        find.byKey(const Key('auth_sign_in_button')).hitTestable();
    final signIn = tester.widget<FilledButton>(signInButton);
    expect(signIn.onPressed, isNotNull);
    signIn.onPressed!();
    await tester.pump();

    await _waitFor(
      tester,
      find.byKey(const Key('chat_composer_field')),
    );
    final accountMenu =
        find.byKey(const Key('account_menu_button')).hitTestable();
    expect(accountMenu, findsOneWidget);

    await tester.tap(accountMenu);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('account_menu_sign_out')));
    await _waitFor(
      tester,
      find.byKey(const Key('unlock_use_another_vault_button')),
    );
  });
}
