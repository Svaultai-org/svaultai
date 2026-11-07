// A single owner-approved older-file read. The PIN is used only to obtain an
// OPAQUE action proof and derive the old content key on this device. Neither
// value is installed in the vault-wide PIN/key caches.

import 'package:cryptography/cryptography.dart' show SecretKey;

import 'zk_proof_token_guard.dart';

class LegacyFileActionCancelled implements Exception {
  const LegacyFileActionCancelled();
}

final class EphemeralLegacyFileAction {
  EphemeralLegacyFileAction({
    required this.promptPin,
    required this.verifyPin,
    required this.deriveKey,
    required this.accessIsCurrent,
  });

  final Future<String?> Function() promptPin;
  final Future<String> Function(String pin) verifyPin;
  final Future<SecretKey> Function(String pin) deriveKey;
  final bool Function() accessIsCurrent;

  SecretKey? _key;
  String? _firstProof;
  bool _closed = false;

  bool get isOpen => !_closed && _key != null && accessIsCurrent();

  Future<SecretKey> open() async {
    if (_closed || _key != null || !accessIsCurrent()) {
      throw StateError('Vault file action is unavailable');
    }
    String? pin;
    try {
      pin = await promptPin();
      _requireCurrent();
      if (pin == null) throw const LegacyFileActionCancelled();
      if (!RegExp(r'^\d{6,64}$').hasMatch(pin)) {
        throw const FormatException('Invalid vault PIN');
      }
      final proof = rejectPinShapedZkProof(await verifyPin(pin));
      _requireCurrent();
      final key = await deriveKey(pin);
      _requireCurrent();
      _key = key;
      _firstProof = proof;
      return key;
    } catch (_) {
      close();
      rethrow;
    } finally {
      // Dart strings cannot be guaranteed erased from the heap. Release our
      // reference before any file ciphertext is fetched.
      pin = null;
    }
  }

  /// The export may require another bounded grant. Ask for a fresh PIN/proof
  /// then; do not keep the PIN in memory for the duration of a file download.
  Future<String> proof() async {
    _requireOpen();
    final first = _firstProof;
    if (first != null) {
      _firstProof = null;
      return first;
    }
    String? pin;
    try {
      pin = await promptPin();
      _requireOpen();
      if (pin == null) throw const LegacyFileActionCancelled();
      if (!RegExp(r'^\d{6,64}$').hasMatch(pin)) {
        throw const FormatException('Invalid vault PIN');
      }
      final proof = rejectPinShapedZkProof(await verifyPin(pin));
      _requireOpen();
      return proof;
    } finally {
      pin = null;
    }
  }

  void _requireCurrent() {
    if (_closed || !accessIsCurrent()) {
      throw StateError('Vault session changed during file action');
    }
  }

  void _requireOpen() {
    _requireCurrent();
    if (_key == null) throw StateError('Vault file action is closed');
  }

  void close() {
    _closed = true;
    _firstProof = null;
    _key = null;
  }
}
