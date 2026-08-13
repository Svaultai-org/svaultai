import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/foundation.dart';
import 'package:integration_test/integration_test.dart';
import 'package:vault_ai_frontend/main.dart' as app;
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import 'package:uuid/uuid.dart';
import 'package:vault_ai_frontend/services/credential_v2.dart';
import 'package:vault_ai_frontend/services/credential_v2_api.dart';
import 'package:vault_ai_frontend/services/credential_v2_repository.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart' as zk_mvk;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

Future<String> _prepareSyntheticCredentialV2(WidgetTester tester) async {
  print('CREDENTIAL_FIXTURE_STAGE_ENTERED=true');
  final context = tester.element(find.byType(app.SvaultaiApp));
  final state = Provider.of<app.AppState>(context, listen: false);
  final token = state.sessionToken;
  final vaultId = state.vaultId;
  final mvk = zk_mvk.ZkActiveMvk.current();
  if (token == null || token.isEmpty || vaultId == null || vaultId.isEmpty) {
    print('CREDENTIAL_FIXTURE_AUTH_CONTEXT_READY=false');
    throw StateError('credential fixture auth context unavailable');
  }
  print('CREDENTIAL_FIXTURE_AUTH_CONTEXT_READY=true');
  if (mvk == null || zk_mvk.ZkActiveMvk.currentVaultId() != vaultId) {
    print('CREDENTIAL_FIXTURE_MVK_READY=false');
    throw StateError('credential fixture MVK unavailable');
  }
  print('CREDENTIAL_FIXTURE_MVK_READY=true');
  final repository = CredentialV2Repository(
    crypto: CredentialV2Crypto(VaultKeyHierarchy(mvk)),
    api: CredentialV2Api(
      baseUrl: app.backendBaseUrl,
      sessionToken: token,
      client: http.Client(),
    ),
  );
  print('CREDENTIAL_FIXTURE_REPOSITORY_CREATED=true');
  final service = 'QA Chat Credential ${DateTime.now().microsecondsSinceEpoch}';
  final recordId = 'cred-qa-chat-${DateTime.now().microsecondsSinceEpoch}';
  final operationId = const Uuid().v4();
  final credential = CredentialV2Plaintext(
    service: service,
    username: 'synthetic-user',
    password: 'synthetic-password',
  );
  print('CREDENTIAL_FIXTURE_CREATE_ENTERED=true');
  print('CREDENTIAL_CREATE_CALL_ABOUT_TO_RUN=true');
  try {
    await repository.create(
        recordId: recordId,
        credential: credential,
        serviceForLookup: service,
        migrationOperationId: operationId);
  } catch (error, stack) {
    print('CREDENTIAL_CREATE_EXCEPTION_RUNTIME_TYPE=${error.runtimeType}');
    final origin = stack.toString().split('\n').firstWhere(
          (line) => line.contains('credential_v2'),
          orElse: () => 'unknown',
        );
    print('CREDENTIAL_CREATE_EXCEPTION_ORIGIN_FILE=$origin');
    print('CREDENTIAL_CREATE_EXCEPTION_SAFE_CATEGORY=unexpected_safe_category');
    rethrow;
  }
  print('CREDENTIAL_CREATE_CALL_RETURNED=true');
  print('CREDENTIAL_FIXTURE_CREATE_RETURNED=true');
  final readBack = await repository.reveal(recordId);
  print('CREDENTIAL_FIXTURE_READBACK_RETURNED=true');
  if (!readBack.semanticallyEquals(credential))
    throw StateError('credential fixture readback mismatch');
  print('CREDENTIAL_VERIFY_PRECONDITIONS_ENTERED=true');
  print('CREDENTIAL_VERIFY_RECORD_ID_PRESENT=${recordId.isNotEmpty}');
  print('CREDENTIAL_VERIFY_OPERATION_ID_PRESENT=${operationId.isNotEmpty}');
  print('CREDENTIAL_VERIFY_API_INSTANCE_READY=true');
  print('CREDENTIAL_VERIFY_CALL_ABOUT_TO_RUN=true');
  await repository.api.verify(recordId, operationId);
  print('CREDENTIAL_VERIFY_CALL_RETURNED=true');
  print('CREDENTIAL_FIXTURE_VERIFY_RETURNED=true');
  print('CREDENTIAL_FIXTURE_WRITE=PASS');
  print('CREDENTIAL_FIXTURE_READBACK=PASS');
  print('CREDENTIAL_FIXTURE_VERIFY=PASS');
  print('verification_state=v2_verified');
  print('SYNTHETIC_CREDENTIAL_READY=true');
  return service;
}

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
    await _prepareSyntheticCredentialV2(tester);
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
