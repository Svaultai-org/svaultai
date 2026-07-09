

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:pointycastle/api.dart' show KeyParameter;
import 'package:pointycastle/digests/keccak.dart';
import 'package:pointycastle/ecc/api.dart';
import 'package:pointycastle/ecc/curves/secp256k1.dart';
import 'package:pointycastle/random/fortuna_random.dart';


class GeneratedEthereumWallet {
  
  final String privateKeyHex;

  
  final String publicAddress;

  
  final String publicAddressLowercase;

  const GeneratedEthereumWallet._({
    required this.privateKeyHex,
    required this.publicAddress,
    required this.publicAddressLowercase,
  });
}


final ECDomainParameters _secp256k1 = ECCurve_secp256k1();


GeneratedEthereumWallet generateEthereumWallet() {
  final secureRandom = _fortunaSeededFromPlatform();

  
  for (var i = 0; i < 16; i++) {
    final candidate = secureRandom.nextBytes(32);
    final asBigInt = _bigIntFromBytes(candidate);
    if (asBigInt <= BigInt.zero) continue;
    if (asBigInt >= _secp256k1.n) continue;
    final address = _deriveEthereumAddress(asBigInt);
    return GeneratedEthereumWallet._(
      privateKeyHex: _hex(candidate),
      publicAddress: _eip55Checksum(address),
      publicAddressLowercase: address,
    );
  }
  throw WalletGenerationFailure(
    'Failed to derive a secp256k1-valid private key after 16 attempts. '
    'This is statistically near-impossible — investigate the CSPRNG '
    'source before retrying.',
  );
}


String deriveEthereumAddressFromPrivateKeyHex(String privateKeyHex) {
  if (privateKeyHex.startsWith('0x') || privateKeyHex.startsWith('0X')) {
    privateKeyHex = privateKeyHex.substring(2);
  }
  if (privateKeyHex.length != 64) {
    throw ArgumentError(
      'Ethereum private key must be 64 hex chars (got '
      '${privateKeyHex.length}).',
    );
  }
  final keyBytes = _bytesFromHex(privateKeyHex);
  final keyBigInt = _bigIntFromBytes(keyBytes);
  if (keyBigInt <= BigInt.zero || keyBigInt >= _secp256k1.n) {
    throw ArgumentError(
      'Private key value is outside the secp256k1 valid range '
      '[1, n).',
    );
  }
  final address = _deriveEthereumAddress(keyBigInt);
  return _eip55Checksum(address);
}

class WalletGenerationFailure implements Exception {
  final String message;
  const WalletGenerationFailure(this.message);
  @override
  String toString() => 'WalletGenerationFailure: $message';
}


FortunaRandom _fortunaSeededFromPlatform() {
  final r = math.Random.secure();
  final seed = Uint8List(32);
  for (var i = 0; i < seed.length; i++) {
    seed[i] = r.nextInt(256);
  }
  final fortuna = FortunaRandom();
  fortuna.seed(KeyParameter(seed));
  return fortuna;
}

String _deriveEthereumAddress(BigInt privateKey) {
  
  
  final point = _secp256k1.G * privateKey;
  if (point == null) {
    throw const WalletGenerationFailure(
      'secp256k1 scalar multiplication returned a null point.',
    );
  }
  final x = point.x!.toBigInteger()!;
  final y = point.y!.toBigInteger()!;
  final xBytes = _padTo32(x);
  final yBytes = _padTo32(y);
  final pub = Uint8List(64)
    ..setRange(0, 32, xBytes)
    ..setRange(32, 64, yBytes);
  
  final hash = KeccakDigest(256).process(pub);
  final addrBytes = hash.sublist(12);
  return '0x' + _hex(addrBytes);
}

String _eip55Checksum(String lowerAddress) {
  if (!lowerAddress.startsWith('0x') || lowerAddress.length != 42) {
    throw ArgumentError(
      'EIP-55 checksum requires a 0x-prefixed 40-hex address.',
    );
  }
  final body = lowerAddress.substring(2).toLowerCase();
  final hash = KeccakDigest(256).process(
    Uint8List.fromList(utf8.encode(body)),
  );
  final out = StringBuffer('0x');
  for (var i = 0; i < body.length; i++) {
    final c = body[i];
    final isHexLetter = RegExp(r'[a-f]').hasMatch(c);
    if (!isHexLetter) {
      out.write(c);
      continue;
    }
    
    
    final byte = hash[i ~/ 2];
    final nibble = (i % 2 == 0) ? (byte >> 4) & 0xf : byte & 0xf;
    out.write(nibble >= 8 ? c.toUpperCase() : c);
  }
  return out.toString();
}

BigInt _bigIntFromBytes(Uint8List bytes) {
  var result = BigInt.zero;
  for (final b in bytes) {
    result = (result << 8) | BigInt.from(b);
  }
  return result;
}

Uint8List _padTo32(BigInt n) {
  var hex = n.toRadixString(16);
  if (hex.length < 64) {
    hex = '0' * (64 - hex.length) + hex;
  }
  return _bytesFromHex(hex);
}

Uint8List _bytesFromHex(String hex) {
  if (hex.length % 2 != 0) {
    throw ArgumentError('Hex string must have even length.');
  }
  final out = Uint8List(hex.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(hex.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return out;
}

String _hex(Uint8List bytes) {
  final sb = StringBuffer();
  for (final b in bytes) {
    sb.write(b.toRadixString(16).padLeft(2, '0'));
  }
  return sb.toString();
}
