
import 'dart:math' as math;
import 'dart:typed_data';

import 'monero_crypto_primitives.dart';
import 'monero_ed25519.dart';


class MoneroWalletGenerationBlocked implements Exception {
  final String reason;
  const MoneroWalletGenerationBlocked(this.reason);
  @override
  String toString() => 'MoneroWalletGenerationBlocked: $reason';
}


class MoneroWalletGenerationFailed implements Exception {
  final String code;

  const MoneroWalletGenerationFailed(this.code);
  @override
  String toString() => 'MoneroWalletGenerationFailed: $code';
}



class GeneratedMoneroWallet {
  final String publicAddress;
  final int restoreHeight;
  final String encryptedWalletSecretPayload;

  const GeneratedMoneroWallet({
    required this.publicAddress,
    required this.restoreHeight,
    required this.encryptedWalletSecretPayload,
  });
}


abstract class MoneroWalletAdapter {
  bool get isAvailable;

  String get unavailableReason;


  Future<GeneratedMoneroWallet> generate({
    required int restoreHeight,
    required Future<String> Function(String plaintext) encryptForVault,
    Uint8List? seedForTests,
  });
}


class NullMoneroWalletAdapter implements MoneroWalletAdapter {
  static const String kBlockerReason =
      'Monero wallet generation is not wired into this build. To ship '
      'the client-side wallet generator into production, plug in a '
      'RealMoneroWalletAdapter and pass it down through the wallet '
      'engine page.';

  const NullMoneroWalletAdapter();

  @override
  bool get isAvailable => false;

  @override
  String get unavailableReason => kBlockerReason;

  @override
  Future<GeneratedMoneroWallet> generate({
    required int restoreHeight,
    required Future<String> Function(String plaintext) encryptForVault,
    Uint8List? seedForTests,
  }) {
    throw const MoneroWalletGenerationBlocked(kBlockerReason);
  }
}


class InjectedMoneroWalletAdapter implements MoneroWalletAdapter {
  final Future<GeneratedMoneroWallet> Function({
    required int restoreHeight,
    required Future<String> Function(String plaintext) encryptForVault,
    Uint8List? seedForTests,
  }) generator;
  final bool available;
  final String reason;

  const InjectedMoneroWalletAdapter({
    required this.generator,
    this.available = true,
    this.reason = '',
  });

  @override
  bool get isAvailable => available;

  @override
  String get unavailableReason => reason;

  @override
  Future<GeneratedMoneroWallet> generate({
    required int restoreHeight,
    required Future<String> Function(String plaintext) encryptForVault,
    Uint8List? seedForTests,
  }) => generator(
        restoreHeight: restoreHeight,
        encryptForVault: encryptForVault,
        seedForTests: seedForTests,
      );
}



class RealMoneroWalletAdapter implements MoneroWalletAdapter {
  final math.Random _rng;

  RealMoneroWalletAdapter({math.Random? rng})
      : _rng = rng ?? math.Random.secure();

  @override
  bool get isAvailable => true;

  @override
  String get unavailableReason => '';

  @override
  Future<GeneratedMoneroWallet> generate({
    required int restoreHeight,
    required Future<String> Function(String plaintext) encryptForVault,
    Uint8List? seedForTests,
  }) async {
    if (restoreHeight < 0) {
      throw const MoneroWalletGenerationFailed(
        'restore_height_must_be_non_negative',
      );
    }
    final seed = seedForTests ?? _randomBytes(32);
    if (seed.length != 32) {
      throw const MoneroWalletGenerationFailed(
        'seed_must_be_32_bytes',
      );
    }
    final privateSpendKey = scRed32(seed);
    final privateViewKey = moneroDerivePrivateViewKey(privateSpendKey);
    final publicSpendKey = moneroDerivePublicKey(privateSpendKey);
    final publicViewKey = moneroDerivePublicKey(privateViewKey);
    final address = buildMoneroPrimaryAddress(
      publicSpendKey: publicSpendKey,
      publicViewKey: publicViewKey,
    );
    if (!moneroPrimaryAddressChecksumValid(address)) {
      _wipe(seed);
      _wipe(privateSpendKey);
      _wipe(privateViewKey);
      throw const MoneroWalletGenerationFailed(
        'address_self_check_failed',
      );
    }
    final plaintextSecret = _composePlaintextSecret(
      privateSpendKey: privateSpendKey,
      privateViewKey: privateViewKey,
      publicSpendKey: publicSpendKey,
      publicViewKey: publicViewKey,
      restoreHeight: restoreHeight,
    );
    final ciphertext = await encryptForVault(plaintextSecret);
    _wipe(seed);
    _wipe(privateSpendKey);
    _wipe(privateViewKey);
    return GeneratedMoneroWallet(
      publicAddress: address,
      restoreHeight: restoreHeight,
      encryptedWalletSecretPayload: ciphertext,
    );
  }

  Uint8List _randomBytes(int n) {
    final b = Uint8List(n);
    for (int i = 0; i < n; i++) {
      b[i] = _rng.nextInt(256);
    }
    return b;
  }

  static void _wipe(Uint8List b) {
    for (int i = 0; i < b.length; i++) {
      b[i] = 0;
    }
  }

  static String _composePlaintextSecret({
    required Uint8List privateSpendKey,
    required Uint8List privateViewKey,
    required Uint8List publicSpendKey,
    required Uint8List publicViewKey,
    required int restoreHeight,
  }) {
    String hex(Uint8List b) => b
        .map((v) => v.toRadixString(16).padLeft(2, '0'))
        .join();
    return '{'
        '"schema":"monero_wallet_secret_v1",'
        '"privateSpendKeyHex":"${hex(privateSpendKey)}",'
        '"privateViewKeyHex":"${hex(privateViewKey)}",'
        '"publicSpendKeyHex":"${hex(publicSpendKey)}",'
        '"publicViewKeyHex":"${hex(publicViewKey)}",'
        '"restoreHeight":$restoreHeight'
        '}';
  }
}


bool isValidMoneroPrimaryAddressShape(String? raw) {
  if (raw == null) return false;
  final s = raw.trim();
  if (s.isEmpty) return false;
  if (s.length != 95) return false;
  final firstChar = s.substring(0, 1);
  if (firstChar != '4' && firstChar != '8') return false;
  return RegExp(r'^[1-9A-HJ-NP-Za-km-z]{95}$').hasMatch(s);
}


bool isValidMoneroIntegratedAddressShape(String? raw) {
  if (raw == null) return false;
  final s = raw.trim();
  if (s.isEmpty) return false;
  if (s.length != 106) return false;
  return RegExp(r'^[1-9A-HJ-NP-Za-km-z]{106}$').hasMatch(s);
}
