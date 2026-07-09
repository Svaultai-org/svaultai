

import 'dart:typed_data';

import 'package:cryptography/cryptography.dart' as cg;


const String _base58Alphabet =
    '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';


class GeneratedSolanaWallet {
  final Uint8List secretKeyBytes;
  final String publicAddress;

  const GeneratedSolanaWallet._({
    required this.secretKeyBytes,
    required this.publicAddress,
  });


  String get secretKeyBase58 => base58Encode(secretKeyBytes);
}


class SolanaWalletGenerationFailure implements Exception {
  final String message;
  const SolanaWalletGenerationFailure(this.message);
  @override
  String toString() => 'SolanaWalletGenerationFailure: $message';
}


Future<GeneratedSolanaWallet> generateSolanaWallet() async {
  final algorithm = cg.Ed25519();
  final keyPair = await algorithm.newKeyPair();
  final publicKey = await keyPair.extractPublicKey();
  final seedBytes = await keyPair.extractPrivateKeyBytes();

  final pubBytes = Uint8List.fromList(publicKey.bytes);
  if (pubBytes.length != 32) {
    throw const SolanaWalletGenerationFailure(
      'Solana public key must be 32 bytes.',
    );
  }
  final seed = Uint8List.fromList(seedBytes);
  if (seed.length != 32) {
    throw const SolanaWalletGenerationFailure(
      'Solana ed25519 seed must be 32 bytes.',
    );
  }


  final secretKey64 = Uint8List(64);
  secretKey64.setRange(0, 32, seed);
  secretKey64.setRange(32, 64, pubBytes);

  final address = base58Encode(pubBytes);
  if (!isValidSolanaAddress(address)) {
    throw const SolanaWalletGenerationFailure(
      'Encoded Solana address failed local validation.',
    );
  }

  return GeneratedSolanaWallet._(
    secretKeyBytes: secretKey64,
    publicAddress: address,
  );
}


String base58Encode(Uint8List bytes) {
  if (bytes.isEmpty) return '';


  int leadingZeros = 0;
  for (final b in bytes) {
    if (b == 0) {
      leadingZeros++;
    } else {
      break;
    }
  }


  var n = BigInt.zero;
  for (final b in bytes) {
    n = (n << 8) | BigInt.from(b);
  }

  final buffer = StringBuffer();
  final base = BigInt.from(58);
  while (n > BigInt.zero) {
    final remainder = (n % base).toInt();
    n = n ~/ base;
    buffer.write(_base58Alphabet[remainder]);
  }
  for (var i = 0; i < leadingZeros; i++) {
    buffer.write(_base58Alphabet[0]);
  }
  return buffer.toString().split('').reversed.join();
}


Uint8List? base58Decode(String s) {
  if (s.isEmpty) return Uint8List(0);
  var n = BigInt.zero;
  final base = BigInt.from(58);
  for (final c in s.split('')) {
    final idx = _base58Alphabet.indexOf(c);
    if (idx < 0) return null;
    n = n * base + BigInt.from(idx);
  }
  final body = <int>[];
  while (n > BigInt.zero) {
    body.insert(0, (n & BigInt.from(0xff)).toInt());
    n = n >> 8;
  }
  int leadingOnes = 0;
  for (final c in s.split('')) {
    if (c == '1') {
      leadingOnes++;
    } else {
      break;
    }
  }
  final combined = <int>[];
  for (var i = 0; i < leadingOnes; i++) {
    combined.add(0);
  }
  combined.addAll(body);
  return Uint8List.fromList(combined);
}


bool isValidSolanaAddress(String? raw) {
  if (raw == null) return false;
  final s = raw.trim();
  if (s.length < 32 || s.length > 44) return false;
  for (final c in s.split('')) {
    if (_base58Alphabet.indexOf(c) < 0) return false;
  }
  final decoded = base58Decode(s);
  if (decoded == null) return false;
  return decoded.length == 32;
}


void wipeSecretKey(Uint8List secret) {
  for (var i = 0; i < secret.length; i++) {
    secret[i] = 0;
  }
}
