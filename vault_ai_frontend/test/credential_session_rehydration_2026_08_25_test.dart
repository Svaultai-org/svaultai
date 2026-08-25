import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/credential_inventory_view_state.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';

void main() {
  test('generated-login save uses ZK transport and authoritative readback', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf(
      'Future<void> _saveGeneratedLoginAuthoritatively',
    );
    final end = source.indexOf(
      'Future<void> _saveMemoryProposalFromCard',
      start,
    );
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final method = source.substring(start, end);
    expect(method, isNot(contains("await _sendQuickPrompt(\n      'save it'")));
    expect(method, contains('await _loadVaultLogins();'));
    expect(method, contains('forceLegacyTransport: false'));
    expect(
      method,
      contains("StateError('generated_credential_readback_failed')"),
    );
    final write = method.indexOf('updateVaultSecureItem(');
    final readback = method.indexOf('await _loadVaultLogins();');
    final acknowledgement = method.indexOf(
      "_appendAssistantMessage('Saved your \${service.trim()} login.');",
    );
    expect(write, greaterThanOrEqualTo(0));
    expect(readback, greaterThan(write));
    expect(acknowledgement, greaterThan(readback));
  });

  test('generated-login card awaits authoritative save helper', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf("if (action == 'generated_login_save')");
    final end = source.indexOf(
      "if (action == 'generated_login_cancel')",
      start,
    );
    final handler = source.substring(start, end);
    expect(
      handler,
      contains('await _saveGeneratedLoginAuthoritatively('),
    );
    expect(
      handler,
      isNot(contains("await _sendQuickPrompt(\n        'save it'")),
    );
  });

  test('fresh session hydrates ciphertext-only vault items under the MVK', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf(
      '// New ZK vaults persist vault_items with opaque metadata columns only.',
    );
    final end = source.indexOf(
      'final v2Repository = _credentialV2Repository(app);',
      start,
    );
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final hydration = source.substring(start, end);
    expect(hydration, contains('listZkVaultItemCiphertexts'));
    expect(hydration, contains('VaultKeyHierarchy(mvk).metadataKey()'));
    expect(hydration, contains("decryptText('item_type_ciphertext')"));
    expect(hydration, contains("decryptText('service_ciphertext')"));
    expect(hydration, contains("decryptText('payload_ciphertext')"));
    expect(hydration, contains('credentialMetadataCryptoVersion'));
    expect(hydration, contains('localFields:'));
  });

  test(
    'ciphertext-only credential chat reveal never calls plaintext backend',
    () {
      final source = File('lib/main.dart').readAsStringSync();
      expect(
        source,
        contains('legacy.cryptoVersion == credentialMetadataCryptoVersion'),
      );
      expect(
        source,
        contains('await _openCiphertextSecureItemDirect(legacy);'),
      );
    },
  );

  test('typed save and card save share authoritative persistence helper', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('Future<void> _enqueueComposerSend()');
    final end = source.indexOf('Future<void> _send() async', start);
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final composerDispatch = source.substring(start, end);
    expect(
      composerDispatch,
      contains('_isGeneratedLoginSaveConfirmation(text)'),
    );
    expect(composerDispatch, contains('_latestGeneratedLoginDraft()'));
    expect(
      composerDispatch,
      contains("if (message.role == 'user') return null;"),
    );
    expect(
      composerDispatch,
      contains('message.kind != ChatMessage.kVaultChatCard'),
    );
    expect(
      composerDispatch,
      contains('await _saveGeneratedLoginAuthoritatively('),
    );

    final cardStart = source.indexOf("if (action == 'generated_login_save')");
    final cardEnd = source.indexOf(
      "if (action == 'generated_login_cancel')",
      cardStart,
    );
    final cardDispatch = source.substring(cardStart, cardEnd);
    expect(
      cardDispatch,
      contains('await _saveGeneratedLoginAuthoritatively('),
    );
  });

  test('credential confirmation is vault scoped and fails closed', () {
    final source = File('lib/main.dart').readAsStringSync();
    final saveStart = source.indexOf(
      'Future<void> _saveGeneratedLoginAuthoritatively',
    );
    final saveEnd = source.indexOf(
      'Future<void> _saveMemoryProposalFromCard',
      saveStart,
    );
    final save = source.substring(saveStart, saveEnd);
    expect(
      save,
      contains("StateError('generated_credential_vault_scope_missing')"),
    );
    expect(save, contains('app.vaultId != initialVaultId'));
    expect(
      save,
      contains("StateError('generated_credential_readback_failed')"),
    );

    final dispatchStart = source.indexOf('Future<void> _enqueueComposerSend()');
    final dispatchEnd =
        source.indexOf('Future<void> _send() async', dispatchStart);
    final dispatch = source.substring(dispatchStart, dispatchEnd);
    expect(
      dispatch,
      contains('_pendingGeneratedLoginDraftVaultId == app.vaultId'),
    );
    expect(
      dispatch,
      contains(
        'Could not confirm that credential draft. Nothing was saved.',
      ),
    );
    expect(
      dispatch,
      contains(
        'Could not save that credential securely. Nothing was saved.',
      ),
    );
    expect(dispatch, contains('return Future<void>.value();'));
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
