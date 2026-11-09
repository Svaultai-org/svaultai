import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_item_read_session.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    SessionTermination.instance.resetForTests();
    ZkPinFreeItemReadSession.instance.clear();
  });
  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    ZkPinFreeItemReadSession.instance.clear();
    SessionTermination.instance.resetForTests();
  });

  test('lock and vault replacement cannot reuse an OPAQUE read offer',
      () async {
    final app = AppState();
    try {
      await app.setSession(
        token: 'first-opaque-session',
        vaultIdValue: 'first-synthetic-vault',
        vaultNameValue: 'First vault',
        vaultHandleValue: 'first-synthetic-handle',
        pinFreeLegacyItemRead: true,
      );
      expect(ZkPinFreeItemReadSession.instance
          .activeForToken('first-opaque-session'), isTrue);
      app.unlocked = false;
      expect(ZkPinFreeItemReadSession.instance
          .activeForToken('first-opaque-session'), isFalse);
      expect(ZkPinFreeItemReadSession.instance
          .wasOfferedForToken('first-opaque-session'), isTrue);
      expect(ZkPinFreeItemReadSession.instance
          .privateVaultForToken('first-opaque-session'),
          kEnableKeylessSavedItemRead);

      await app.setSession(
        token: 'second-session',
        vaultIdValue: 'second-synthetic-vault',
        vaultNameValue: 'Second vault',
      );
      expect(ZkPinFreeItemReadSession.instance
          .wasOfferedForToken('first-opaque-session'), isFalse);
      expect(ZkPinFreeItemReadSession.instance
          .activeForToken('second-session'), isFalse);
      expect(ZkPinFreeItemReadSession.instance
          .privateVaultForToken('second-session'), isFalse);
      await app.clearSession();
    } finally {
      app.dispose();
    }
  });

  test('unoffered OPAQUE marker follows only its current bearer', () async {
    final app = AppState();
    try {
      await app.setSession(
        token: 'first-opaque-session',
        vaultIdValue: 'first-synthetic-vault',
        vaultNameValue: 'First vault',
        vaultHandleValue: 'first-synthetic-handle',
      );
      expect(ZkPinFreeItemReadSession.instance
          .privateVaultForToken('first-opaque-session'),
          kEnableKeylessSavedItemRead);
      await app.setSession(
        token: 'replacement-legacy-session',
        vaultIdValue: 'second-synthetic-vault',
        vaultNameValue: 'Second vault',
      );
      expect(ZkPinFreeItemReadSession.instance
          .privateVaultForToken('first-opaque-session'), isFalse);
      expect(ZkPinFreeItemReadSession.instance
          .privateVaultForToken('replacement-legacy-session'), isFalse);
      await app.clearSession();
    } finally {
      app.dispose();
    }
  });
}
