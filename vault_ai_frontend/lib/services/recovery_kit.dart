// Recovery-kit primitives.
//
// A recovery kit is an OPT-IN backup that lets a user restore vault
// access if they lose their PIN. It works as an ADDITIONAL wrap of
// the same MVK: server stores wrapped_mvk_by_recovery = AES-GCM(
// recovery_KEK, MVK) where recovery_KEK is derived from a
// user-generated 32-byte seed via Argon2id.
//
// The seed is shown to the user ONCE and displayed as
// 24 words (BIP-39 wordlist not embedded here; we render as a
// hex-grouped block that a user can transcribe). Loss of the seed
// after opt-in reverts the vault to "PIN loss = data loss" —
// unchanged from the base guarantee.
//
// This file uses only the `cryptography` package.

import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

const int recoverySeedBytes = 32;
const int recoveryArgon2MemoryKib = 65536;
const int recoveryArgon2Iterations = 3;
const int recoveryArgon2Parallelism = 1;

class RecoveryKit {
  final Uint8List seed;
  final Uint8List wrappedMvk;
  final Uint8List recoverySalt;
  RecoveryKit({
    required this.seed,
    required this.wrappedMvk,
    required this.recoverySalt,
  });

  /// Human-transcribable rendering: 8 groups of 4 base32-style chars.
  String toHumanReadableSeed() {
    const alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
    final chars = <String>[];
    var n = BigInt.zero;
    for (final b in seed) {
      n = (n << 8) | BigInt.from(b);
    }
    final totalChars = (recoverySeedBytes * 8 + 4) ~/ 5;
    final mask = BigInt.from(0x1F);
    final out = List<String>.filled(totalChars, '0');
    for (var i = totalChars - 1; i >= 0; i--) {
      out[i] = alphabet[(n & mask).toInt()];
      n = n >> 5;
    }
    for (var i = 0; i < out.length; i++) {
      chars.add(out[i]);
    }
    final groups = <String>[];
    for (var i = 0; i < chars.length; i += 4) {
      final end = (i + 4 > chars.length) ? chars.length : i + 4;
      groups.add(chars.sublist(i, end).join());
    }
    return groups.join('-');
  }
}

Uint8List generateRecoverySeed() {
  final rng = Random.secure();
  final out = Uint8List(recoverySeedBytes);
  for (var i = 0; i < recoverySeedBytes; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
}

Uint8List parseHumanReadableSeed(String text) {
  final normalized = text
      .toUpperCase()
      .replaceAll(RegExp(r'[\s\-]+'), '')
      .replaceAll('I', '1')
      .replaceAll('L', '1')
      .replaceAll('O', '0')
      .replaceAll('U', 'V');
  const alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  final decode = <String, int>{};
  for (var i = 0; i < alphabet.length; i++) {
    decode[alphabet[i]] = i;
  }
  var n = BigInt.zero;
  for (var i = 0; i < normalized.length; i++) {
    final ch = normalized[i];
    final v = decode[ch];
    if (v == null) {
      throw ArgumentError('Recovery seed contains invalid character: $ch');
    }
    n = (n << 5) | BigInt.from(v);
  }
  final needed = recoverySeedBytes * 8;
  final have = normalized.length * 5;
  if (have < needed) {
    throw ArgumentError('Recovery seed is too short (need 32 bytes)');
  }
  final out = Uint8List(recoverySeedBytes);
  for (var i = recoverySeedBytes - 1; i >= 0; i--) {
    out[i] = (n & BigInt.from(0xFF)).toInt();
    n = n >> 8;
  }
  return out;
}

Future<SecretKey> deriveRecoveryKek(
    Uint8List seed, Uint8List recoverySalt) async {
  final argon = Argon2id(
    memory: recoveryArgon2MemoryKib,
    parallelism: recoveryArgon2Parallelism,
    iterations: recoveryArgon2Iterations,
    hashLength: 32,
  );
  return argon.deriveKey(
    secretKey: SecretKey(seed),
    nonce: recoverySalt,
  );
}

Future<RecoveryKit> createRecoveryKitForMvk(SecretKey mvk) async {
  final seed = generateRecoverySeed();
  final salt = _randomBytes(16);
  final kek = await deriveRecoveryKek(seed, salt);
  final mvkBytes = await mvk.extractBytes();
  final wrapped = await aesGcmWrap(kek, mvkBytes);
  return RecoveryKit(
    seed: seed,
    wrappedMvk: wrapped,
    recoverySalt: salt,
  );
}

/// Restore path: given the seed the user typed and the server-stored
/// (wrappedMvk, recoverySalt), unwrap MVK. Throws on wrong seed.
Future<SecretKey> restoreMvkFromRecovery({
  required Uint8List seed,
  required Uint8List wrappedMvk,
  required Uint8List recoverySalt,
}) async {
  final kek = await deriveRecoveryKek(seed, recoverySalt);
  final mvkBytes = await aesGcmUnwrap(kek, wrappedMvk);
  return SecretKey(mvkBytes);
}

Uint8List _randomBytes(int len) {
  final rng = Random.secure();
  final out = Uint8List(len);
  for (var i = 0; i < len; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
}

/// Convenience helper for the upload body of a recovery-kit
/// registration call.
Map<String, dynamic> recoveryKitUploadBody(RecoveryKit kit) => {
      'wrapped_mvk_by_recovery': base64Url.encode(kit.wrappedMvk)
          .replaceAll('=', ''),
      'recovery_salt': base64Url.encode(kit.recoverySalt)
          .replaceAll('=', ''),
    };
