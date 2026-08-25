import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/credential_inventory_view_state.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';

void main() {
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
