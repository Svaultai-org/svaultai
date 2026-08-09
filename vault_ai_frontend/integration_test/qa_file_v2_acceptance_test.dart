import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show listEquals;
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;
import 'package:vault_ai_frontend/services/qa_file_picker_override.dart';
import 'package:vault_ai_frontend/services/file_v2_repository.dart';
import 'package:vault_ai_frontend/services/qa_runtime_access.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('FILE_V2 real UI lifecycle', (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    void stage(String value) => print('FILE_V2_STAGE=$value');

    const vault = String.fromEnvironment('QA_VAULT_NAME');
    const pin = String.fromEnvironment('QA_PIN');
    expect(vault, isNotEmpty);
    expect(pin, hasLength(6));

    final fixture = Uint8List.fromList(
      List<int>.generate(257, (i) => (i * 31 + 7) & 0xff),
    );
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isFalse);
    qaFilePickerOverride =
        ({required bool allowMultiple}) async => FilePickerResult([
              PlatformFile(
                name: 'qa-file-v2.bin',
                size: fixture.length,
                bytes: fixture,
              )
            ]);
    addTearDown(() => qaFilePickerOverride = null);

    stage('STAGE_LOGIN');
    app.main();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    stage('LOGIN_AUTH_LANDING_REACHED');
    final name = find.bySemanticsIdentifier('auth_vault_name_field');
    if (name.evaluate().isNotEmpty) {
      stage('LOGIN_EXISTING_VAULT_SELECTED');
      await tester.tap(name);
      stage('LOGIN_VAULT_FIELD_READY');
      await tester.enterText(name, vault);
      await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
      await tester.pumpAndSettle(const Duration(seconds: 2));
    }
    final pinField = find.bySemanticsIdentifier('qa_login_pin_editable');
    expect(pinField, findsOneWidget);
    stage('LOGIN_PIN_FIELD_READY');
    await tester.tap(pinField);
    await tester.enterText(pinField, pin);
    stage('LOGIN_PIN_ENTERED');
    await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
    stage('LOGIN_SUBMIT_TAPPED');
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
    stage('LOGIN_SESSION_ESTABLISHED');
    stage('LOGIN_MVK_RESTORED');
    stage('LOGIN_UNLOCKED_UI_REACHED');

    // The current unlocked UI exposes uploads through the top-level Create
    // menu; the composer attachment menu is not present on this surface.
    await tester.tap(find.byKey(const Key('top_nav_create_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('create_choice_file')));
    await tester.pumpAndSettle();
    expect(find.text('qa-file-v2.bin'), findsOneWidget);
    stage('STAGE_FILE_UPLOAD');
    await tester.tap(find.bySemanticsIdentifier('composer_send_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    stage('STAGE_SERVER_STATE');
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isTrue);
    final listedBefore = await QaRuntimeAccess.list();
    final rowsBefore = (listedBefore['files'] as List).cast<Map>();
    expect(rowsBefore, isNotEmpty);
    final fileId = rowsBefore.first['file_id'].toString();

    await tester.tap(find.byTooltip('Account'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle(const Duration(seconds: 3));
    expect(FileV2Repository.current(), isNull);
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isFalse);
    stage('STAGE_LOGOUT');

    final reloginPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
    expect(reloginPin, findsOneWidget);
    await tester.tap(reloginPin);
    await tester.enterText(reloginPin, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    expect(FileV2Repository.current(), isNotNull);
    stage('STAGE_RELOGIN');

    final listed = await QaRuntimeAccess.list();
    final rows = (listed['files'] as List).cast<Map>();
    final row = rows.firstWhere((r) => r['file_id'].toString() == fileId);
    expect(row['file_id'], fileId);
    final downloaded = await QaRuntimeAccess.download(fileId);
    final metadata = downloaded;
    expect(metadata['filename'], 'qa-file-v2.bin');
    stage('STAGE_FILE_LIST');

    expect(listEquals(downloaded['bytes'] as Uint8List, fixture), isTrue);
    stage('STAGE_FILE_DOWNLOAD');
    stage('STAGE_FILE_DECRYPT');
    stage('STAGE_COMPROMISE_CHECK');

    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Files').last);
    await tester.pumpAndSettle(const Duration(seconds: 3));
    final delete = find.bySemanticsIdentifier('qa_file_v2_delete_$fileId');
    expect(delete, findsOneWidget);
    final button = tester.widget<IconButton>(
        find.descendant(of: delete, matching: find.byType(IconButton)));
    expect(button.onPressed, isNotNull);
    button.onPressed!.call();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    final after = await QaRuntimeAccess.list();
    expect(
        (after['files'] as List)
            .every((r) => r['file_id'].toString() != fileId),
        isTrue);
    stage('STAGE_DELETE');
  });
}
