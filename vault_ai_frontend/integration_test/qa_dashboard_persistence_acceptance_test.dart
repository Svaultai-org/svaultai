import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
      'new vault keeps login and memory visible after sign out and relogin',
      (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };

    // These values belong only to the temporary QA vault. Never print them.
    final suffix = DateTime.now().millisecondsSinceEpoch.toString();
    final vaultName = 'qa-dashboard-${suffix.substring(suffix.length - 10)}';
    const pin = '847261';
    const existingVault = String.fromEnvironment('QA_VAULT_NAME');
    const existingPin = String.fromEnvironment('QA_PIN');
    final usesExistingVault =
        existingVault.isNotEmpty && existingPin.isNotEmpty;
    final activeVaultName = usesExistingVault ? existingVault : vaultName;
    final activePin = usesExistingVault ? existingPin : pin;
    final loginTitle = 'QA Login ${suffix.substring(suffix.length - 6)}';
    final memoryTitle = 'QA Memory ${suffix.substring(suffix.length - 6)}';

    void stage(String value) => print('DASHBOARD_QA_STAGE=$value');

    Future<void> openSidebarSection(String identifier) async {
      await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
      await tester.pumpAndSettle();
      final target = find.bySemanticsIdentifier(identifier);
      expect(target, findsOneWidget);
      await tester.ensureVisible(target);
      await tester.tap(target);
      await tester.pumpAndSettle(const Duration(seconds: 3));
    }

    Future<void> waitForDashboard() async {
      for (var i = 0;
          i < 30 &&
              find
                  .bySemanticsIdentifier('top_nav_menu_button')
                  .evaluate()
                  .isEmpty;
          i++) {
        await tester.pump(const Duration(seconds: 1));
      }
      expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    }

    Future<void> waitForText(String value) async {
      for (var i = 0; i < 30 && find.text(value).evaluate().isEmpty; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
      expect(find.text(value), findsWidgets);
    }

    final loginCards = find.byWidgetPredicate((widget) =>
        widget.key?.toString().contains('secure_item_card_') == true);

    Future<void> signOutAndRelogin() async {
      expect(find.byTooltip('Account'), findsOneWidget);
      await tester.tap(find.byTooltip('Account'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle(const Duration(seconds: 3));
      stage('SIGN_OUT_OK');

      final unlockPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
      expect(unlockPin, findsOneWidget);
      await tester.tap(unlockPin);
      await tester.enterText(unlockPin, activePin);
      await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
      await tester.pumpAndSettle(const Duration(seconds: 15));
      await waitForDashboard();
      stage('RELOGIN_OK');
    }

    Future<void> assertExistingInventoriesLoad() async {
      await openSidebarSection('sidebar_section_logins');
      for (var i = 0; i < 20 && loginCards.evaluate().isEmpty; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
      expect(find.textContaining('Could not load saved logins'), findsNothing);
      expect(loginCards, findsWidgets,
          reason: 'known_saved_login_missing_from_dashboard');
      stage('EXISTING_LOGIN_INVENTORY_VISIBLE');

      await openSidebarSection('sidebar_section_memory');
      await tester.pump(const Duration(seconds: 5));
      expect(find.textContaining('Could not load memory'), findsNothing,
          reason: 'memory_inventory_failed_to_load');
      stage('EXISTING_MEMORY_INVENTORY_LOADED');
    }

    app.main();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    for (var i = 0;
        i < 20 &&
            find.byKey(const Key('auth_vault_name_field')).evaluate().isEmpty &&
            find
                .bySemanticsIdentifier('auth_unlock_pin_field')
                .evaluate()
                .isEmpty;
        i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }

    if (usesExistingVault) {
      stage('EXISTING_VAULT_LOGIN_START');
      final rememberedPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
      if (rememberedPin.evaluate().isNotEmpty) {
        await tester.tap(rememberedPin);
        await tester.enterText(rememberedPin, activePin);
        await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
      } else {
        final vaultField = find.byKey(const Key('auth_vault_name_field'));
        final pinField = find.byKey(const Key('auth_pin_field'));
        expect(vaultField, findsOneWidget);
        expect(pinField, findsOneWidget);
        tester.widget<TextField>(vaultField).controller!.text = activeVaultName;
        tester.widget<TextField>(pinField).controller!.text = activePin;
        await tester.pump();
        await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
      }
      await tester.pumpAndSettle(const Duration(seconds: 15));
      await waitForDashboard();
      final state = Provider.of<app.AppState>(
        tester.element(find.byType(MaterialApp).first),
        listen: false,
      );
      print('DASHBOARD_QA_WRITES_ALLOWED=${state.billingWritesAllowed}');
      print('DASHBOARD_QA_BILLING_STATE=${state.billingLoadState.name}');
      stage('EXISTING_VAULT_LOGIN_OK');
      if (!state.billingWritesAllowed) {
        await assertExistingInventoriesLoad();
        await signOutAndRelogin();
        await assertExistingInventoriesLoad();
        stage('READ_ONLY_ACCOUNT_REHYDRATION_OK');
        FlutterError.onError = previousError;
        return;
      }
    } else {
      stage('CREATE_VAULT_START');
      final createLink = find.bySemanticsIdentifier('qa_create_vault_link');
      expect(createLink, findsOneWidget);
      await tester.tap(createLink);
      await tester.pumpAndSettle();
      await tester.enterText(
          find.bySemanticsIdentifier('qa_create_vault_name_field'), vaultName);
      await tester.enterText(
          find.bySemanticsIdentifier('qa_create_vault_pin_field'), pin);
      await tester.enterText(
          find.bySemanticsIdentifier('qa_create_vault_confirm_pin_field'), pin);
      await tester.tap(find.bySemanticsIdentifier('qa_create_vault_consent'));
      await tester.tap(find.bySemanticsIdentifier('qa_create_vault_submit'));
      await tester.pumpAndSettle(const Duration(seconds: 15));
      await waitForDashboard();
      stage('CREATE_VAULT_OK');
    }

    stage('CREATE_LOGIN_START');
    await tester.tap(find.byKey(const Key('top_nav_create_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('create_choice_login')));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('secure_item_edit_title')), loginTitle);
    await tester.enterText(
        find.byKey(const Key('secure_item_edit_username')), 'qa-user');
    await tester.enterText(
        find.byKey(const Key('secure_item_edit_password')), 'qa-pass-847261');
    await tester.tap(find.byKey(const Key('secure_item_edit_save')));
    await tester.pumpAndSettle(const Duration(seconds: 8));
    await waitForText(loginTitle);
    stage('CREATE_LOGIN_VISIBLE');

    stage('CREATE_MEMORY_START');
    await tester.tap(find.byKey(const Key('top_nav_create_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('create_choice_memory')));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('memory_dialog_title')), memoryTitle);
    await tester.enterText(find.byKey(const Key('memory_dialog_value')),
        'QA-only synthetic persistence check');
    await tester.tap(find.text('Save').last);
    await tester.pumpAndSettle(const Duration(seconds: 8));
    await waitForText(memoryTitle);
    stage('CREATE_MEMORY_VISIBLE');

    await signOutAndRelogin();

    await openSidebarSection('sidebar_section_logins');
    await waitForText(loginTitle);
    stage('LOGIN_REHYDRATED');

    final loginTitleElement = find.text(loginTitle).evaluate().first;
    Element? loginCardElement = loginTitleElement;
    while (loginCardElement != null &&
        !(loginCardElement.widget.key
                ?.toString()
                .contains('secure_item_card_') ??
            false)) {
      loginCardElement = loginCardElement._parentForQA;
    }
    expect(loginCardElement, isNotNull);
    final loginCard = find.byKey(loginCardElement!.widget.key!);
    final loginDelete = find.descendant(
      of: loginCard,
      matching: find.widgetWithText(OutlinedButton, 'Delete'),
    );
    expect(loginDelete, findsOneWidget);
    await tester.tap(loginDelete);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete').last);
    await tester.pumpAndSettle(const Duration(seconds: 4));
    expect(find.text(loginTitle), findsNothing);
    stage('LOGIN_CLEANUP_OK');

    await openSidebarSection('sidebar_section_memory');
    await waitForText(memoryTitle);
    stage('MEMORY_REHYDRATED');

    // Delete the temporary memory via its row semantics.
    String? memoryDeleteIdentifier;
    final root = tester.binding.pipelineOwner.semanticsOwner?.rootSemanticsNode;
    bool scan(SemanticsNode node) {
      if (memoryDeleteIdentifier == null &&
          node.identifier.startsWith('qa_memory_v2_delete_')) {
        memoryDeleteIdentifier = node.identifier;
      }
      node.visitChildren(scan);
      return true;
    }

    if (root != null) scan(root);
    expect(memoryDeleteIdentifier, isNotNull);
    final memoryDelete = find.bySemanticsIdentifier(memoryDeleteIdentifier!);
    final memoryDeleteButton = find.descendant(
      of: memoryDelete,
      matching: find.byType(IconButton),
    );
    final deleteWidget = tester.widget<IconButton>(memoryDeleteButton);
    deleteWidget.onPressed!.call();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete').last);
    await tester.pumpAndSettle(const Duration(seconds: 4));
    expect(find.text(memoryTitle), findsNothing);
    stage('MEMORY_CLEANUP_OK');

    if (!usesExistingVault) {
      // Permanently delete the temporary vault so the production backend is
      // returned to its pre-test state.
      await openSidebarSection('sidebar_section_settings');
      final deleteTile = find.byKey(const Key('settings_delete_vault_tile'));
      expect(deleteTile, findsOneWidget);
      await tester.ensureVisible(deleteTile);
      await tester.tap(deleteTile);
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('delete_vault_phrase_field')),
          kDeleteVaultConfirmationPhrase);
      await tester.enterText(
          find.byKey(const Key('delete_vault_pin_field')), activePin);
      await tester.tap(find.byKey(const Key('delete_vault_confirm_button')));
      await tester.pumpAndSettle(const Duration(seconds: 8));
      expect(
          find.bySemanticsIdentifier('auth_vault_name_field'), findsOneWidget);
      stage('TEMP_VAULT_DELETED');
    } else {
      stage('EXISTING_VAULT_LEFT_INTACT');
    }

    FlutterError.onError = previousError;
  });
}

extension on Element {
  Element? get _parentForQA {
    Element? parent;
    visitAncestorElements((ancestor) {
      parent = ancestor;
      return false;
    });
    return parent;
  }
}
