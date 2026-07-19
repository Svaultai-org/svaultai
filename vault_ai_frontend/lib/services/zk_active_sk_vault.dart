// Process-global cache for the currently-unlocked ZK vault's
// X25519 private key ``sk_vault_private``.
//
// The private key is unwrapped from ``wrapped_sk_vault`` during
// ZK login/registration (see ``zk_auth_service.dart``) and is
// required for the beneficiary side of the inheritance credential
// escrow flow — decrypting the wrapped CEK requires an X25519 ECDH
// with the beneficiary's own ``sk_vault_private``.
//
// This holder is analogous to ``ZkActiveMvk``; the same lifecycle
// rules apply:
//   * populated by ``main.dart`` right after a successful login;
//   * cleared on logout or vault switch;
//   * returns null for legacy (non-ZK) vaults — callers must fail
//     closed and surface a clear operator message.
//
// The bytes never touch persistent storage; if the app process is
// killed, the beneficiary must log in again before revealing.

import 'package:cryptography/cryptography.dart';

class ZkActiveSkVault {
  static SecretKey? _current;
  static String? _vaultId;

  static void set({
    required SecretKey skVault,
    required String vaultId,
  }) {
    _current = skVault;
    _vaultId = vaultId;
  }

  static void clear() {
    _current = null;
    _vaultId = null;
  }

  static SecretKey? current() => _current;

  static String? currentVaultId() => _vaultId;
}
