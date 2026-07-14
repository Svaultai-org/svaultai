// Process-global accessor for the currently-unlocked ZK vault's MVK.
//
// main.dart's unlock paths (legacy _deriveKeyAndUnlock and ZK
// loginVault / registerVault / adoptLegacyVault) call
// `ZkActiveMvk.set(...)` after populating `_VaultCrypto._keyCache`.
// Downstream widgets (crypto send panels, upload panel, chat
// callbacks) call `ZkActiveMvk.current()` when they need to encrypt
// something client-side.
//
// Returns null when the active vault is legacy (not yet adopted) —
// callers then fall back to plaintext writes and rely on the lazy
// migration loop to catch up on the next unlock.
//
// This module holds a SecretKey handle only; no key bytes are
// exposed unless the caller explicitly calls extractBytes(). On
// vault switch or logout, main.dart clears the holder.

import 'package:cryptography/cryptography.dart';

class ZkActiveMvk {
  static SecretKey? _current;
  static String? _vaultId;
  static String? _vaultHandle;

  static void set({
    required SecretKey mvk,
    required String vaultId,
    required String vaultHandle,
  }) {
    _current = mvk;
    _vaultId = vaultId;
    _vaultHandle = vaultHandle;
  }

  static void clear() {
    _current = null;
    _vaultId = null;
    _vaultHandle = null;
  }

  static SecretKey? current() => _current;

  static String? currentVaultId() => _vaultId;

  static String? currentVaultHandle() => _vaultHandle;
}
