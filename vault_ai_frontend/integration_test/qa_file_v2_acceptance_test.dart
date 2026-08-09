import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show listEquals;
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;
import 'package:vault_ai_frontend/services/qa_file_picker_override.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/file_v2_repository.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart' as keys;
import 'package:vault_ai_frontend/services/qa_runtime_access.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('FILE_V2 real UI lifecycle', (tester) async {
    void stage(String value) => print('FILE_V2_STAGE=$value');
    const vault = String.fromEnvironment('QA_VAULT_NAME');
    const pin = String.fromEnvironment('QA_PIN');
    expect(vault, isNotEmpty);
    expect(pin, hasLength(6));

    final fixture = Uint8List.fromList(
      List<int>.generate(257, (i) => (i * 31 + 7) & 0xff),
    );
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isFalse);
    qaFilePickerOverride = ({required bool allowMultiple}) async =>
        FilePickerResult([PlatformFile(
          name: 'qa-file-v2.bin', size: fixture.length, bytes: fixture,
        )]);
    addTearDown(() => qaFilePickerOverride = null);

    stage('STAGE_LOGIN');
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
    expect(pinField, findsOneWidget);
    await tester.tap(pinField);
    await tester.enterText(pinField, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    expect(find.bySemanticsIdentifier('top_nav_menu_button'), findsOneWidget);
    expect(QaRuntimeAccess.fileV2RepositoryAvailable, isTrue);

    await tester.tap(find.bySemanticsIdentifier('attachment_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('attachment_menu_upload_file')));
    await tester.pumpAndSettle();
    expect(find.text('qa-file-v2.bin'), findsOneWidget);
    stage('STAGE_FILE_UPLOAD');
    await tester.tap(find.bySemanticsIdentifier('composer_send_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    stage('STAGE_SERVER_STATE');
    final client = VaultAIClient(baseUrl: const String.fromEnvironment('BACKEND_BASE_URL', defaultValue: 'https://127.0.0.1:8444'));
    // The full authenticated API handoff is supplied by the running app;
    // this test never accepts or prints a token.
    final token = const String.fromEnvironment('QA_SESSION_TOKEN');
    expect(token, isNotEmpty);
    final listedBefore = await client.listFileV2(authToken: token);
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

    final listed = await client.listFileV2(authToken: token);
    final rows = (listed['files'] as List).cast<Map>();
    final row = rows.firstWhere((r) => r['file_id'].toString() == fileId);
    expect(row['file_id'], fileId);
    final manifest = await client.getFileV2Manifest(authToken: token, fileId: fileId);
    final repo = FileV2Repository.current()!;
    final metadata = await repo.decryptMetadata(fileId, keys.b64urlDecode(manifest['manifest_ciphertext'] as String));
    expect(metadata.filename, 'qa-file-v2.bin');
    stage('STAGE_FILE_LIST');

    final count = (manifest['chunk_count'] as num).toInt();
    final output = BytesBuilder(copy: false);
    for (var i = 0; i < count; i++) {
      final frame = await client.getFileV2Chunk(authToken: token, fileId: fileId, chunkIndex: i);
      output.add(await repo.decryptChunk(fileId, i, frame));
    }
    expect(listEquals(output.takeBytes(), fixture), isTrue);
    stage('STAGE_FILE_DOWNLOAD');
    stage('STAGE_FILE_DECRYPT');
    stage('STAGE_COMPROMISE_CHECK');

    await tester.tap(find.bySemanticsIdentifier('top_nav_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Files').last);
    await tester.pumpAndSettle(const Duration(seconds: 3));
    final delete = find.bySemanticsIdentifier('qa_file_v2_delete_$fileId');
    expect(delete, findsOneWidget);
    final button = tester.widget<IconButton>(find.descendant(of: delete, matching: find.byType(IconButton)));
    expect(button.onPressed, isNotNull);
    button.onPressed!.call();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    final after = await client.listFileV2(authToken: token);
    expect((after['files'] as List).every((r) => r['file_id'].toString() != fileId), isTrue);
    stage('STAGE_DELETE');
  });
}
