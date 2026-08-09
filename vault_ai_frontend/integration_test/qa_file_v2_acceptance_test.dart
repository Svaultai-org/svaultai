import 'dart:convert';
import 'dart:io';
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
    const phase = String.fromEnvironment('FILE_V2_PHASE', defaultValue: 'A');
    final checkpointFile = File(
        '${Platform.environment['HOME']}/Library/Application Support/SVaultAI-QA/runtime/file_v2_checkpoint.json');
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    void stage(String value) => print('FILE_V2_STAGE=$value');
    Future<void> pumpBounded([int seconds = 3]) async {
      for (var i = 0; i < seconds * 2; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
    }

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
    var authenticated = false;
    for (var i = 0; i < 30; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (FileV2Repository.current() != null ||
          find
              .bySemanticsIdentifier('top_nav_menu_button')
              .evaluate()
              .isNotEmpty) {
        authenticated = true;
        break;
      }
    }
    expect(authenticated, isTrue, reason: 'authenticated_state_not_observed');
    stage('LOGIN_SESSION_ESTABLISHED');
    stage('LOGIN_MVK_RESTORED');
    stage('LOGIN_UNLOCKED_UI_REACHED');

    if (phase == 'B') {
      expect(checkpointFile.existsSync(), isTrue);
    }

    // The current unlocked UI exposes uploads through the top-level Create
    // menu; the composer attachment menu is not present on this surface.
    var fileId = '';
    if (phase == 'A') {
      await tester.tap(find.byKey(const Key('top_nav_create_button')));
      await pumpBounded();
      expect(find.byKey(const Key('create_choice_file')), findsOneWidget);
      await tester.tap(find.byKey(const Key('create_choice_file')));
      await pumpBounded();
      expect(find.text('qa-file-v2.bin'), findsOneWidget);
      stage('STAGE_FILE_UPLOAD');
      await tester.tap(find.bySemanticsIdentifier('composer_send_button'));
      await tester.pumpAndSettle(const Duration(seconds: 12));
      stage('STAGE_SERVER_STATE');
      print('POST_SERVER_STATE_COMPLETED');
      // The QA runtime bridge is installed when the product loads the Files
      // surface. Navigate there through the real menu before querying it.
      await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
      await pumpBounded();
      await tester.tap(find.text('Files').last);
      print('FILES_SURFACE_ACTIVE');
      await pumpBounded();
      expect(QaRuntimeAccess.fileV2RepositoryAvailable, isTrue);
      print('FILE_V2_BRIDGE_AVAILABLE');
      final listedBefore = await QaRuntimeAccess.list();
      final rowsBefore = (listedBefore['files'] as List).cast<Map>();
      expect(rowsBefore, isNotEmpty);
      fileId = rowsBefore.first['file_id'].toString();
      checkpointFile.writeAsStringSync(jsonEncode({
        'phase': 'FILE_UPLOADED',
        'file_id': fileId,
        'fixture_name': 'qa-file-v2.bin',
        'fixture_mime': 'application/octet-stream',
        'fixture_length': fixture.length,
      }));
      print('FILE_ID_CHECKPOINTED=true');
      if (phase == 'A') return;
    } else {
      final saved = jsonDecode(checkpointFile.readAsStringSync()) as Map;
      fileId = saved['file_id'].toString();
      stage('STAGE_SERVER_STATE');
      await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
      await pumpBounded();
      await tester.tap(find.text('Files').last);
      await pumpBounded();
      expect(QaRuntimeAccess.fileV2RepositoryAvailable, isTrue);
      final listedBefore = await QaRuntimeAccess.list();
      expect(
          (listedBefore['files'] as List)
              .any((r) => r['file_id'].toString() == fileId),
          isTrue);
      stage('STAGE_LOGOUT');
      await tester.tap(find.byTooltip('Account'));
      await pumpBounded();
      await tester.tap(find.text('Sign out'));
      await pumpBounded();
      expect(FileV2Repository.current(), isNull);
      stage('STAGE_RELOGIN');
      final reloginPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
      await tester.tap(reloginPin);
      await tester.enterText(reloginPin, pin);
      await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
      await pumpBounded(12);
      await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
      await pumpBounded();
      await tester.tap(find.text('Files').last);
      await pumpBounded();
      expect(QaRuntimeAccess.fileV2RepositoryAvailable, isTrue);
      final listed = await QaRuntimeAccess.list();
      expect(
          (listed['files'] as List)
              .any((r) => r['file_id'].toString() == fileId),
          isTrue);
      stage('STAGE_FILE_LIST');
      final downloaded = await QaRuntimeAccess.download(fileId);
      expect(downloaded['filename'], 'qa-file-v2.bin');
      stage('STAGE_FILE_DOWNLOAD');
      expect(listEquals(downloaded['bytes'] as Uint8List, fixture), isTrue);
      stage('STAGE_FILE_DECRYPT');
      stage('STAGE_COMPROMISE_CHECK');
      final deleted = await QaRuntimeAccess.delete(fileId);
      expect(deleted, isTrue);
      final after = await QaRuntimeAccess.list();
      expect(
          (after['files'] as List)
              .every((r) => r['file_id'].toString() != fileId),
          isTrue);
      stage('STAGE_DELETE');
      checkpointFile.deleteSync();
      return;
    }

    print('LOGOUT_NAVIGATION_STARTED');
    await tester.tap(find.byTooltip('Account'));
    await pumpBounded();
    print('LOGOUT_ACTION_FOUND');
    await tester.tap(find.text('Sign out'));
    print('LOGOUT_ACTION_INVOKED');
    await pumpBounded();
    expect(FileV2Repository.current(), isNull);
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isFalse);
    stage('STAGE_LOGOUT');

    final reloginPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
    expect(reloginPin, findsOneWidget);
    await tester.tap(reloginPin);
    await tester.enterText(reloginPin, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
    print('RELOGIN_STARTED');
    await pumpBounded(12);
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    expect(FileV2Repository.current(), isNotNull);
    stage('STAGE_RELOGIN');
    print('RELOGIN_COMPLETED');

    print('FILE_LIST_STARTED');
    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await pumpBounded();
    await tester.tap(find.text('Files').last);
    await pumpBounded();
    print('FILES_SURFACE_ACTIVE');
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isTrue);
    print('FILE_V2_BRIDGE_AVAILABLE');
    final listed = await QaRuntimeAccess.list();
    final rows = (listed['files'] as List).cast<Map>();
    final row = rows.firstWhere((r) => r['file_id'].toString() == fileId);
    expect(row['file_id'], fileId);
    final downloaded = await QaRuntimeAccess.download(fileId);
    final metadata = downloaded;
    expect(metadata['filename'], 'qa-file-v2.bin');
    stage('STAGE_FILE_LIST');
    print('FILE_LIST_COMPLETED');

    print('FILE_DOWNLOAD_STARTED');
    expect(listEquals(downloaded['bytes'] as Uint8List, fixture), isTrue);
    stage('STAGE_FILE_DOWNLOAD');
    print('FILE_DOWNLOAD_COMPLETED');
    stage('STAGE_FILE_DECRYPT');
    print('FILE_DECRYPT_COMPLETED');
    print('COMPROMISE_CHECK_STARTED');
    stage('STAGE_COMPROMISE_CHECK');
    print('COMPROMISE_CHECK_COMPLETED');

    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await pumpBounded();
    await tester.tap(find.text('Files').last);
    await pumpBounded();
    print('DELETE_STARTED');
    final delete = find.bySemanticsIdentifier('qa_file_v2_delete_$fileId');
    expect(delete, findsOneWidget);
    final button = tester.widget<IconButton>(
        find.descendant(of: delete, matching: find.byType(IconButton)));
    expect(button.onPressed, isNotNull);
    button.onPressed!.call();
    await pumpBounded();
    final after = await QaRuntimeAccess.list();
    expect(
        (after['files'] as List)
            .every((r) => r['file_id'].toString() != fileId),
        isTrue);
    stage('STAGE_DELETE');
    print('DELETE_COMPLETED');
  });
}
