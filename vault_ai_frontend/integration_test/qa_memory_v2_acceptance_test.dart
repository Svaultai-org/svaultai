import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('MemoryV2 real UI acceptance smoke', (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    // Safe checkpoints only; never include vault, PIN, or memory values.
    void stage(String value) => print('MEMORY_QA_STAGE=$value');
    stage('STAGE_LOGIN');
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
    for (var i = 0;
        i < 10 &&
            find
                .bySemanticsIdentifier('top_nav_menu_button')
                .evaluate()
                .isEmpty;
        i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    stage('STAGE_MEMORY_PAGE');
    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Memory').last);
    await tester.pumpAndSettle(const Duration(seconds: 4));
    await tester.tap(find.text('New memory'));
    await tester.pumpAndSettle();
    stage('STAGE_MEMORY_CREATE');
    await tester.enterText(
        find.byKey(const Key('memory_dialog_title')), 'QA Memory');
    await tester.enterText(find.byKey(const Key('memory_dialog_value')),
        'QA-only synthetic memory');
    await tester.tap(find.text('Save').last);
    await tester.pumpAndSettle(const Duration(seconds: 4));
    expect(find.text('Memory saved'), findsOneWidget);
    stage('STAGE_SERVER_STATE');
    FlutterError.onError = previousError;
  });
}
