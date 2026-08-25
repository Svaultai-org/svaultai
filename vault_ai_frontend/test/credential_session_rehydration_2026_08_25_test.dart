import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/credential_inventory_view_state.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';

void main() {
  test('legacy generated-login save requires authoritative list readback', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf(
      'Future<void> _saveGeneratedLoginLegacyAuthoritatively',
    );
    final end = source.indexOf(
      'Future<void> _saveMemoryProposalFromCard',
      start,
    );
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final method = source.substring(start, end);
    expect(method, contains("await _sendQuickPrompt(\n      'save it'"));
    expect(method, contains('await _loadVaultLogins();'));
    expect(method, contains('forceLegacyTransport: true'));
    expect(method, contains("StateError('generated_legacy_readback_failed')"));
  });

  test('legacy generated-login card awaits authoritative save helper', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf("if (action == 'generated_login_save')");
    final end = source.indexOf(
      "if (action == 'generated_login_cancel')",
      start,
    );
    final handler = source.substring(start, end);
    expect(
      handler,
      contains('await _saveGeneratedLoginLegacyAuthoritatively('),
    );
    expect(
      handler,
      isNot(contains("await _sendQuickPrompt(\n        'save it'")),
    );
  });

  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
  });

  test('real logout/login lifecycle invalidates credential inventory owner',
      () async {
    final app = AppState();
    final binding = CredentialInventorySessionBinding();

    await app.setSession(
      token: 'session-a1',
      vaultIdValue: 'vault-a',
      vaultNameValue: 'Vault A',
      vaultHandleValue: 'VLT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF',
    );
    expect(binding.bind(app.sessionEpoch), isTrue);
    final firstEpoch = binding.epoch;

    await app.clearSession();
    expect(binding.bind(app.sessionEpoch), isTrue);
    expect(binding.epoch, isNot(firstEpoch));

    await app.setSession(
      token: 'session-a2',
      vaultIdValue: 'vault-a',
      vaultNameValue: 'Vault A',
      vaultHandleValue: 'VLT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF',
    );
    expect(binding.bind(app.sessionEpoch), isTrue);
    expect(binding.bind(app.sessionEpoch), isFalse);
  });

  test('delayed persisted legacy fixture cannot produce false empty', () {
    expect(
      resolveCredentialInventoryViewState(
        loading: true,
        authoritativeLoadCompleted: false,
        itemCount: 0,
        hasError: false,
      ),
      CredentialInventoryViewState.loading,
    );
    expect(
      resolveCredentialInventoryViewState(
        loading: false,
        authoritativeLoadCompleted: true,
        itemCount: 1,
        hasError: false,
      ),
      CredentialInventoryViewState.readyWithItems,
    );
  });

  test('failed merged source renders error rather than authoritative empty',
      () {
    expect(
      resolveCredentialInventoryViewState(
        loading: false,
        authoritativeLoadCompleted: false,
        itemCount: 0,
        hasError: true,
      ),
      CredentialInventoryViewState.error,
    );
  });
}
