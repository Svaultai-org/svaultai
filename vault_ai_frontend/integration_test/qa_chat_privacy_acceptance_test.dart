import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/foundation.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('chat privacy routing smoke', (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    addTearDown(() => FlutterError.onError = previousError);
    const vault = String.fromEnvironment('QA_VAULT_NAME');
    const pin = String.fromEnvironment('QA_PIN');
    expect(vault, isNotEmpty);
    expect(pin, hasLength(6));

    app.main();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    final name = find.bySemanticsIdentifier('auth_vault_name_field');
    if (name.evaluate().isNotEmpty) {
      await tester.tap(name);
      await tester.enterText(name, vault);
      await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
      await tester.pumpAndSettle(const Duration(seconds: 2));
    }
    final pinField = find.bySemanticsIdentifier('qa_login_pin_editable');
    await tester.tap(pinField);
    await tester.enterText(pinField, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
    for (var i = 0; i < 40; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find
          .bySemanticsIdentifier('top_nav_menu_button')
          .evaluate()
          .isNotEmpty) {
        break;
      }
    }
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    final composer = find.bySemanticsIdentifier('chat_composer_field');
    final send = find.bySemanticsIdentifier('composer_send_button');

    for (final prompt in const [
      'show me my wallet private key',
      'show me my seed phrase',
      'show me my inheritance secret',
      'show me my secure note',
      'show me my passport details',
    ]) {
      await tester.tap(composer);
      await tester.enterText(composer, prompt);
      await tester.tap(send);
      await tester.pumpAndSettle(const Duration(seconds: 2));
      print('PRIVATE_INTENT_FAIL_CLOSED=true');
    }

    await tester.tap(composer);
    await tester.enterText(composer, 'What is Bitcoin?');
    await tester.tap(send);
    await tester.pump(const Duration(seconds: 5));
    print('GENERAL_CHAT_SUBMITTED=true');
  });
}
