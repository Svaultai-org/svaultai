// Transparent legacy-to-ZK adoption trigger.
//
// Called by main.dart's LoginPage / UnlockPage / PinGatePage after a
// successful legacy unlock. Runs asynchronously; a failed adoption
// does NOT break the user's session — the client retries on the
// next unlock.
//
// Behavior:
//   1. Ask the backend whether this vault already has a vault_handle
//      (i.e. is already ZK). If yes, no-op.
//   2. Otherwise: mint a fresh Vault Handle, run OPAQUE registration
//      with the user's existing PIN, adopt the LEGACY vault_key as
//      MVK (zero data re-encryption), wrap it under the new KEK
//      derived from OPAQUE export_key, wrap the display name under
//      the MVK-derived display key, upload via /auth/zk-adopt.
//   3. Store the new Vault Handle in shared_preferences so future
//      logins on this trusted device can autofill it.
//
// This module contains no cryptography — everything delegates to
// zk_auth_service.dart (which delegates to opaque_client.dart which
// delegates to WASM opaque-ke).

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'native_secure_store.dart';
import 'zk_auth_service.dart';

const String prefsVaultHandleKey = 'vaultai.zk.vault_handle';
const String prefsAdoptionAttemptedKey = 'vaultai.zk.adoption_attempted_v1';

typedef HttpJsonPost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body, {
  String? bearerToken,
});

typedef HttpJsonGet = Future<Map<String, dynamic>> Function(
  String path, {
  String? bearerToken,
});

class LegacyAdoptionResult {
  final bool adopted;
  final bool alreadyZk;
  final String? newVaultHandle;
  final Object? error;
  LegacyAdoptionResult({
    required this.adopted,
    required this.alreadyZk,
    this.newVaultHandle,
    this.error,
  });
}

Future<LegacyAdoptionResult> tryAdoptLegacyVault({
  required String legacyDisplayName,
  required String pin,
  required SecretKey legacyVaultKey,
  required String sessionToken,
  required HttpJsonPost post,
  required HttpJsonGet get,
}) async {
  try {
    final status = await get(
      '/auth/me',
      bearerToken: sessionToken,
    ).timeout(const Duration(seconds: 6));
    if (status['zk'] == true || status['vault_handle'] != null) {
      return LegacyAdoptionResult(adopted: false, alreadyZk: true);
    }
  } catch (_) {
    // /auth/me may not expose these fields yet; fall through and
    // attempt adoption. The server-side /auth/zk-adopt endpoint is
    // idempotent — it returns 409 if the vault is already adopted.
  }

  try {
    final legacyBytes = await legacyVaultKey.extractBytes();
    final legacyBytesU8 = Uint8List.fromList(legacyBytes);
    if (legacyBytesU8.length != 32) {
      return LegacyAdoptionResult(
        adopted: false,
        alreadyZk: false,
        error: StateError(
          'legacy vault key is not 32 bytes; refusing to adopt',
        ),
      );
    }

    final zk = ZkAuthService((path, body, {bearerToken}) async {
      return await post(path, body, bearerToken: bearerToken);
    });

    final result = await zk.adoptLegacyVault(
      legacyDisplayName: legacyDisplayName,
      pin: pin,
      legacyVaultKeyBytes: legacyBytesU8,
      currentSessionToken: sessionToken,
    );

    try {
      await NativeSecureStore.writeString(
        prefsVaultHandleKey,
        result.newVaultHandle,
      );
    } catch (_) {
      // If local secure storage is unavailable, we still succeeded
      // server-side. Next login attempt will need the user to type
      // their handle.
    }

    return LegacyAdoptionResult(
      adopted: true,
      alreadyZk: false,
      newVaultHandle: result.newVaultHandle,
    );
  } catch (err) {
    return LegacyAdoptionResult(
      adopted: false,
      alreadyZk: false,
      error: err,
    );
  }
}

/// Return the last-adopted Vault Handle stored on this device, or
/// null if none. Used for the trusted-device autofill.
Future<String?> readCachedVaultHandle() async {
  try {
    return NativeSecureStore.readString(prefsVaultHandleKey);
  } catch (_) {
    return null;
  }
}

/// Clear the cached Vault Handle. Called on logout when the user
/// asks to untrust this device.
Future<void> clearCachedVaultHandle() async {
  try {
    await NativeSecureStore.deleteString(prefsVaultHandleKey);
  } catch (_) {}
}

/// Best-effort UTF-8 encode helper for callers.
List<int> encodeDisplayName(String s) => utf8.encode(s);
