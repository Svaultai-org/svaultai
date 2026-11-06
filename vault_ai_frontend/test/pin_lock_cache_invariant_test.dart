import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    VaultCryptoRegistry.clear(reason: 'pin_lock_test_setup');
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    VaultCryptoRegistry.clear(reason: 'pin_lock_test_teardown');
  });

  test('a direct lock removes cached PIN, PBKDF2 context, and ZK keys',
      () async {
    final app = AppState();
    const vaultId = 'synthetic-lock-vault';
    const vaultName = 'Synthetic lock vault';
    const token = 'synthetic-lock-session';
    const handle = 'VLT-synthetic-lock';
    try {
      await app.setSession(
        token: token,
        vaultIdValue: vaultId,
        vaultNameValue: vaultName,
        vaultHandleValue: handle,
      );
      final context = await deriveAndInstallCryptoContext(
        vaultId: vaultId,
        vaultName: vaultName,
        pin: '135790',
        pinSaltBase64: base64Encode(List<int>.filled(16, 19)),
        iterations: 1000,
        source: 'synthetic_lock_test',
      );
      expect(context, isNotNull);
      ZkActiveMvk.set(
        mvk: SecretKey(List<int>.filled(32, 20)),
        vaultId: vaultId,
        vaultHandle: handle,
      );
      ZkActiveSkVault.set(
        skVault: SecretKey(List<int>.filled(32, 21)),
        vaultId: vaultId,
      );
      app.markUnlocked();
      expect(app.unlocked, isTrue);
      expect(
          zkPrivateUnlockCredentialStateForTesting()['pin_cache_entries'], 1);

      // This is deliberately only the AppState setter: no caller-side
      // clearCache helper is allowed to hide a broken lock invariant.
      app.unlocked = false;
      expect(app.unlocked, isFalse);
      expect(zkPrivateUnlockCredentialStateForTesting(), {
        'pin_cache_entries': 0,
        'legacy_key_entries': 0,
        'has_pbkdf2_context': false,
      });
      expect(ZkActiveMvk.current(), isNull);
      expect(ZkActiveSkVault.current(), isNull);

      // A fresh entered PIN can still install a new unlocked context.
      final next = await deriveAndInstallCryptoContext(
        vaultId: vaultId,
        vaultName: vaultName,
        pin: '135790',
        pinSaltBase64: base64Encode(List<int>.filled(16, 19)),
        iterations: 1000,
        source: 'synthetic_reunlock_test',
      );
      expect(next, isNotNull);
      app.markUnlocked();
      expect(app.unlocked, isTrue);

      // A failed or interrupted unlock can install a context before the
      // dashboard becomes unlocked. Repeating the lock still clears it.
      app.unlocked = false;
      final interrupted = await deriveAndInstallCryptoContext(
        vaultId: vaultId,
        vaultName: vaultName,
        pin: '135790',
        pinSaltBase64: base64Encode(List<int>.filled(16, 19)),
        iterations: 1000,
        source: 'synthetic_interrupted_unlock_test',
      );
      expect(interrupted, isNotNull);
      expect(app.unlocked, isFalse);
      app.unlocked = false;
      expect(zkPrivateUnlockCredentialStateForTesting(), {
        'pin_cache_entries': 0,
        'legacy_key_entries': 0,
        'has_pbkdf2_context': false,
      });
    } finally {
      await app.clearSession();
      app.dispose();
    }
  }, skip: !kIsWeb || kPrivateOnlyUnlockEnabled);
}
