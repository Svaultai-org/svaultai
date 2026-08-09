import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  print('ENSURE_INITIALIZED_COMPLETED');
  testWidgets('MemoryV2 real UI acceptance smoke', (tester) async {
    print('FIRST_TEST_BODY_ENTERED');
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    // Safe checkpoints only; never include vault, PIN, or memory values.
    void stage(String value) => print('MEMORY_QA_STAGE=$value');
    stage('STAGE_LOGIN');
    print('APP_MAIN_CALLED');
    app.main();
    print('FIRST_PUMP_ENTERED');
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
    print('AUTH_WIDGET_WAIT_ENTERED');
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
    await tester.tap(find.bySemanticsIdentifier('sidebar_section_memory'));
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

    // Logout/relogin through the real account menu; only safe lifecycle
    // checkpoints are emitted.
    expect(find.byTooltip('Account'), findsOneWidget);
    await tester.tap(find.byTooltip('Account'));
    await tester.pumpAndSettle();
    expect(find.text('Sign out'), findsOneWidget);
    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle(const Duration(seconds: 3));
    stage('STAGE_LOGOUT');

    final reloginPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
    expect(reloginPin, findsOneWidget);
    await tester.tap(reloginPin);
    await tester.enterText(reloginPin, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    stage('STAGE_RELOGIN');

    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await tester.pumpAndSettle();
    expect(
        find.bySemanticsIdentifier('sidebar_section_memory'), findsOneWidget);
    await tester.tap(find.bySemanticsIdentifier('sidebar_section_memory'));
    await tester.pumpAndSettle(const Duration(seconds: 4));
    expect(find.text('New memory'), findsOneWidget);
    final search = find.byWidgetPredicate((w) =>
        w is TextField && w.decoration?.hintText == 'Search memories...');
    expect(search, findsOneWidget);
    await tester.tap(search);
    await tester.enterText(search, 'QA Memory');
    await tester.pumpAndSettle(const Duration(seconds: 3));
    stage('STAGE_EXACT_RECALL');
    expect(find.text('QA Memory'), findsWidgets);

    // The row action is the real MemoryV2 reveal/delete UI.  Keep the
    // assertions semantic and avoid exposing the memory value.
    final reveal = find.text('Reveal').first;
    expect(reveal, findsOneWidget);
    await tester.tap(reveal);
    await tester.pumpAndSettle();
    stage('STAGE_COMPROMISE_CHECK');

    String? deleteIdentifier;
    final root = tester.binding.pipelineOwner.semanticsOwner?.rootSemanticsNode;
    bool scan(SemanticsNode node) {
      final id = node.identifier;
      if (deleteIdentifier == null && id.startsWith('qa_memory_v2_delete_')) {
        deleteIdentifier = id;
      }
      node.visitChildren(scan);
      return true;
    }

    if (root != null) scan(root);
    expect(deleteIdentifier, isNotNull);
    final deleteSemantics = find.bySemanticsIdentifier(deleteIdentifier!);
    expect(deleteSemantics, findsOneWidget);
    final deleteButtons = find.descendant(
      of: deleteSemantics,
      matching: find.byType(IconButton),
    );
    expect(deleteButtons, findsOneWidget);
    final deleteButton = tester.widget<IconButton>(deleteButtons);
    expect(deleteButton.onPressed, isNotNull);
    deleteButton.onPressed!.call();
    await tester.pumpAndSettle();
    expect(find.text('Delete'), findsWidgets);
    await tester.tap(find.text('Delete').last);
    await tester.pumpAndSettle(const Duration(seconds: 3));
    stage('STAGE_DELETE');
    FlutterError.onError = previousError;
  });
}
