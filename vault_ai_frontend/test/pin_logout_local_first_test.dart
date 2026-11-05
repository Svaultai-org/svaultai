import 'dart:async';
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
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    VaultCryptoRegistry.clear(reason: 'logout_test');
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    VaultCryptoRegistry.clear(reason: 'logout_test');
  });

  test('logout clears local secrets before remote revocation completes',
      () async {
    final app = AppState();
    const token = 'synthetic-logout-session';
    const vaultId = 'synthetic-logout-vault';
    const vaultName = 'Synthetic logout vault';
    final remoteEntered = Completer<String>();
    final releaseRemote = Completer<void>();
    try {
      await app.setSession(
        token: token,
        vaultIdValue: vaultId,
        vaultNameValue: vaultName,
        vaultHandleValue: 'VLT-synthetic-logout',
      );
      if (kIsWeb) {
        await deriveAndInstallCryptoContext(
          vaultId: vaultId,
          vaultName: vaultName,
          pin: '123456',
          pinSaltBase64: base64Encode(List<int>.filled(16, 7)),
          iterations: 1000,
          source: 'synthetic_logout_test',
        );
      }
      ZkActiveMvk.set(
        mvk: SecretKey(List<int>.filled(32, 8)),
        vaultId: vaultId,
        vaultHandle: 'VLT-synthetic-logout',
      );
      ZkActiveSkVault.set(
        skVault: SecretKey(List<int>.filled(32, 9)),
        vaultId: vaultId,
      );
      app.markUnlocked();
      expect(ZkActiveMvk.current(), isNotNull);
      expect(ZkActiveSkVault.current(), isNotNull);
      if (kIsWeb) {
        expect(app.unlocked, isTrue);
        expect(
            zkPrivateUnlockCredentialStateForTesting()['pin_cache_entries'], 1);
      }

      final signOut = app.signOut(remoteLogout: (capturedToken) {
        remoteEntered.complete(capturedToken);
        return releaseRemote.future;
      });
      expect(await remoteEntered.future, token);
      expect(app.sessionToken, isNull);
      expect(app.unlocked, isFalse);
      expect(app.vaultName, isNull);
      expect(ZkActiveMvk.current(), isNull);
      expect(ZkActiveSkVault.current(), isNull);
      expect(zkPrivateUnlockCredentialStateForTesting(), {
        'pin_cache_entries': 0,
        'legacy_key_entries': 0,
        'has_pbkdf2_context': false,
      });
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('session_token'), isNull);

      releaseRemote.complete();
      await signOut;
    } finally {
      if (!releaseRemote.isCompleted) releaseRemote.complete();
      await app.clearSession();
      app.dispose();
    }
  });
}
