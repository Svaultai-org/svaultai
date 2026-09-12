import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart' as app;

const _pin = '654321';

Future<void> _waitFor(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 45),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (finder.evaluate().isEmpty && DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  expect(finder, findsWidgets);
}

Future<void> _waitForAny(
  WidgetTester tester,
  List<Finder> finders, {
  Duration timeout = const Duration(seconds: 45),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (finders.every((finder) => finder.evaluate().isEmpty) &&
      DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  expect(finders.any((finder) => finder.evaluate().isNotEmpty), isTrue);
}

Future<void> _settleNetwork(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 2));
}

Future<void> _sendChat(WidgetTester tester, String text) async {
  final composer = find.byKey(const Key('chat_composer_field'));
  await _waitFor(tester, composer);
  final readyDeadline = DateTime.now().add(const Duration(seconds: 45));
  while (tester.widget<TextField>(composer).enabled == false &&
      DateTime.now().isBefore(readyDeadline)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  expect(
    tester.widget<TextField>(composer).enabled,
    isNot(false),
    reason: 'The previous chat request must finish before the next send.',
  );
  await tester.enterText(composer, text);
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  final sendControl = find.descendant(
    of: find.byKey(const Key('composer_send_button')),
    matching: find.byType(InkWell),
  );
  final deadline = DateTime.now().add(const Duration(seconds: 30));
  while (tester.widget<InkWell>(sendControl).onTap == null &&
      DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  final send = tester.widget<InkWell>(sendControl);
  expect(send.onTap, isNotNull);
  send.onTap!();
  await tester.pump();
}

Future<void> _screenshot(
  WidgetTester tester,
  String name,
) async {
  await tester.pump(const Duration(milliseconds: 500));
  // The host wrapper captures the simulator display as soon as it sees this
  // checkpoint. This avoids the iOS 26 stale-launch-window bug in Flutter's
  // integration_test screenshot channel.
  debugPrint('SVAULTAI_SCREENSHOT_READY:$name');
  await tester.pump(const Duration(seconds: 2));
}

Future<void> _openSection(
  WidgetTester tester,
  String section,
) async {
  await tester.tap(find.byIcon(Icons.menu_rounded));
  await tester.pumpAndSettle();
  final target = find.byKey(ValueKey('sidebar_section_$section'));
  await _waitFor(tester, target);
  await tester.ensureVisible(target);
  await tester.tap(target);
  await tester.pumpAndSettle();
}

Future<void> _deleteCurrentVault(WidgetTester tester) async {
  await _openSection(tester, 'settings');
  final deleteTile = find.byKey(const Key('settings_delete_vault_tile'));
  await tester.ensureVisible(deleteTile);
  await tester.tap(deleteTile);
  await tester.pumpAndSettle();
  await tester.enterText(
    find.byKey(const Key('delete_vault_phrase_field')),
    'DELETE MY VAULT',
  );
  await tester.enterText(find.byKey(const Key('delete_vault_pin_field')), _pin);
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  final confirmButton = find.byKey(const Key('delete_vault_confirm_button'));
  await tester.ensureVisible(confirmButton);
  await tester.pumpAndSettle();
  final confirm = tester.widget<ElevatedButton>(confirmButton);
  expect(confirm.onPressed, isNotNull);
  confirm.onPressed!();
  await tester.pump();
  final deadline = DateTime.now().add(const Duration(seconds: 60));
  final errorFinder = find.byKey(const Key('delete_vault_error_text'));
  final dialogFinder = find.byKey(const Key('delete_vault_dialog'));
  while (dialogFinder.evaluate().isNotEmpty &&
      errorFinder.evaluate().isEmpty &&
      DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  if (errorFinder.evaluate().isNotEmpty) {
    final error = tester.widget<Text>(errorFinder).data ?? 'unknown error';
    fail('Temporary acceptance vault cleanup failed: $error');
  }
  expect(
    dialogFinder,
    findsNothing,
    reason: 'Delete confirmation must finish and close after backend success.',
  );
  await tester.pump(const Duration(seconds: 1));
  if (find
      .byKey(const Key('auth_landing_primary_button'))
      .evaluate()
      .isNotEmpty) {
    await tester.pump(const Duration(seconds: 2));
    if (find.byKey(const Key('auth_vault_name_field')).evaluate().isEmpty) {
      await tester.tap(find.byKey(const Key('auth_landing_primary_button')));
      await _waitFor(tester, find.byKey(const Key('auth_vault_name_field')));
    }
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'production iPhone create-save-sign-out-sign-in-retrieve-delete journey',
    (tester) async {
      final suffix = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
      final vaultName = 'acceptance$suffix';
      const displayName = 'Release Acceptance';
      const loginTitle = 'Acceptance Login';
      const memoryTitle = 'Acceptance Memory';
      const generatedLoginTitle = 'GitHub';
      const chatMemoryTitle = "Mom's birthday";
      const fileName = 'acceptance-note.txt';

      app.main();
      await _waitForAny(
        tester,
        [
          find.byKey(const Key('auth_vault_name_field')),
          find.byKey(const Key('auth_unlock_pin_field')),
          find.byKey(const Key('pin_gate_pin_field')),
          find.byKey(const Key('auth_landing_primary_button')),
        ],
      );
      if (find
          .byKey(const Key('auth_landing_primary_button'))
          .evaluate()
          .isNotEmpty) {
        await tester.pump(const Duration(seconds: 2));
        if (find.byKey(const Key('auth_vault_name_field')).evaluate().isEmpty) {
          await tester
              .tap(find.byKey(const Key('auth_landing_primary_button')));
          await _waitFor(
            tester,
            find.byKey(const Key('auth_vault_name_field')),
          );
        }
      }
      const cleanupCurrent = bool.fromEnvironment(
        'SVAULTAI_CLEANUP_CURRENT',
      );
      if (cleanupCurrent) {
        final unlockField = find.byKey(const Key('auth_unlock_pin_field'));
        final pinGateField = find.byKey(const Key('pin_gate_pin_field'));
        expect(
          unlockField.evaluate().isNotEmpty ||
              pinGateField.evaluate().isNotEmpty,
          isTrue,
          reason: 'Cleanup requires the simulator\'s remembered test vault.',
        );
        if (pinGateField.evaluate().isNotEmpty) {
          await tester.enterText(pinGateField, _pin);
          await tester.tap(find.byKey(const Key('pin_gate_submit_button')));
        } else {
          await tester.enterText(unlockField, _pin);
          await tester.tap(find.byKey(const Key('auth_unlock_button')));
        }
        await _waitFor(
          tester,
          find.byKey(const Key('chat_composer_field')),
          timeout: const Duration(seconds: 90),
        );
        await _deleteCurrentVault(tester);
        return;
      }
      const cleanupVault = String.fromEnvironment('SVAULTAI_CLEANUP_VAULT');
      if (cleanupVault.isNotEmpty) {
        await tester.enterText(
          find.byKey(const Key('auth_vault_name_field')).hitTestable(),
          cleanupVault,
        );
        await tester.enterText(
          find.byKey(const Key('auth_pin_field')).hitTestable(),
          _pin,
        );
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        final signInButton =
            find.byKey(const Key('auth_sign_in_button')).hitTestable();
        await tester.ensureVisible(signInButton);
        final signIn = tester.widget<FilledButton>(signInButton);
        expect(signIn.onPressed, isNotNull);
        signIn.onPressed!();
        await tester.pump();
        await _waitFor(
          tester,
          find.byKey(const Key('chat_composer_field')),
          timeout: const Duration(seconds: 90),
        );
        await _deleteCurrentVault(tester);
        return;
      }
      // A prior interrupted acceptance run may have left its temporary vault
      // on this simulator. Finish that run's cleanup before starting fresh.
      final rememberedUnlockField =
          find.byKey(const Key('auth_unlock_pin_field'));
      final rememberedPinGateField =
          find.byKey(const Key('pin_gate_pin_field'));
      if (rememberedUnlockField.evaluate().isNotEmpty ||
          rememberedPinGateField.evaluate().isNotEmpty) {
        if (rememberedPinGateField.evaluate().isNotEmpty) {
          await tester.enterText(rememberedPinGateField, _pin);
          await tester.tap(find.byKey(const Key('pin_gate_submit_button')));
        } else {
          await tester.enterText(rememberedUnlockField, _pin);
          await tester.tap(find.byKey(const Key('auth_unlock_button')));
        }
        await _waitFor(
          tester,
          find.byKey(const Key('chat_composer_field')),
          timeout: const Duration(seconds: 90),
        );
        await _deleteCurrentVault(tester);
      }
      await _screenshot(tester, '01-fresh-install-sign-in');

      await tester.tap(find.byKey(const Key('login_create_vault_link')).last);
      await tester.pumpAndSettle();
      await _waitFor(tester, find.byKey(const Key('signup_vault_name_field')));

      await tester.enterText(
        find.byKey(const Key('signup_vault_name_field')),
        vaultName,
      );
      await tester.enterText(
        find.byKey(const Key('signup_display_name_field')),
        displayName,
      );
      await tester.enterText(find.byKey(const Key('signup_pin_field')), _pin);
      await tester.enterText(
        find.byKey(const Key('signup_confirm_pin_field')),
        _pin,
      );
      await tester.tap(find.byKey(const Key('signup_risk_checkbox')));
      await tester.pump();
      await _screenshot(tester, '02-create-vault-completed-form');
      await tester.tap(find.byKey(const Key('signup_create_vault_button')));
      await _waitFor(
        tester,
        find.byKey(const Key('chat_composer_field')),
        timeout: const Duration(seconds: 90),
      );
      await _settleNetwork(tester);
      await _screenshot(tester, '03-new-vault-chat-ready');

      await tester.tap(find.byKey(const Key('top_nav_create_button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('create_choice_login')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_title')),
        loginTitle,
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_username')),
        'acceptance-user',
      );
      await tester.enterText(
        find.byKey(const Key('secure_item_edit_password')),
        'acceptance-password',
      );
      await tester.tap(find.byKey(const Key('secure_item_edit_save')));
      await _waitFor(tester, find.byKey(const Key('logins_page')));
      await _waitFor(tester, find.text(loginTitle));
      await _screenshot(tester, '04-login-saved-and-visible');

      await tester.tap(find.byKey(const Key('top_nav_create_button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('create_choice_memory')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('memory_dialog_title')),
        memoryTitle,
      );
      await tester.enterText(
        find.byKey(const Key('memory_dialog_value')),
        'Persistence verified on the production acceptance journey.',
      );
      await tester.tap(find.byKey(const Key('memory_dialog_save')));
      await _waitFor(tester, find.text(memoryTitle));
      await _screenshot(tester, '05-memory-saved-and-visible');

      final appState = Provider.of<app.AppState>(
        tester.element(find.byType(app.ChatDashboardPage)),
        listen: false,
      );
      final token = appState.sessionToken;
      expect(token, isNotNull);
      await VaultAIClient(baseUrl: app.backendBaseUrl).uploadVaultFile(
        vaultName: appState.vaultName!,
        pin: _pin,
        authToken: token!,
        filename: fileName,
        fileBytes: Uint8List.fromList(utf8.encode(
          'SVaultAI production acceptance file. Encrypted before storage.',
        )),
        contentType: 'text/plain',
      );
      await _openSection(tester, 'files');
      if (find.text(fileName).evaluate().isEmpty) {
        await tester.tap(find.byKey(const Key('files_empty_refresh_button')));
      }
      await _waitFor(tester, find.text(fileName));
      await _screenshot(tester, '06-file-uploaded-and-visible');

      await _openSection(tester, 'chat');
      await tester.enterText(
        find.byKey(const Key('chat_composer_field')),
        'Create me a login for GitHub',
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      final sendControl = find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      );
      final send = tester.widget<InkWell>(sendControl);
      expect(send.onTap, isNotNull);
      send.onTap!();
      await tester.pump();
      await _waitFor(
        tester,
        find.byKey(const ValueKey('chat_assistant_message_2')),
        timeout: const Duration(seconds: 90),
      );
      await _settleNetwork(tester);
      final generatedSave =
          find.byKey(const Key('vault_chat_card_generated_login_save'));
      await _waitFor(
        tester,
        generatedSave,
        timeout: const Duration(seconds: 90),
      );
      final composer = tester.widget<TextField>(
        find.byKey(const Key('chat_composer_field')),
      );
      expect(
        composer.controller?.text,
        isEmpty,
        reason: 'A successful chat send clears the composer.',
      );
      expect(find.textContaining('ClientException'), findsNothing);
      expect(find.textContaining('Error:'), findsNothing);
      await _screenshot(tester, '07-chat-generated-login-ready-to-save');

      // Exact production regression: a login generated in chat must become a
      // normal encrypted dashboard row immediately.
      await tester.ensureVisible(generatedSave);
      await tester.tap(generatedSave);
      await _waitFor(tester, find.byKey(const Key('logins_page')));
      await _waitFor(tester, find.textContaining(generatedLoginTitle));
      await _screenshot(tester, '08-chat-generated-login-saved-and-visible');

      // Exact production regression: an explicit memory saved through chat
      // must be encrypted by the client, acknowledged, and listed in Memory.
      await _openSection(tester, 'chat');
      await _sendChat(
        tester,
        'Remember my mom birthday is January 30, 1965',
      );
      await _waitFor(
        tester,
        find.textContaining('Memory saved securely.'),
        timeout: const Duration(seconds: 90),
      );
      expect(find.textContaining('could not save'), findsNothing);
      await _openSection(tester, 'memory');
      await _waitFor(tester, find.text(chatMemoryTitle));
      await _screenshot(tester, '09-chat-memory-saved-and-visible');

      await tester.tap(find.byKey(const Key('account_menu_button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('account_menu_sign_out')));
      await _waitFor(
        tester,
        find.byKey(const Key('unlock_use_another_vault_button')),
      );
      await tester.tap(
        find.byKey(const Key('unlock_use_another_vault_button')),
      );
      await _waitFor(tester, find.byKey(const Key('auth_vault_name_field')));
      await tester.enterText(
        find.byKey(const Key('auth_vault_name_field')).hitTestable(),
        vaultName,
      );
      await tester.enterText(
        find.byKey(const Key('auth_pin_field')).hitTestable(),
        _pin,
      );
      await _screenshot(tester, '10-returning-user-sign-in');
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      final signInButton =
          find.byKey(const Key('auth_sign_in_button')).hitTestable();
      await tester.ensureVisible(signInButton);
      final signIn = tester.widget<FilledButton>(signInButton);
      expect(signIn.onPressed, isNotNull);
      signIn.onPressed!();
      await tester.pump();
      await _waitFor(
        tester,
        find.byKey(const Key('chat_composer_field')),
        timeout: const Duration(seconds: 90),
      );

      await _openSection(tester, 'logins');
      await _waitFor(tester, find.text(loginTitle));
      await _waitFor(tester, find.textContaining(generatedLoginTitle));
      await _screenshot(tester, '11-logins-retrieved-after-relogin');

      await _openSection(tester, 'memory');
      await _waitFor(tester, find.text(memoryTitle));
      await _waitFor(tester, find.text(chatMemoryTitle));
      await _screenshot(tester, '12-memories-retrieved-after-relogin');

      await _openSection(tester, 'files');
      await _waitFor(tester, find.text(fileName));
      await _screenshot(tester, '13-file-retrieved-after-relogin');

      await _deleteCurrentVault(tester);
      await _screenshot(tester, '14-temporary-vault-deleted');
    },
    timeout: const Timeout(Duration(minutes: 8)),
  );
}
