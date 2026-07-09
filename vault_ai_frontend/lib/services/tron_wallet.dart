

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:pointycastle/api.dart' show KeyParameter;
import 'package:pointycastle/digests/keccak.dart';
import 'package:pointycastle/ecc/api.dart';
import 'package:pointycastle/ecc/curves/secp256k1.dart';
import 'package:pointycastle/random/fortuna_random.dart';


const int kTronMainnetPrefix = 0x41;

const String kTronBase58Alphabet =
    '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';


class GeneratedTronWallet {
  final String privateKeyHex;
  final String publicAddress;

  const GeneratedTronWallet._({
    required this.privateKeyHex,
    required this.publicAddress,
  });
}


class TronWalletGenerationFailure implements Exception {
  final String message;
  const TronWalletGenerationFailure(this.message);
  @override
  String toString() => 'TronWalletGenerationFailure: $message';
}


final ECDomainParameters _tronSecp256k1 = ECCurve_secp256k1();


GeneratedTronWallet generateTronWallet() {
  final secureRandom = _fortunaSeededFromPlatform();

  for (var i = 0; i < 16; i++) {
    final candidate = secureRandom.nextBytes(32);
    final asBigInt = _bigIntFromBytes(candidate);
    if (asBigInt <= BigInt.zero) continue;
    if (asBigInt >= _tronSecp256k1.n) continue;
    final addr = _deriveTronAddress(asBigInt);
    return GeneratedTronWallet._(
      privateKeyHex: _hex(candidate),
      publicAddress: addr,
    );
  }
  throw const TronWalletGenerationFailure(
    'Failed to derive a secp256k1-valid private key after 16 attempts.',
  );
}


String deriveTronAddressFromPrivateKeyHex(String privateKeyHex) {
  if (privateKeyHex.startsWith('0x') || privateKeyHex.startsWith('0X')) {
    privateKeyHex = privateKeyHex.substring(2);
  }
  if (privateKeyHex.length != 64) {
    throw ArgumentError(
      'TRON private key must be 64 hex chars (got '
      '${privateKeyHex.length}).',
    );
  }
  final keyBytes = _bytesFromHex(privateKeyHex);
  final keyBigInt = _bigIntFromBytes(keyBytes);
  if (keyBigInt <= BigInt.zero || keyBigInt >= _tronSecp256k1.n) {
    throw ArgumentError(
      'Private key value is outside the secp256k1 valid range [1, n).',
    );
  }
  return _deriveTronAddress(keyBigInt);
}


bool isValidTronAddress(String? raw) {
  if (raw == null) return false;
  final s = raw.trim();
  if (s.isEmpty) return false;
  if (!RegExp(r'^T[1-9A-HJ-NP-Za-km-z]{33}$').hasMatch(s)) return false;
  Uint8List decoded;
  try {
    decoded = base58Decode(s);
  } catch (_) {
    return false;
  }
  if (decoded.length != 25) return false;
  if (decoded[0] != kTronMainnetPrefix) return false;
  final payload = decoded.sublist(0, 21);
  final checksum = decoded.sublist(21);
  final expected = _doubleSha256(payload).sublist(0, 4);
  for (var i = 0; i < 4; i++) {
    if (expected[i] != checksum[i]) return false;
  }
  return true;
}


String base58Encode(Uint8List raw) {
  if (raw.isEmpty) return '';
  var n = BigInt.zero;
  for (final b in raw) {
    n = (n << 8) | BigInt.from(b);
  }
  var out = '';
  final base = BigInt.from(58);
  while (n > BigInt.zero) {
    final rem = (n % base).toInt();
    n = n ~/ base;
    out = kTronBase58Alphabet[rem] + out;
  }
  var leadingZeros = 0;
  for (final b in raw) {
    if (b == 0) {
      leadingZeros++;
    } else {
      break;
    }
  }
  return (kTronBase58Alphabet[0] * leadingZeros) + out;
}


Uint8List base58Decode(String s) {
  if (s.isEmpty) return Uint8List(0);
  var n = BigInt.zero;
  final base = BigInt.from(58);
  for (var i = 0; i < s.length; i++) {
    final idx = kTronBase58Alphabet.indexOf(s[i]);
    if (idx < 0) {
      throw ArgumentError('invalid base58 char: ${s[i]}');
    }
    n = n * base + BigInt.from(idx);
  }
  Uint8List body;
  if (n == BigInt.zero) {
    body = Uint8List(0);
  } else {
    final hex = n.toRadixString(16);
    final padded = hex.length.isOdd ? '0$hex' : hex;
    body = _bytesFromHex(padded);
  }
  var leadingOnes = 0;
  for (var i = 0; i < s.length; i++) {
    if (s[i] == '1') {
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


void wipeTronPrivateKeyHex(String hex) {

  hex.codeUnits;
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


String _deriveTronAddress(BigInt privateKey) {
  final point = _tronSecp256k1.G * privateKey;
  if (point == null) {
    throw const TronWalletGenerationFailure(
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
  final ethLast20 = hash.sublist(12);
  final payload = Uint8List(21);
  payload[0] = kTronMainnetPrefix;
  payload.setRange(1, 21, ethLast20);
  final checksum = _doubleSha256(payload).sublist(0, 4);
  final full = Uint8List(25);
  full.setRange(0, 21, payload);
  full.setRange(21, 25, checksum);
  return base58Encode(full);
}


Uint8List _doubleSha256(Uint8List raw) {
  final first = crypto.sha256.convert(raw).bytes;
  final second = crypto.sha256.convert(first).bytes;
  return Uint8List.fromList(second);
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
  if (hex.length.isOdd) {
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
