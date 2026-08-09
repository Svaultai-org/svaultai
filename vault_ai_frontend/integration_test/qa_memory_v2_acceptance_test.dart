import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('MemoryV2 real UI acceptance smoke', (tester) async {
    app.main();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    const vault = String.fromEnvironment('QA_VAULT_NAME');
    const pin = String.fromEnvironment('QA_PIN');
    expect(vault, isNotEmpty);
    expect(pin, hasLength(6));
    final name = find.bySemanticsIdentifier('auth_vault_name_field');
    if (name.evaluate().isNotEmpty) {
      await tester.tap(name);
      await tester.enterText(name, vault);
      await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
      await tester.pumpAndSettle(const Duration(seconds: 2));
    }
    final pinField = find.bySemanticsIdentifier('qa_login_pin_editable');
    expect(pinField, findsOneWidget);
    await tester.tap(pinField);
    await tester.enterText(pinField, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Memory').last);
    await tester.pumpAndSettle(const Duration(seconds: 4));
    await tester.tap(find.text('New memory'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('memory_dialog_title')), 'QA Memory');
    await tester.enterText(find.byKey(const Key('memory_dialog_value')),
        'QA-only synthetic memory');
    await tester.tap(find.text('Save').last);
    await tester.pumpAndSettle(const Duration(seconds: 4));
    expect(find.text('Memory saved'), findsOneWidget);
  });
}
