import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;
import 'package:vault_ai_frontend/services/qa_file_picker_override.dart';

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

    await tester.tap(find.bySemanticsIdentifier('attachment_menu_button'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('attachment_menu_upload_file')));
    await tester.pumpAndSettle();
    expect(find.text('qa-file-v2.bin'), findsOneWidget);
    stage('STAGE_FILE_UPLOAD');
    await tester.tap(find.bySemanticsIdentifier('composer_send_button'));
    await tester.pumpAndSettle(const Duration(seconds: 12));
    stage('STAGE_SERVER_STATE');
    // Remaining lifecycle stages are intentionally explicit checkpoints for
    // the same real app process; they fail closed until live assertions are
    // added for the target QA backend record.
    fail('FILE_V2 live server/list/relogin/delete assertions require QA runtime inspection');
  });
}
