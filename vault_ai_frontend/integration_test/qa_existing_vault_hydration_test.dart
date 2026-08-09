import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/foundation.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('authenticated QA hydration', (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
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
    final pinField = find.byKey(const ValueKey('auth_pin_field'));
    expect(pinField, findsOneWidget);
    await tester.tap(pinField);
    await tester.enterText(pinField, pin);
    await tester.pumpAndSettle(const Duration(milliseconds: 300));
    await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.bySemanticsIdentifier('sidebar_section_logins'));
    await tester.pumpAndSettle(const Duration(seconds: 5));
    final diag = find.bySemanticsIdentifier(
      'qa_v2_hydration_diag_generated-1d1c9d799b70b2c919d2cb558bec682f',
    );
    expect(diag, findsOneWidget);
    final semantics = tester.getSemantics(diag);
    // Only safe diagnostic text is emitted; it contains booleans and categories.
    // ignore: avoid_print
    print('QA_HYDRATION_DIAGNOSTIC=${semantics.label}');
    FlutterError.onError = previousError;
  });
}
