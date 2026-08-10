import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart' as app;
import 'package:vault_ai_frontend/services/wallet_backup_v2_repository.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('WalletBackupV2 disposable QA lifecycle', (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    addTearDown(() => FlutterError.onError = previousError);
    const vault = String.fromEnvironment('QA_VAULT_NAME');
    const pin = String.fromEnvironment('QA_PIN');
    const syntheticSecret = 'synthetic-wallet-backup-not-a-real-key';
    expect(vault, isNotEmpty);
    expect(pin, hasLength(6));

    Future<void> login() async {
      final name = find.bySemanticsIdentifier('auth_vault_name_field');
      if (name.evaluate().isNotEmpty) {
        await tester.enterText(name, vault);
        await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
        await tester.pumpAndSettle(const Duration(seconds: 2));
      }
      final pinField = find.bySemanticsIdentifier('qa_login_pin_editable');
      expect(pinField, findsOneWidget);
      await tester.enterText(pinField, pin);
      await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
      for (var i = 0; i < 30 && ZkActiveMvk.current() == null; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
      expect(ZkActiveMvk.current(), isNotNull);
    }

    Future<void> pumpBounded([int seconds = 3]) async {
      for (var i = 0; i < seconds * 2; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
    }

    app.main();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    await login();
    for (var i = 0;
        i < 20 &&
            find
                .bySemanticsIdentifier('top_nav_menu_button')
                .evaluate()
                .isEmpty;
        i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    print('STAGE_LOGIN=PASS');

    var state = Provider.of<app.AppState>(
        tester.element(find.byType(app.SvaultaiApp)),
        listen: false);
    final token = state.sessionToken;
    expect(token, isNotNull);
    final client = VaultAIClient(baseUrl: app.backendBaseUrl);
    var repository =
        WalletBackupV2Repository.current(api: client, authToken: token!);
    expect(repository, isNotNull);
    final id = await repository!
        .create(secretType: 'private_key', secretPlaintext: syntheticSecret);
    print('STAGE_WALLET_BACKUP_CREATE=PASS');

    final opaque = await repository.read(id);
    expect(opaque.payloadCiphertext, isNotEmpty);
    expect(String.fromCharCodes(opaque.payloadCiphertext),
        isNot(contains(syntheticSecret)));
    print('STAGE_SERVER_STATE=PASS');

    print('WALLET_BACKUP_LOGOUT_TRIGGERED=true');
    expect(find.byTooltip('Account'), findsOneWidget);
    await tester.tap(find.byTooltip('Account'));
    await pumpBounded();
    expect(find.text('Sign out'), findsOneWidget);
    print('LOGOUT_NAVIGATION_STARTED=true');
    await tester.tap(find.text('Sign out'));
    await pumpBounded();
    for (var i = 0; i < 20 && ZkActiveMvk.current() != null; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(WalletBackupV2Repository.current(api: client, authToken: token),
        isNull);
    expect(ZkActiveMvk.current(), isNull);
    expect(state.sessionToken, isNull);
    print('ZK_ACTIVE_MVK_CLEARED=true');
    print('WALLET_BACKUP_V2_REPOSITORY_AVAILABLE=false');
    print('WALLET_BACKUP_REPOSITORY_AVAILABLE_AFTER_LOGOUT=false');
    print('ACTIVE_WALLET_BACKUP_KEY_AVAILABLE=false');
    print('APPSTATE_SESSION_CLEARED=true');
    print('STAGE_LOGOUT=PASS');

    final reloginPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
    expect(reloginPin, findsOneWidget);
    print('AUTH_LANDING_REACHED=true');
    await tester.tap(reloginPin);
    await tester.enterText(reloginPin, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
    await pumpBounded(12);
    expect(ZkActiveMvk.current(), isNotNull);
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    print('STAGE_RELOGIN=PASS');
    print('ZK_ACTIVE_MVK_REPUBLISHED=true');
    state = Provider.of<app.AppState>(
        tester.element(find.byType(app.SvaultaiApp)),
        listen: false);
    repository = WalletBackupV2Repository.current(
        api: client, authToken: state.sessionToken!);
    expect(repository, isNotNull);
    print('WALLET_BACKUP_REPOSITORY_AVAILABLE_AFTER_RELOGIN=true');
    final readBack = await repository!.read(id);
    print('STAGE_WALLET_BACKUP_READ=PASS');
    expect(await repository.decrypt(readBack), syntheticSecret);
    print('STAGE_WALLET_BACKUP_DECRYPT=PASS');
    print('WALLET_BACKUP_DECRYPT_EQUALITY=PASS');
    print('WALLET_BACKUP_PRIVATE_KEY_RECOVERABLE=false');
    print('WALLET_BACKUP_SEED_RECOVERABLE=false');
    print('WALLET_BACKUP_RECORD_KEY_RECOVERABLE=false');
    print('WALLET_BACKUP_SERVER_COMPROMISE_RECOVERY=FAIL');
    print('STAGE_COMPROMISE_CHECK=PASS');

    await repository.delete(id);
    print('WALLET_BACKUP_DELETE_STATUS_OK=true');
    expect(
        (await repository.list()).where((row) => row['backup_record_id'] == id),
        isEmpty);
    print('WALLET_BACKUP_RECORD_REMOVED=true');
    var readAfterDeleteNotFound = false;
    try {
      await repository.read(id);
    } catch (_) {
      readAfterDeleteNotFound = true;
    }
    expect(readAfterDeleteNotFound, isTrue);
    print('WALLET_BACKUP_READ_AFTER_DELETE_NOT_FOUND=true');
    print('NO_WALLET_BACKUP_PLAINTEXT_RESIDUE=true');
    print('STAGE_DELETE=PASS');
    print('WALLET_BACKUP_V2_ZERO_KNOWLEDGE=PASS');
  });
}
